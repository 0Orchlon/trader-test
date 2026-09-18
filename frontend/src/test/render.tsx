/** Тестийн нийтлэг угсралт — Mantine + Query + Router. */
import type { ReactElement, ReactNode } from 'react';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { render, type RenderOptions } from '@testing-library/react';

export function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
}

export function renderWithProviders(
  ui: ReactElement,
  { route = '/', ...options }: RenderOptions & { route?: string } = {},
) {
  const client = makeClient();
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <MantineProvider>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>
  );
  return { client, ...render(ui, { wrapper: Wrapper, ...options }) };
}

/** `fetch`-ийг зам тус бүрээр орлуулна. Сүлжээнд ХЭЗЭЭ Ч хүрэхгүй. */
export function mockFetch(routes: Record<string, { status?: number; body: unknown }>) {
  return async (input: RequestInfo | URL, _init?: RequestInit): Promise<Response> => {
    const url = typeof input === 'string' ? input : input.toString();
    const key = Object.keys(routes).find((candidate) => url.startsWith(candidate));
    if (key === undefined) {
      return new Response(JSON.stringify({ code: 'not_found', detail: url }), { status: 404 });
    }
    const entry = routes[key]!;
    return new Response(JSON.stringify(entry.body), {
      status: entry.status ?? 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
}
