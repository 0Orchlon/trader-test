/**
 * System state, mode, and staleness — ONE source of truth (LLD §16.1, §16.7).
 *
 * REST is the source of truth (TanStack Query). WS is invalidation only:
 * a message arriving re-fetches the query. UI state is never built
 * directly from WS.
 */
import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { connect, type BusMessage } from '@/lib/ws';

/** The server announces every `HEARTBEAT_SECONDS`; 5s of silence = stale. */
export const STALE_AFTER_MS = 5_000;
const TICK_MS = 1_000;

export const systemStateKey = ['system-state'] as const;

export function useSystemState() {
  return useQuery({
    queryKey: systemStateKey,
    queryFn: api.systemState,
    // The wind-down countdown isn't per-second here, it updates via WS;
    // this is the fallback path for when WS is fully down.
    refetchInterval: 15_000,
  });
}

export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 30_000 });
}

/**
 * Measures WS silence (AC-2).
 *
 * Does NOT wait on `onclose`: the network dropping without `onclose`
 * ever arriving is the most dangerous case. So this decides from the
 * timestamp of the last MESSAGE instead.
 */
export function useLiveSocket() {
  const queryClient = useQueryClient();
  const lastMessageAt = useRef<number>(0);
  const [stale, setStale] = useState(true);
  const [lastSeen, setLastSeen] = useState<string | null>(null);

  useEffect(() => {
    const handle = (message: BusMessage) => {
      lastMessageAt.current = Date.now();
      setLastSeen(new Date().toISOString());
      const channel = message.channel;
      // Heartbeat means "connection alive", NOT "state changed". Treating
      // it as invalidation would make every idle tab fetch
      // `GET /system/state` (which itself calls the broker's
      // `get_account`) 30 times a minute (N-2).
      if (channel === 'system' && message.payload?.event !== 'heartbeat') {
        void queryClient.invalidateQueries({ queryKey: systemStateKey });
        void queryClient.invalidateQueries({ queryKey: ['providers'] });
      }
      if (channel === 'orders') {
        void queryClient.invalidateQueries({ queryKey: ['orders'] });
        void queryClient.invalidateQueries({ queryKey: ['positions'] });
        void queryClient.invalidateQueries({ queryKey: ['attribution'] });
      }
      if (channel === 'agent-decisions') {
        void queryClient.invalidateQueries({ queryKey: ['decisions'] });
        void queryClient.invalidateQueries({ queryKey: ['approvals'] });
      }
      // Live price tick (T-99, personal project) — same invalidation
      // pattern as orders/decisions above, not a source of UI state
      // (see lib/ws.ts). Refetches bars/quote as soon as a trade prints,
      // instead of waiting for the next REST poll interval.
      if (channel.startsWith('ticks:')) {
        const symbol = message.payload?.symbol;
        if (typeof symbol === 'string') {
          void queryClient.invalidateQueries({ queryKey: ['bars', symbol] });
          void queryClient.invalidateQueries({ queryKey: ['quote', symbol] });
        }
      }
    };
    const disconnect = connect({ onMessage: handle });
    const timer = setInterval(() => {
      setStale(Date.now() - lastMessageAt.current > STALE_AFTER_MS);
    }, TICK_MS);
    return () => {
      disconnect();
      clearInterval(timer);
    };
  }, [queryClient]);

  return { stale, lastSeen };
}
