/**
 * T-50 (675) — «Хэн юунд арилжаа хийж байна» (AC-29, AC-30).
 *
 * Голууд:
 * - Мөр бүр origin шошготой.
 * - `external` позиц нь agent-ийн нэрээр ХЭЗЭЭ Ч харагдахгүй.
 * - Харагдацын symbol жагсаалт нь API-ийн буцаасантай ЯГ тэнцүү.
 */
import { describe, expect, it, vi, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';

import { AttributionPage } from './AttributionPage';
import { renderWithProviders, mockFetch } from '@/test/render';
import { attribution } from '@/test/fixtures';

afterEach(() => vi.unstubAllGlobals());

function renderPage() {
  vi.stubGlobal('fetch', vi.fn(mockFetch({ '/api/v1/attribution': { body: attribution } })));
  return renderWithProviders(<AttributionPage />);
}

describe('AttributionPage', () => {
  it('origin тус бүрээр нэг карт', async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId('attribution-group')).toHaveLength(2));
    const origins = screen
      .getAllByTestId('attribution-group')
      .map((node) => node.getAttribute('data-origin'));
    expect(origins).toEqual(['research_agent', 'external']);
  });

  it('AI-ийн картад provider/model харагдана', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText(/claude-mcp\/claude-opus-5/)).toBeInTheDocument());
  });

  it('external позиц нь agent-ийн нэрээр ХЭЗЭЭ Ч харагдахгүй', async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId('attribution-group')).toHaveLength(2));
    const external = screen
      .getAllByTestId('attribution-group')
      .find((node) => node.getAttribute('data-origin') === 'external')!;
    expect(external).toHaveTextContent('TSLA');
    expect(external).toHaveTextContent('локал бичлэггүй');
    expect(external).not.toHaveTextContent('claude');
    expect(external).not.toHaveTextContent('AI судалгааны agent');
  });

  it('symbol жагсаалт нь API-ийн буцаасантай тэнцүү', async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId('attribution-row')).toHaveLength(2));
    const shown = screen
      .getAllByTestId('attribution-row')
      .map((row) => row.getAttribute('data-symbol'));
    const expected = attribution.groups.flatMap((g) => g.symbols.map((s) => s.symbol));
    expect(shown.sort()).toEqual(expected.sort());
  });

  it('позицтой symbol-д ширхэг ба зах зээлийн үнэ харагдана', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('$9,012.00')).toBeInTheDocument());
    expect(screen.getByText('40 ш')).toBeInTheDocument();
  });

  it('шийдвэртэй мөрөөс «яагаад» холбоос гарна', async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId('why-link')).toHaveLength(1));
    expect(screen.getByTestId('why-link')).toHaveAttribute('href', '/decisions?symbol=AAPL');
  });

  it('хоосон үед таамаглахгүй, ил хэлнэ', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(mockFetch({ '/api/v1/attribution': { body: { ...attribution, groups: [] } } })),
    );
    renderWithProviders(<AttributionPage />);
    await waitFor(() => expect(screen.getByTestId('attribution-empty')).toBeInTheDocument());
  });
});
