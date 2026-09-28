/** Entry point. Router, Mantine, TanStack Query — all wired up here (LLD §16.1). */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { MantineProvider, createTheme, type MantineColorsTuple } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createBrowserRouter } from 'react-router-dom';

import '@mantine/core/styles.css';

import { routes } from './app/routes';

// Accent — a single vivid trading-platform blue. Index 5/6 sit at primaryShade.
const brand: MantineColorsTuple = [
  '#EAF1FF', '#D2E1FF', '#A6C4FF', '#78A5FF', '#5389FE',
  '#3D77FE', '#2F68F5', '#2258DE', '#1749C4', '#0C3AA6',
];

// Gains — more saturated than Mantine's stock green, reads clearly on near-black.
const gain: MantineColorsTuple = [
  '#E6FBF1', '#C3F5DF', '#8FEAC1', '#57DBA1', '#2CC885',
  '#12B76A', '#0E9F5C', '#0B8750', '#086F42', '#065935',
];

// Losses — matching saturation/weight to `gain` so a red/green pair never
// looks lopsided (one loud, one washed out) in the same row.
const loss: MantineColorsTuple = [
  '#FEECEB', '#FDD2CF', '#FBA7A0', '#F87A6E', '#F55245',
  '#F04438', '#D63A2F', '#B22F26', '#8E251E', '#6E1D18',
];

// Dark surfaces — navy-tinted near-black, NOT neutral grey. This is what
// actually separates "trading terminal" from "generic admin template":
// 9 = page background, 7/8 = header/nav surfaces, 6 = card surface,
// 4/5 = borders/hover, 0-2 = text on dark.
const dark: MantineColorsTuple = [
  '#C7CBDD', '#A9AFC7', '#8D93AC', '#5F6580', '#3A3F58',
  '#282C40', '#1E2132', '#161825', '#101120', '#0A0B14',
];

export const theme = createTheme({
  primaryColor: 'brand',
  primaryShade: { light: 6, dark: 5 },
  colors: { brand, green: gain, red: loss, dark },

  // System font stack, not a Google Fonts import — no new network
  // dependency, no FOUC, works if the terminal is ever run offline.
  fontFamily:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, "Helvetica Neue", Arial, sans-serif',
  fontFamilyMonospace:
    'ui-monospace, "SF Mono", SFMono-Regular, "JetBrains Mono", Consolas, "Liberation Mono", Menlo, monospace',
  headings: { fontFamily: undefined, fontWeight: '700' }, // inherits body font

  defaultRadius: 'md',
  radius: { xs: '4px', sm: '6px', md: '8px', lg: '12px', xl: '20px' },

  // Elevation on a dark UI comes from border + surface-tone contrast
  // (every card already uses `withBorder`), not drop shadows — a light
  // shadow on a near-black background just looks like a rendering bug.
  // Leave `shadows` at Mantine defaults; do not add custom box-shadows.

  components: {
    Table: {
      styles: {
        th: {
          // CMC/Polymarket-style table headers: quiet, small, wide-tracked.
          fontSize: 'var(--mantine-font-size-xs)',
          fontWeight: 600,
          letterSpacing: '0.03em',
          textTransform: 'uppercase',
          color: 'var(--mantine-color-dimmed)',
        },
      },
    },
  },
});

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Retry does NOT hide errors: only twice, then it surfaces.
      retry: 1,
      refetchOnWindowFocus: true,
      staleTime: 2_000,
    },
  },
});

const router = createBrowserRouter(routes);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="dark">
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </MantineProvider>
  </StrictMode>,
);
