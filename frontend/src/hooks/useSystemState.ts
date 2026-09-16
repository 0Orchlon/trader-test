/**
 * Системийн төлөв, горим, staleness — НЭГ эх сурвалж (LLD §16.1, §16.7).
 *
 * REST нь үнэний эх (TanStack Query). WS нь зөвхөн invalidation: мессеж
 * ирэхэд query дахин татагдана. WS-ээс UI-ийн төлөвийг ШУУД угсрахгүй.
 */
import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { connect, type BusMessage } from '@/lib/ws';

/** Сервер `HEARTBEAT_SECONDS` тутам мэдэгдэнэ; 5s чимээгүй бол stale. */
export const STALE_AFTER_MS = 5_000;
const TICK_MS = 1_000;

export const systemStateKey = ['system-state'] as const;

export function useSystemState() {
  return useQuery({
    queryKey: systemStateKey,
    queryFn: api.systemState,
    // Wind-down-ийн тоолуур секунд тутам биш, WS-ээр шинэчлэгдэнэ; энэ нь
    // WS бүрэн унасан үеийн нөөц зам.
    refetchInterval: 15_000,
  });
}

export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 30_000 });
}

/**
 * WS-ийн чимээгүй байдлыг хэмжинэ (AC-2).
 *
 * `onclose`-ыг ХҮЛЭЭХГҮЙ: сүлжээ унтарсан ч `onclose` ирэхгүй тохиолдол нь
 * хамгийн аюултай хэлбэр. Тиймээс сүүлийн МЕССЕЖИЙН цагаар шийднэ.
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
      if (channel === 'system') {
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
