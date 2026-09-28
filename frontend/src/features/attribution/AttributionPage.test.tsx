/**
 * T-50 (675) — "Who is trading what" (AC-29, AC-30).
 *
 * Core points:
 * - Every row is labeled with an origin.
 * - An `external` position is NEVER shown under an agent's name.
 * - The view's symbol list is EXACTLY what the API returned.
 */
import { describe, expect, it, vi, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';

import { AttributionPage } from './AttributionPage';
import { renderWithProviders, mockFetch } from '@/test/render';
import { attribution, mixedAttribution } from '@/test/fixtures';

afterEach(() => vi.unstubAllGlobals());

function renderPage() {
  vi.stubGlobal('fetch', vi.fn(mockFetch({ '/api/v1/attribution': { body: attribution } })));
  return renderWithProviders(<AttributionPage />);
}

describe('AttributionPage', () => {
  it('one card per origin', async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId('attribution-group')).toHaveLength(2));
    const origins = screen
      .getAllByTestId('attribution-group')
      .map((node) => node.getAttribute('data-origin'));
    expect(origins).toEqual(['research_agent', 'external']);
  });

  it("shows provider/model on the AI's card", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText(/claude-mcp\/claude-opus-5/)).toBeInTheDocument());
  });

  it('an external position is NEVER shown under an agent name', async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId('attribution-group')).toHaveLength(2));
    const external = screen
      .getAllByTestId('attribution-group')
      .find((node) => node.getAttribute('data-origin') === 'external')!;
    expect(external).toHaveTextContent('TSLA');
    expect(external).toHaveTextContent('no local record');
    expect(external).not.toHaveTextContent('claude');
    expect(external).not.toHaveTextContent('AI research agent');
  });

  it("the symbol list equals the API's response", async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId('attribution-row')).toHaveLength(2));
    const shown = screen
      .getAllByTestId('attribution-row')
      .map((row) => row.getAttribute('data-symbol'));
    const expected = attribution.groups.flatMap((g) => g.symbols.map((s) => s.symbol));
    expect(shown.sort()).toEqual(expected.sort());
  });

  it('shows quantity and market value for a symbol with a position', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('$9,012.00')).toBeInTheDocument());
    expect(screen.getByText('40 shares')).toBeInTheDocument();
  });

  it('a decided row shows a "why" link', async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId('why-link')).toHaveLength(1));
    expect(screen.getByTestId('why-link')).toHaveAttribute('href', '/decisions?symbol=AAPL');
  });

  it('mixed origin is marked on EVERY card (LLD §16.4)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(mockFetch({ '/api/v1/attribution': { body: mixedAttribution } })),
    );
    renderWithProviders(<AttributionPage />);
    await waitFor(() => expect(screen.getAllByTestId('attribution-row')).toHaveLength(2));
    const groups = screen
      .getAllByTestId('attribution-group')
      .map((node) => node.getAttribute('data-origin'));
    expect(groups.sort()).toEqual(['manual_operator', 'research_agent']);
    expect(screen.getAllByTestId('mixed-origin-badge')).toHaveLength(2);
  });

  it('a single-origin symbol shows NO mixed badge', async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId('attribution-row')).toHaveLength(2));
    expect(screen.queryByTestId('mixed-origin-badge')).toBeNull();
  });

  it('does not guess when empty, states it plainly', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(mockFetch({ '/api/v1/attribution': { body: { ...attribution, groups: [] } } })),
    );
    renderWithProviders(<AttributionPage />);
    await waitFor(() => expect(screen.getByTestId('attribution-empty')).toBeInTheDocument());
  });
});
