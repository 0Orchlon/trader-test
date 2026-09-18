/**
 * N-2 — heartbeat нь REST-ийг дахин татахгүй.
 *
 * `system` сувгийн heartbeat нь `HEARTBEAT_SECONDS` (анхдагч 2s) тутам ирдэг.
 * Түүнийг invalidation гэж үзвэл сул зогсож буй таб бүр минутад 30 удаа
 * `GET /system/state` татна — тэр бүр нь broker-ийн `get_account`. Heartbeat
 * нь «холболт амьд» гэсэн үг, «төлөв өөрчлөгдсөн» гэсэн үг БИШ.
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
  it('heartbeat нь query-г дахин татахгүй', () => {
    const { invalidate, send } = setup();
    send({ channel: 'system', payload: { event: 'heartbeat', ts: '2026-09-16T14:30:00Z' } });
    expect(invalidate).not.toHaveBeenCalled();
  });

  it('бодит системийн үйл явдал нь татна', () => {
    const { invalidate, send } = setup();
    send({ channel: 'system', payload: { event: 'state_changed', ts: '2026-09-16T14:30:00Z' } });
    expect(invalidate).toHaveBeenCalled();
  });
});
