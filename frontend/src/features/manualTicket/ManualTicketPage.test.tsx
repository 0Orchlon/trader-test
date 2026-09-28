/**
 * T-49 (674) — Manual trade ticket (AC-31, AC-33).
 *
 * DoD:
 * (a) submit is DISABLED while `halted`;
 * (b) an order over the threshold cannot be submitted without confirmation;
 * (c) `winding_down` disallows a risk-increasing direction.
 */
import { describe, expect, it, vi, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ManualTicketPage, allowedSides, idempotencyKeyFor } from './ManualTicketPage';
import { renderWithProviders, mockFetch } from '@/test/render';
import {
  haltedState,
  positions,
  quote,
  staleQuote,
  systemState,
  windingDownState,
} from '@/test/fixtures';

afterEach(() => vi.unstubAllGlobals());

function renderTicket(state = systemState, extra: Record<string, { status?: number; body: unknown }> = {}) {
  const fetchMock = vi.fn(
    mockFetch({
      '/api/v1/system/state': { body: state },
      '/api/v1/positions': { body: positions },
      '/api/v1/market/quote/': { body: quote },
      ...extra,
    }),
  );
  vi.stubGlobal('fetch', fetchMock);
  return { fetchMock, ...renderWithProviders(<ManualTicketPage />) };
}

describe('allowedSides (AC-33)', () => {
  it('both while active', () => {
    expect(allowedSides('active', null)).toEqual(['buy', 'sell']);
  });

  it('neither while halted', () => {
    expect(allowedSides('halted', '40')).toEqual([]);
  });

  it('wind-down + long position → sell only', () => {
    expect(allowedSides('winding_down', '40')).toEqual(['sell']);
  });

  it('wind-down + short position → buy only', () => {
    expect(allowedSides('winding_down', '-40')).toEqual(['buy']);
  });

  it('wind-down + no position → neither (new risk)', () => {
    expect(allowedSides('winding_down', null)).toEqual([]);
  });
});

describe('idempotencyKeyFor', () => {
  const body = { symbol: 'AAPL', side: 'buy', qty: '10', order_type: 'limit', time_in_force: 'day' } as const;

  it('same body + same attempt → same key (confirmation\'s second call)', () => {
    expect(idempotencyKeyFor(body, 'attempt-1')).toBe(idempotencyKeyFor({ ...body }, 'attempt-1'));
  });

  it('same body + NEW attempt → DIFFERENT key (B-3: a resubmit is not swallowed)', () => {
    expect(idempotencyKeyFor(body, 'attempt-1')).not.toBe(idempotencyKeyFor(body, 'attempt-2'));
  });

  it('different body → different key', () => {
    expect(idempotencyKeyFor(body, 'attempt-1')).not.toBe(
      idempotencyKeyFor({ ...body, qty: '11' }, 'attempt-1'),
    );
  });

  it('is UUID-shaped', () => {
    expect(idempotencyKeyFor(body, 'attempt-1')).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });
});

describe('ManualTicketPage', () => {
  it('submit disabled + reason shown while halted', async () => {
    renderTicket(haltedState);
    await waitFor(() => expect(screen.getByTestId('halted-notice')).toBeInTheDocument());
    expect(screen.getByTestId('halted-notice')).toHaveTextContent('Daily loss limit exceeded');
    expect(screen.getByTestId('ticket-submit')).toBeDisabled();
  });

  it('shows a notice while winding down', async () => {
    renderTicket(windingDownState);
    await waitFor(() => expect(screen.getByTestId('wind-down-notice')).toBeInTheDocument());
    expect(screen.getByTestId('wind-down-notice')).toHaveTextContent('REDUCING');
  });

  it('notional is computed from the last quote (LLD §16.5)', async () => {
    renderTicket();
    await userEvent.type(screen.getByTestId('ticket-symbol'), 'AAPL');
    await userEvent.type(screen.getByTestId('ticket-qty'), '10');
    await userEvent.type(screen.getByTestId('ticket-limit-price'), '221.50');
    await waitFor(() =>
      expect(screen.getByTestId('ticket-notional')).toHaveTextContent('$2,215.00'),
    );
  });

  it('shows a figure on a market order too — even with limit price disabled', async () => {
    renderTicket();
    await userEvent.type(screen.getByTestId('ticket-symbol'), 'AAPL');
    await userEvent.type(screen.getByTestId('ticket-qty'), '10');
    await userEvent.click(screen.getByTestId('ticket-order-type'));
    await userEvent.click(await screen.findByText('Market'));
    expect(screen.getByTestId('ticket-limit-price')).toBeDisabled();
    await waitFor(() =>
      expect(screen.getByTestId('ticket-notional')).toHaveTextContent('$2,215.00'),
    );
  });

  it("on a limit order the reference price is the LIMIT price — matches Risk's R9 (N-1)", async () => {
    // `app/risk/rules.py::reference_price` uses `limit_price` when it is
    // set. The UI used to always take `quote.last`, so the on-screen
    // figure and the backend's check figure disagreed, breaking §16.5's promise.
    renderTicket();
    await userEvent.type(screen.getByTestId('ticket-symbol'), 'AAPL');
    await userEvent.type(screen.getByTestId('ticket-qty'), '10');
    await userEvent.type(screen.getByTestId('ticket-limit-price'), '300.00');
    await waitFor(() =>
      expect(screen.getByTestId('ticket-notional')).toHaveTextContent('$3,000.00'),
    );
    expect(screen.getByTestId('ticket-notional')).toHaveTextContent('limit price');
  });

  it('a stale quote is marked VISIBLY', async () => {
    renderTicket(systemState, { '/api/v1/market/quote/': { body: staleQuote } });
    await userEvent.type(screen.getByTestId('ticket-symbol'), 'AAPL');
    await userEvent.type(screen.getByTestId('ticket-qty'), '10');
    await waitFor(() => expect(screen.getByTestId('quote-stale')).toBeInTheDocument());
  });

  it('with no quote, the figure is NEVER fabricated — the reason is stated', async () => {
    renderTicket(systemState, {
      '/api/v1/market/quote/': {
        status: 503,
        body: { type: 'x', title: 'x', status: 503, code: 'broker_unavailable', detail: 'no quote available' },
      },
    });
    await userEvent.type(screen.getByTestId('ticket-symbol'), 'NOPE');
    await userEvent.type(screen.getByTestId('ticket-qty'), '10');
    await waitFor(() =>
      expect(screen.getByTestId('ticket-notional')).toHaveTextContent('no quote'),
    );
  });

  it('an order over the threshold cannot be submitted without confirmation', async () => {
    const problem = {
      type: 'x',
      title: 'x',
      status: 409,
      code: 'confirmation_required',
      detail: 'over the limit',
      confirmation: {
        token: 'tok-9',
        prompt: 'Send this MANUAL ORDER? It exceeds the limit.',
        expires_at: '2026-09-16T14:35:00Z',
      },
      risk: {
        decision: 'ESCALATE_TO_HUMAN',
        reason: 'Notional 6645.00 > MAX_ORDER_NOTIONAL 5000.00',
        evaluated_at: '2026-09-16T14:30:00Z',
        checks: [
          {
            rule: 'order_notional',
            passed: false,
            limit_name: 'MAX_ORDER_NOTIONAL',
            limit_value: '5000.00',
            actual_value: '6645.00',
          },
        ],
      },
    };
    const { fetchMock } = renderTicket(systemState, {
      '/api/v1/orders/manual': { status: 409, body: problem },
    });

    await userEvent.type(screen.getByTestId('ticket-symbol'), 'AAPL');
    await userEvent.type(screen.getByTestId('ticket-qty'), '30');
    await userEvent.type(screen.getByTestId('ticket-limit-price'), '221.50');
    await userEvent.click(screen.getByTestId('ticket-submit'));

    await waitFor(() =>
      expect(screen.getByTestId('ticket-confirm-prompt')).toHaveTextContent(/MANUAL ORDER/),
    );
    // Risk's preview comes from the 409's body — no separate dry-run exists.
    expect(screen.getByTestId('risk-preview')).toHaveTextContent('order_notional');
    expect(screen.getByTestId('risk-preview')).toHaveTextContent('6645.00');

    const manualCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes('/orders/manual'),
    );
    expect(manualCalls).toHaveLength(1);
  });

  it("confirmation's second call carries the SAME Idempotency-Key", async () => {
    const problem = {
      type: 'x',
      title: 'x',
      status: 409,
      code: 'confirmation_required',
      detail: 'over the limit',
      confirmation: { token: 'tok-9', prompt: 'Confirm?', expires_at: 'x' },
    };
    const { fetchMock } = renderTicket(systemState, {
      '/api/v1/orders/manual': { status: 409, body: problem },
    });

    await userEvent.type(screen.getByTestId('ticket-symbol'), 'AAPL');
    await userEvent.type(screen.getByTestId('ticket-qty'), '30');
    await userEvent.click(screen.getByTestId('ticket-submit'));
    await waitFor(() => expect(screen.getByTestId('ticket-confirm-accept')).toBeInTheDocument());
    await userEvent.click(screen.getByTestId('ticket-confirm-accept'));

    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter(([url]) => String(url).includes('/orders/manual'));
      expect(calls).toHaveLength(2);
    });
    const keys = fetchMock.mock.calls
      .filter((call) => String(call[0]).includes('/orders/manual'))
      .map((call) => (call[1]?.headers ?? {}) as Record<string, string>)
      .map((headers) => headers['Idempotency-Key']);
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it('resubmitting the SAME form gets a DIFFERENT Idempotency-Key (B-3)', async () => {
    const accepted = {
      source: 'alpaca_paper',
      as_of: '2026-09-16T14:30:00Z',
      stale: false,
      system_state: 'active',
      order: {
        id: 'o-1',
        broker_order_id: null,
        client_order_id: 'p3-abc123',
        symbol: 'AAPL',
        side: 'buy',
        qty: '10',
        filled_qty: '0',
        order_type: 'limit',
        time_in_force: 'day',
        status: 'accepted',
        origin: 'manual_operator',
        origin_detail: 'operator',
        decision_id: null,
        submitted_at: '2026-09-16T14:30:00Z',
      },
      risk: { decision: 'APPROVE', reason: null, evaluated_at: '2026-09-16T14:30:00Z', checks: [] },
    };
    const { fetchMock } = renderTicket(systemState, {
      '/api/v1/orders/manual': { status: 202, body: accepted },
    });

    await userEvent.type(screen.getByTestId('ticket-symbol'), 'AAPL');
    await userEvent.type(screen.getByTestId('ticket-qty'), '10');
    await userEvent.click(screen.getByTestId('ticket-submit'));
    await waitFor(() => expect(screen.getByTestId('ticket-accepted')).toBeInTheDocument());
    await userEvent.click(screen.getByTestId('ticket-submit'));

    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter(([url]) => String(url).includes('/orders/manual'));
      expect(calls).toHaveLength(2);
    });
    const keys = fetchMock.mock.calls
      .filter((call) => String(call[0]).includes('/orders/manual'))
      .map((call) => ((call[1]?.headers ?? {}) as Record<string, string>)['Idempotency-Key']);
    expect(keys[0]).not.toBe(keys[1]);
  });

  it('a Risk rejection shows the reason + every check', async () => {
    const problem = {
      type: 'x',
      title: 'x',
      status: 422,
      code: 'risk_rejected',
      detail: 'restricted_symbol: GME vs RESTRICTED_SYMBOLS GME,AMC',
      risk: {
        decision: 'REJECT',
        reason: 'restricted_symbol',
        evaluated_at: '2026-09-16T14:30:00Z',
        checks: [
          { rule: 'restricted_symbol', passed: false, limit_name: 'RESTRICTED_SYMBOLS', limit_value: 'GME' },
          { rule: 'system_state', passed: true },
        ],
      },
    };
    renderTicket(systemState, { '/api/v1/orders/manual': { status: 422, body: problem } });

    await userEvent.type(screen.getByTestId('ticket-symbol'), 'GME');
    await userEvent.type(screen.getByTestId('ticket-qty'), '10');
    await userEvent.click(screen.getByTestId('ticket-submit'));

    await waitFor(() => expect(screen.getByTestId('ticket-problem')).toHaveTextContent('risk_rejected'));
    expect(screen.getAllByTestId('risk-check')).toHaveLength(2);
  });

  it('a successful submit shows the client_order_id', async () => {
    const accepted = {
      source: 'alpaca_paper',
      as_of: '2026-09-16T14:30:00Z',
      stale: false,
      system_state: 'active',
      order: {
        id: 'o-1',
        broker_order_id: null,
        client_order_id: 'p3-abc123',
        symbol: 'AAPL',
        side: 'buy',
        qty: '10',
        filled_qty: '0',
        order_type: 'limit',
        time_in_force: 'day',
        status: 'accepted',
        origin: 'manual_operator',
        origin_detail: 'operator',
        decision_id: null,
        submitted_at: '2026-09-16T14:30:00Z',
      },
      risk: { decision: 'APPROVE', reason: null, evaluated_at: '2026-09-16T14:30:00Z', checks: [] },
    };
    renderTicket(systemState, { '/api/v1/orders/manual': { status: 202, body: accepted } });

    await userEvent.type(screen.getByTestId('ticket-symbol'), 'AAPL');
    await userEvent.type(screen.getByTestId('ticket-qty'), '10');
    await userEvent.click(screen.getByTestId('ticket-submit'));

    await waitFor(() =>
      expect(screen.getByTestId('ticket-accepted')).toHaveTextContent('p3-abc123'),
    );
  });
});
