/**
 * Persistent mode indicator (T-29, LLD §16.2, AC-20).
 *
 * Pinned to the top of the screen, on EVERY route. "Am I looking at real
 * money right now" must NEVER be ambiguous.
 */
import { Group, Text } from '@mantine/core';
import { IconAlertTriangle, IconFlask, IconHistory } from '@tabler/icons-react';

import type { Source } from '@/lib/api';

type Style = { label: string; background: string; color: string; icon: React.ReactNode };

export const MODE_STYLES: Record<Source, Style> = {
  alpaca_paper: {
    label: 'PAPER — fake money',
    background: 'linear-gradient(90deg, var(--mantine-color-blue-8), var(--mantine-color-blue-6))',
    color: 'white',
    icon: <IconFlask size={18} />,
  },
  alpaca_live: {
    label: 'LIVE — REAL MONEY',
    background: 'linear-gradient(90deg, var(--mantine-color-red-9), var(--mantine-color-red-7))',
    color: 'white',
    icon: <IconAlertTriangle size={18} />,
  },
  backtest: {
    label: 'BACKTEST — historical data',
    background: 'linear-gradient(90deg, var(--mantine-color-gray-8), var(--mantine-color-gray-6))',
    color: 'white',
    icon: <IconHistory size={18} />,
  },
};

export function ModeBanner({ source }: { source: Source | undefined }) {
  // An UNKNOWN mode does NOT mean `paper`. State the ambiguity plainly.
  if (!source) {
    return (
      <Group
        component="header"
        role="banner"
        data-testid="mode-banner"
        data-source="unknown"
        justify="center"
        gap="xs"
        py={6}
        style={{ background: 'var(--mantine-color-dark-4)', color: 'white' }}
      >
        <IconAlertTriangle size={18} />
        <Text fw={700} size="sm" style={{ letterSpacing: '0.02em' }}>
          MODE UNKNOWN — connecting to backend
        </Text>
      </Group>
    );
  }

  const style = MODE_STYLES[source];
  return (
    <Group
      component="header"
      role="banner"
      data-testid="mode-banner"
      data-source={source}
      justify="center"
      gap="xs"
      py={6}
      style={{ background: style.background, color: style.color }}
    >
      {style.icon}
      <Text fw={700} size="sm" style={{ letterSpacing: '0.02em' }}>
        {style.label}
      </Text>
    </Group>
  );
}
