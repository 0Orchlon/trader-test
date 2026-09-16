/**
 * Горимын байнгын заалт (T-29, LLD §16.2, AC-20).
 *
 * Дэлгэцийн дээд ирмэгт наалдсан, БҮХ route дээр. «Би одоо бодит мөнгө
 * харж байна уу» гэдэг асуулт ХЭЗЭЭ Ч тодорхойгүй байхгүй.
 */
import { Group, Text } from '@mantine/core';
import { IconAlertTriangle, IconFlask, IconHistory } from '@tabler/icons-react';

import type { Source } from '@/lib/api';

type Style = { label: string; background: string; color: string; icon: React.ReactNode };

export const MODE_STYLES: Record<Source, Style> = {
  alpaca_paper: {
    label: 'PAPER — хуурамч мөнгө',
    background: 'var(--mantine-color-blue-7)',
    color: 'white',
    icon: <IconFlask size={18} />,
  },
  alpaca_live: {
    label: 'LIVE — БОДИТ МӨНГӨ',
    background: 'var(--mantine-color-red-8)',
    color: 'white',
    icon: <IconAlertTriangle size={18} />,
  },
  backtest: {
    label: 'BACKTEST — түүхэн өгөгдөл',
    background: 'var(--mantine-color-gray-7)',
    color: 'white',
    icon: <IconHistory size={18} />,
  },
};

export function ModeBanner({ source }: { source: Source | undefined }) {
  // Горим МЭДЭГДЭХГҮЙ байх нь `paper` гэсэн үг БИШ. Тодорхойгүйг ил хэлнэ.
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
        <Text fw={700} size="sm">
          ГОРИМ ТОДОРХОЙГҮЙ — backend-тэй холбогдож байна
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
      <Text fw={700} size="sm">
        {style.label}
      </Text>
    </Group>
  );
}
