/**
 * Live trade chart + manual close (T-99, personal project, not in the LLD).
 *
 * REAL candles from `GET /market/bars/{symbol}` (`lightweight-charts`,
 * TradingView's open-source library). An entry-price line and P&L are
 * both visible. The "Close" button goes through our EXACT normal order
 * path (`POST /orders/manual`) — no separate, unchecked close path exists
 * (same principle as R-1: a manual close routes through the Risk Agent
 * exactly like any other manual order).
 */
import { useState } from 'react';
import { Alert, Badge, Button, Group, Stack, Text } from '@mantine/core';
import { IconAlertTriangle, IconX } from '@tabler/icons-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api, ApiError, type Position } from '@/lib/api';
import { formatMoney, subtract } from '@/lib/money';
import { Pnl } from '@/components/Pnl';
import { PriceChart } from '@/components/PriceChart';

export function TradeChart({ position, onClose }: { position: Position; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const close = useMutation({
    mutationFn: () =>
      api.manualOrder(
        {
          symbol: position.symbol,
          side: position.side === 'long' ? 'sell' : 'buy',
          qty: position.qty.replace('-', ''),
          order_type: 'market',
          time_in_force: 'day',
        },
        crypto.randomUUID(),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['positions'] });
      onClose();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Unknown error'),
  });

  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Group gap="xs">
          <Text fw={700} size="lg">
            {position.symbol}
          </Text>
          <Badge color={position.side === 'long' ? 'green' : 'orange'} variant="light">
            {position.side}
          </Badge>
          <Text size="sm" c="dimmed">
            {position.qty} shares · entry {formatMoney(position.avg_entry_price)}
          </Text>
        </Group>
        <Pnl
          value={position.unrealized_pl}
          costBasis={subtract(position.market_value, position.unrealized_pl)}
          fw={700}
          size="lg"
          data-testid="trade-chart-pnl"
        />

      </Group>

      <PriceChart symbol={position.symbol} entryPrice={position.avg_entry_price} />

      {error ? (
        <Alert color="red" icon={<IconAlertTriangle size={16} />}>
          {error}
        </Alert>
      ) : null}

      <Group justify="flex-end">
        <Button
          color="red"
          variant="light"
          leftSection={<IconX size={16} />}
          loading={close.isPending}
          data-testid="close-position"
          onClick={() => close.mutate()}
        >
          Close position ({position.side === 'long' ? 'sell' : 'buy'} {position.qty})
        </Button>
      </Group>
    </Stack>
  );
}
