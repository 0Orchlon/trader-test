/**
 * WebSocket client (asyncapi, LLD §16.1).
 *
 * **WS is NOT the source of truth.** REST is the source; WS is only for
 * invalidation + a live tick. Building UI state directly from WS messages
 * would drift after any disconnect.
 */
export type BusMessage = { channel: string; payload: Record<string, unknown> };

export type SocketHandlers = {
  onMessage: (message: BusMessage) => void;
  onOpen?: () => void;
  onClose?: () => void;
};

const RETRY_BASE_MS = 500;
const RETRY_MAX_MS = 15_000;

export function socketUrl(path = '/ws'): string {
  if (typeof window === 'undefined') return `ws://localhost${path}`;
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}${path}`;
}

export function retryDelay(attempt: number): number {
  return Math.min(RETRY_MAX_MS, RETRY_BASE_MS * 2 ** attempt);
}

/** Connection with reconnect retry. Returns a stop function. */
export function connect(handlers: SocketHandlers, url = socketUrl()): () => void {
  let socket: WebSocket | null = null;
  let attempt = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;

  const open = () => {
    if (stopped) return;
    socket = new WebSocket(url);
    socket.onopen = () => {
      attempt = 0;
      handlers.onOpen?.();
    };
    socket.onmessage = (event: MessageEvent) => {
      try {
        handlers.onMessage(JSON.parse(event.data as string) as BusMessage);
      } catch {
        // An unparseable message doesn't crash the UI — the next one arrives.
      }
    };
    socket.onclose = () => {
      handlers.onClose?.();
      if (stopped) return;
      timer = setTimeout(open, retryDelay(attempt));
      attempt += 1;
    };
    socket.onerror = () => socket?.close();
  };

  open();
  return () => {
    stopped = true;
    if (timer !== undefined) clearTimeout(timer);
    socket?.close();
  };
}
