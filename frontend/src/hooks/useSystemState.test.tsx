/**
 * N-2 — heartbeat does not re-fetch REST.
 *
 * The `system` channel's heartbeat arrives every `HEARTBEAT_SECONDS`
 * (default 2s). Treating it as invalidation would make every idle tab
 * fetch `GET /system/state` — which itself calls the broker's
 * `get_account` — 30 times a minute. Heartbeat means "connection alive",
 * NOT "state changed".
 */
import { describe, expect, it, vi, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { useLiveSocket } from './useSystemState';
import type { BusMessage, SocketHandlers } from '@/lib/ws';

const handlers: { current: SocketHandlers | null } = { current: null };

vi.mock('@/lib/ws', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/ws')>();
  return {
    ...actual,
    connect: (h: SocketHandlers) => {
      handlers.current = h;
      return () => {};
    },
  };
});

afterEach(() => vi.restoreAllMocks());

function setup() {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, 'invalidateQueries');
  renderHook(() => useLiveSocket(), {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
  return { invalidate, send: (message: BusMessage) => handlers.current?.onMessage(message) };
}

describe('useLiveSocket (N-2)', () => {
  it('heartbeat does not re-fetch the query', () => {
    const { invalidate, send } = setup();
    send({ channel: 'system', payload: { event: 'heartbeat', ts: '2026-09-16T14:30:00Z' } });
    expect(invalidate).not.toHaveBeenCalled();
  });

  it('a real system event does re-fetch', () => {
    const { invalidate, send } = setup();
    send({ channel: 'system', payload: { event: 'state_changed', ts: '2026-09-16T14:30:00Z' } });
    expect(invalidate).toHaveBeenCalled();
  });

  it('a tick invalidates bars and quote for that symbol only', () => {
    const { invalidate, send } = setup();
    send({ channel: 'ticks:BTCUSD', payload: { event: 'tick', symbol: 'BTCUSD', price: '84123.45' } });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['bars', 'BTCUSD'] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['quote', 'BTCUSD'] });
  });
});
