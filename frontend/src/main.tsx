/** Орох цэг. Router, Mantine, TanStack Query — нэг газар (LLD §16.1). */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { MantineProvider, createTheme } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createBrowserRouter } from 'react-router-dom';

import '@mantine/core/styles.css';

import { routes } from './app/routes';

const theme = createTheme({ primaryColor: 'indigo' });

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Дахин оролдлого нь алдааг ДАЛДЛАХГҮЙ: хоёр удаа л, дараа нь ил.
      retry: 1,
      refetchOnWindowFocus: true,
      staleTime: 2_000,
    },
  },
});

const router = createBrowserRouter(routes);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="auto">
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </MantineProvider>
  </StrictMode>,
);
