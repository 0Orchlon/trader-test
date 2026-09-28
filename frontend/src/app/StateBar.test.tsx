/**
 * T-29 (656) · T-51 (676) — mode indicator and three buttons (AC-20, AC-38).
 *
 * Core points:
 * - Every mode has a distinct label; unknown does NOT mean `paper`.
 * - `Kill switch` fires with NO confirmation.
 * - `Wind down` and `Activate` have DIFFERENT confirmation behavior.
 * - `Activate`'s prompt text comes from the backend's `confirmation.prompt`.
 */
import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ModeBanner } from './ModeBanner';
import { StateBar } from './StateBar';
import { StalenessBanner } from './AppShell';
import { renderWithProviders } from '@/test/render';
import {
  haltedState,
  liveState,
  systemState,
  unmeasuredBreakerState,
  windingDownState,
} from '@/test/fixtures';

describe('ModeBanner (AC-20)', () => {
  it('marks paper mode visibly', () => {
    renderWithProviders(<ModeBanner source="alpaca_paper" />);
    expect(screen.getByTestId('mode-banner')).toHaveAttribute('data-source', 'alpaca_paper');
    expect(screen.getByText(/PAPER — fake money/)).toBeInTheDocument();
  });

  it('shows live mode with DIFFERENT text and color', () => {
    renderWithProviders(<ModeBanner source="alpaca_live" />);
    expect(screen.getByText(/LIVE — REAL MONEY/)).toBeInTheDocument();
  });

  it('separates backtest mode', () => {
    renderWithProviders(<ModeBanner source="backtest" />);
    expect(screen.getByText(/BACKTEST — historical data/)).toBeInTheDocument();
  });

  it('does NOT assume unknown mode is paper', () => {
    renderWithProviders(<ModeBanner source={undefined} />);
    expect(screen.getByTestId('mode-banner')).toHaveAttribute('data-source', 'unknown');
    expect(screen.getByText(/MODE UNKNOWN/)).toBeInTheDocument();
  });

  it('reads live mode from source, not a guess', () => {
    renderWithProviders(<ModeBanner source={liveState.source} />);
    expect(screen.getByTestId('mode-banner')).toHaveAttribute('data-source', 'alpaca_live');
  });
});

describe('StateBar (AC-38)', () => {
  it('disables Activate while active', () => {
    renderWithProviders(<StateBar state={systemState} />);
    expect(screen.getByTestId('state-badge')).toHaveTextContent('ACTIVE');
    expect(screen.getByTestId('activate')).toBeDisabled();
    expect(screen.getByTestId('wind-down')).toBeEnabled();
    expect(screen.getByTestId('kill-switch')).toBeEnabled();
  });

  it('shows the reason while halted, disables wind-down', () => {
    renderWithProviders(<StateBar state={haltedState} />);
    expect(screen.getByTestId('halt-reason')).toHaveTextContent('Daily loss limit exceeded');
    expect(screen.getByTestId('wind-down')).toBeDisabled();
    expect(screen.getByTestId('activate')).toBeEnabled();
  });

  it('shows a countdown of remaining time while winding down', () => {
    renderWithProviders(<StateBar state={windingDownState} />);
    expect(screen.getByTestId('wind-down-countdown')).toHaveTextContent('12:34');
  });

  it('kill switch fires immediately with NO confirmation', async () => {
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response(JSON.stringify(haltedState), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    renderWithProviders(<StateBar state={systemState} />);
    await userEvent.click(screen.getByTestId('kill-switch'));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.queryByTestId('confirm-prompt')).not.toBeInTheDocument();
    expect(String(fetchMock.mock.calls.at(0)?.[0] ?? '')).toContain('/kill-switch');
    vi.unstubAllGlobals();
  });

  it('wind down fires immediately with NO confirmation (N-6)', async () => {
    // No confirmation on a risk-REDUCING action — wind-down is not one of
    // §8.4's three actions. This keeps policy text out of the UI.
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response(JSON.stringify(systemState), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    renderWithProviders(<StateBar state={systemState} />);
    await userEvent.click(screen.getByTestId('wind-down'));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(String(fetchMock.mock.calls.at(0)?.[0] ?? '')).toContain('/system/wind-down');
    expect(screen.queryByTestId('confirm-prompt')).not.toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it('activate prompt comes from the backend', async () => {
    const problem = {
      type: 'https://personal-3.invalid/problems/confirmation_required',
      title: 'Confirmation required',
      status: 409,
      code: 'confirmation_required',
      detail: 'explicit confirmation required',
      confirmation: {
        token: 'tok-1',
        prompt: 'ACTIVATE the system? Agent and algorithmic trading will resume.',
        expires_at: '2026-09-16T14:35:00Z',
      },
    };
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify(problem), { status: 409 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    renderWithProviders(<StateBar state={haltedState} />);
    await userEvent.click(screen.getByTestId('activate'));

    await waitFor(() =>
      expect(screen.getByTestId('confirm-prompt')).toHaveTextContent(/ACTIVATE the system/),
    );
    // Text is not hard-coded in the UI — no second source of truth (LLD §16.3).
    expect(screen.getByTestId('confirm-prompt')).not.toHaveTextContent(/wind down/i);
    vi.unstubAllGlobals();
  });

  it("shows breaker's CURRENT metrics before activating (AC-37)", async () => {
    const problem = {
      status: 409,
      code: 'confirmation_required',
      title: 'x',
      type: 'x',
      confirmation: { token: 't', prompt: 'Activate?', expires_at: 'x' },
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(problem), { status: 409 })),
    );

    renderWithProviders(<StateBar state={haltedState} />);
    await userEvent.click(screen.getByTestId('activate'));

    await waitFor(() => expect(screen.getByTestId('breaker-metrics')).toBeInTheDocument());
    expect(screen.getByTestId('breaker-metrics')).toHaveTextContent('daily_loss');
    vi.unstubAllGlobals();
  });

  it('an unmeasured metric is never shown as "normal" (B-1)', async () => {
    const problem = {
      status: 409,
      code: 'confirmation_required',
      title: 'x',
      type: 'x',
      confirmation: { token: 't', prompt: 'Activate?', expires_at: 'x' },
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(problem), { status: 409 })),
    );

    renderWithProviders(<StateBar state={unmeasuredBreakerState} />);
    await userEvent.click(screen.getByTestId('activate'));

    await waitFor(() => expect(screen.getByTestId('breaker-metrics')).toBeInTheDocument());
    const row = screen.getByTestId('breaker-metric-api_error_rate');
    expect(row).toHaveTextContent('UNMEASURED');
    expect(row).not.toHaveTextContent('0.0000');
    vi.unstubAllGlobals();
  });
});

describe('StalenessBanner (AC-2)', () => {
  it('shows the UTC time of the last message', () => {
    renderWithProviders(<StalenessBanner lastSeen="2026-09-16T14:29:58Z" />);
    expect(screen.getByTestId('staleness-banner')).toHaveTextContent('14:29:58Z');
    expect(screen.getByTestId('staleness-banner')).toHaveTextContent(/may be STALE/);
  });
});
