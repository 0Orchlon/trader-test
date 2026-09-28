import { vi } from 'vitest';
import '@testing-library/jest-dom/vitest';

/**
 * `lightweight-charts` needs a real canvas 2D context to draw — jsdom has
 * none, and it schedules its first draw via `requestAnimationFrame`
 * regardless of container width, so no width guard in the component avoids
 * it. Mocked once here (same spirit as the `matchMedia`/`ResizeObserver`
 * shims below) rather than worked around per test file.
 */
vi.mock('lightweight-charts', () => ({
  createChart: () => ({
    addSeries: () => ({ setData: () => {}, createPriceLine: () => {} }),
    applyOptions: () => {},
    timeScale: () => ({ fitContent: () => {} }),
    remove: () => {},
  }),
  CandlestickSeries: {},
  LineSeries: {},
  LineStyle: { Solid: 0, Dotted: 1, Dashed: 2 },
}));

/** Browser APIs jsdom lacks but Mantine requires. */
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

if (!window.scrollTo) {
  window.scrollTo = (() => {}) as typeof window.scrollTo;
}

/** WebSocket — tests NEVER touch the real network. */
class FakeSocket {
  static instances: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  readonly url: string;

  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }

  close() {
    this.onclose?.();
  }

  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket;
export { FakeSocket };
