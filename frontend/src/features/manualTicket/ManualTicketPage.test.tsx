/**
 * T-49 (674) — Гарын арилжааны ticket (AC-31, AC-33).
 *
 * DoD:
 * (а) `halted` төлөвт илгээх товч ИДЭВХГҮЙ;
 * (б) босгоос дээш order баталгаажуулалтгүйгээр илгээгдэхгүй;
 * (в) `winding_down` үед нэмэгдүүлэх чиглэл сонгох боломжгүй.
 */
import { describe, expect, it, vi, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ManualTicketPage, allowedSides, idempotencyKeyFor } from './ManualTicketPage';
import { renderWithProviders, mockFetch } from '@/test/render';
import { haltedState, positions, systemState, windingDownState } from '@/test/fixtures';

afterEach(() => vi.unstubAllGlobals());

function renderTicket(state = systemState, extra: Record<string, { status?: number; body: unknown }> = {}) {
  const fetchMock = vi.fn(
    mockFetch({
      '/api/v1/system/state': { body: state },
      '/api/v1/positions': { body: positions },
      ...extra,
    }),
  );
  vi.stubGlobal('fetch', fetchMock);
  return { fetchMock, ...renderWithProviders(<ManualTicketPage />) };
}

describe('allowedSides (AC-33)', () => {
  it('идэвхтэй үед хоёул', () => {
    expect(allowedSides('active', null)).toEqual(['buy', 'sell']);
  });

  it('зогссон үед аль нь ч биш', () => {
    expect(allowedSides('halted', '40')).toEqual([]);
  });

  it('wind-down + long позиц → зөвхөн зарах', () => {
    expect(allowedSides('winding_down', '40')).toEqual(['sell']);
  });

  it('wind-down + short позиц → зөвхөн авах', () => {
    expect(allowedSides('winding_down', '-40')).toEqual(['buy']);
  });

  it('wind-down + позицгүй → аль нь ч биш (шинэ эрсдэл)', () => {
    expect(allowedSides('winding_down', null)).toEqual([]);
  });
});

describe('idempotencyKeyFor', () => {
  it('ижил бие → ижил key (баталгаажуулалтын хоёр дахь дуудалт)', () => {
    const body = { symbol: 'AAPL', side: 'buy', qty: '10', order_type: 'limit', time_in_force: 'day' } as const;
    expect(idempotencyKeyFor(body)).toBe(idempotencyKeyFor({ ...body }));
  });

  it('өөр бие → өөр key', () => {
    const base = { symbol: 'AAPL', side: 'buy', qty: '10', order_type: 'limit', time_in_force: 'day' } as const;
    expect(idempotencyKeyFor(base)).not.toBe(idempotencyKeyFor({ ...base, qty: '11' }));
  });

  it('UUID хэлбэртэй', () => {
    const key = idempotencyKeyFor({
      symbol: 'AAPL',
      side: 'buy',
      qty: '10',
      order_type: 'limit',
      time_in_force: 'day',
    });
    expect(key).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}$/);
  });
});

describe('ManualTicketPage', () => {
  it('halted үед илгээх товч идэвхгүй + шалтгаан харагдана', async () => {
    renderTicket(haltedState);
    await waitFor(() => expect(screen.getByTestId('halted-notice')).toBeInTheDocument());
    expect(screen.getByTestId('halted-notice')).toHaveTextContent('Өдрийн алдагдлын хязгаар давсан');
    expect(screen.getByTestId('ticket-submit')).toBeDisabled();
  });

  it('winding_down үед анхааруулга харагдана', async () => {
    renderTicket(windingDownState);
    await waitFor(() => expect(screen.getByTestId('wind-down-notice')).toBeInTheDocument());
    expect(screen.getByTestId('wind-down-notice')).toHaveTextContent('БАГАСГАХ');
  });

  it('notional нь тэмдэгт мөрөөр тооцогдоно', async () => {
    renderTicket();
    await userEvent.type(screen.getByTestId('ticket-symbol'), 'AAPL');
    await userEvent.type(screen.getByTestId('ticket-qty'), '10');
    await userEvent.type(screen.getByTestId('ticket-limit-price'), '221.50');
    await waitFor(() =>
      expect(screen.getByTestId('ticket-notional')).toHaveTextContent('$2,215.00'),
    );
  });

  it('босгоос дээш order баталгаажуулалтгүйгээр илгээгдэхгүй', async () => {
    const problem = {
      type: 'x',
      title: 'x',
      status: 409,
      code: 'confirmation_required',
      detail: 'хязгаараас дээш',
      confirmation: {
        token: 'tok-9',
        prompt: 'Энэ хэмжээний ГАРЫН ORDER-ыг илгээх үү? Хязгаараас дээш байна.',
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
      expect(screen.getByTestId('ticket-confirm-prompt')).toHaveTextContent(/ГАРЫН ORDER/),
    );
    // Risk-ийн урьдчилсан үнэлгээ нь 409-ийн биеэс — тусдаа dry-run БАЙХГҮЙ.
    expect(screen.getByTestId('risk-preview')).toHaveTextContent('order_notional');
    expect(screen.getByTestId('risk-preview')).toHaveTextContent('6645.00');

    const manualCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes('/orders/manual'),
    );
    expect(manualCalls).toHaveLength(1);
  });

  it('баталгаажуулалтын хоёр дахь дуудалт ИЖИЛ Idempotency-Key-тэй', async () => {
    const problem = {
      type: 'x',
      title: 'x',
      status: 409,
      code: 'confirmation_required',
      detail: 'хязгаараас дээш',
      confirmation: { token: 'tok-9', prompt: 'Батлах уу?', expires_at: 'x' },
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

  it('Risk татгалзвал шалтгаан + бүх шалгалт харагдана', async () => {
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

  it('амжилттай илгээлтэд client_order_id харагдана', async () => {
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
