/**
 * N-5 · LLD §16.2, §19 point 14 — ONE table never shows TWO `source`
 * labels at once.
 *
 * The backend has a guard (`MixedSourceError`), but each tool call
 * arrives with its own `source`, so a table can still end up mixed: a
 * live call and a backtest call under one decision. At that point "which
 * one is real" becomes ambiguous — this is EXACTLY the most dangerous
 * case (AC-21).
 */
import { describe, expect, it, vi, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { DecisionsPage } from './DecisionsPage';
import { renderWithProviders, mockFetch } from '@/test/render';

afterEach(() => vi.unstubAllGlobals());

const DECISION_ID = '3c9d8e7f-6a5b-4c3d-8e1f-0a9b8c7d6e5f';

const feed = {
  decisions: [
    {
      id: DECISION_ID,
      agent: 'research',
      provider: 'claude-mcp',
      model: 'claude-opus-5',
      outcome: 'approved',
      created_at: '2026-09-16T13:55:02Z',
      proposal: {
        symbol: 'AAPL',
        side: 'buy',
        qty: '10',
        rationale: 'Proposing to enter at the last price of 221.50.',
        estimated_notional: '2215.00',
      },
    },
  ],
  source: 'alpaca_paper',
  as_of: '2026-09-16T13:55:03Z',
  system_state: 'active',
};

function toolCall(id: string, source: string) {
  return {
    id,
    tool_name: 'get_quote',
    source,
    called_at: '2026-09-16T13:55:01Z',
    latency_ms: 42,
    request: { symbol: 'AAPL' },
    response: { data: { last: '221.50' } },
  };
}

function renderWith(sources: string[], grounding: Record<string, unknown> = { passed: true, unverified_claims: [] }) {
  const detail = {
    ...feed.decisions[0],
    grounding,
    tool_calls: sources.map((source, index) => toolCall(`c${index}`, source)),
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(
      mockFetch({
        [`/api/v1/agent-decisions/${DECISION_ID}`]: { body: detail },
        // The list row is the source of truth for the summary (grounding comes from the row).
        '/api/v1/agent-decisions': {
          body: { ...feed, decisions: [{ ...feed.decisions[0], grounding }] },
        },
      }),
    ),
  );
  return renderWithProviders(<DecisionsPage />);
}

/** Opens a row — the tool call table is inside the expanded panel. */
async function openDetail() {
  await waitFor(() => expect(screen.getByTestId('decision-row')).toBeInTheDocument());
  await userEvent.click(screen.getByTestId('decision-row'));
}

describe('DecisionsPage — tool call table source', () => {
  it('a single source shows its label ONCE for the whole table', async () => {
    renderWith(['alpaca_paper', 'alpaca_paper']);
    await openDetail();
    await waitFor(() => expect(screen.getAllByTestId('tool-call-row')).toHaveLength(2));
    expect(screen.getByTestId('tool-calls-table')).toBeInTheDocument();
    const labels = screen.getAllByTestId('tool-calls-source');
    expect(labels).toHaveLength(1);
    expect(labels[0]).toHaveTextContent('alpaca_paper');
  });

  it('a grounding check that did not run is NEVER labeled "failed" (N-3)', async () => {
    renderWith(['alpaca_paper'], {
      passed: false,
      not_run: true,
      unverified_claims: [],
      checked_claims: 0,
    });
    await openDetail();
    await waitFor(() => expect(screen.getByTestId('decision-grounding')).toBeInTheDocument());
    expect(screen.getByTestId('decision-grounding')).toHaveTextContent('not run');
    expect(screen.getByTestId('decision-grounding')).not.toHaveTextContent('FAILED');
  });

  it('shows the ACTUAL count checked — 0 does not render green as "passed" (N-4)', async () => {
    renderWith(['alpaca_paper'], { passed: true, unverified_claims: [], checked_claims: 0 });
    await openDetail();
    await waitFor(() => expect(screen.getByTestId('decision-grounding')).toBeInTheDocument());
    expect(screen.getByTestId('decision-grounding')).toHaveTextContent('0 claims checked');
  });

  it('a larger checked count is shown too', async () => {
    renderWith(['alpaca_paper'], { passed: true, unverified_claims: [], checked_claims: 12 });
    await openDetail();
    await waitFor(() => expect(screen.getByTestId('decision-grounding')).toBeInTheDocument());
    expect(screen.getByTestId('decision-grounding')).toHaveTextContent('12 claims checked');
  });

  it('a mixed source hides the table and shows an explicit warning', async () => {
    renderWith(['alpaca_paper', 'backtest']);
    await openDetail();
    await waitFor(() => expect(screen.getByTestId('mixed-source')).toBeInTheDocument());
    expect(screen.queryByTestId('tool-calls-table')).not.toBeInTheDocument();
    expect(screen.getByTestId('mixed-source')).toHaveTextContent('backtest');
  });
});
