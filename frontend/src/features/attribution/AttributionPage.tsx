/**
 * "Who is trading what" (T-50, LLD §16.4, FR-11, AC-29, AC-30).
 *
 * One card per origin: AI (provider/model), auto-tuning, manual,
 * outside the system. A "why →" link on every row goes to the decision
 * log in one click.
 *
 * An `external` position is NEVER shown under an agent's name: with no
 * local record, it says so explicitly — "no local record", never
 * attached to the nearest order (LLD §11.1).
 */
import { Alert, Anchor, Badge, Card, Group, Loader, Stack, Table, Text, Title } from '@mantine/core';
import { IconArrowRight, IconAlertTriangle, IconUsersGroup } from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { Num } from '@/components/Num';
import { api, type Origin } from '@/lib/api';
import { formatLocalWithUtc, formatMoney, formatQuantity } from '@/lib/money';

export const ORIGIN_LABEL: Record<Origin, string> = {
  research_agent: 'AI research agent',
  auto_tuning: 'Auto-tuning',
  manual_operator: 'Manual (operator)',
  external: 'Outside the system',
};

export const ORIGIN_COLOR: Record<Origin, string> = {
  research_agent: 'violet',
  auto_tuning: 'teal',
  manual_operator: 'blue',
  external: 'gray',
};

export function OriginBadge({
  origin,
  detail,
  mixed = false,
}: {
  origin: Origin;
  detail?: string | null;
  mixed?: boolean;
}) {
  return (
    <Group gap={4}>
      <Badge color={ORIGIN_COLOR[origin]} variant="light" data-testid="origin-badge" data-origin={origin}>
        {ORIGIN_LABEL[origin]}
        {detail ? ` · ${detail}` : ''}
      </Badge>
      {mixed ? <MixedOriginBadge /> : null}
    </Group>
  );
}

/**
 * Multiple origins on one symbol (LLD §11.1). Such a symbol appears on
 * EVERY relevant card — never hidden on just one (LLD §16.4). `origin` is
 * from the latest fill, so without this badge it would read as "sole owner".
 */
export function MixedOriginBadge() {
  return (
    <Badge color="orange" variant="outline" data-testid="mixed-origin-badge">
      mixed origin
    </Badge>
  );
}

export function AttributionPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['attribution'],
    queryFn: api.attribution,
    refetchInterval: 10_000,
  });

  if (isLoading) return <Loader data-testid="attribution-loading" />;
  if (error) {
    return (
      <Alert color="red" icon={<IconAlertTriangle size={18} />}>
        {(error as Error).message}
      </Alert>
    );
  }

  const groups = data?.groups ?? [];

  return (
    <Stack gap="md">
      <Group gap="xs">
        <IconUsersGroup size={22} style={{ color: 'var(--mantine-color-brand-5)' }} />
        <Title order={3}>Who is trading what</Title>
      </Group>
      <Text size="sm" c="dimmed">
        Each group is built from REAL `orders` / `positions` rows. There is no
        separate computed cache, so every symbol shown here traces back to at least one row.
      </Text>

      {groups.length === 0 ? (
        <Alert color="gray" data-testid="attribution-empty">
          No open positions and no open orders.
        </Alert>
      ) : null}

      {groups.map((group) => (
        <Card
          key={`${group.origin}:${group.origin_detail ?? ''}`}
          withBorder
          padding="md"
          style={{ background: 'var(--mantine-color-dark-7)', borderColor: 'var(--mantine-color-dark-4)' }}
          data-testid="attribution-group"
          data-origin={group.origin}
        >
          <Group justify="space-between" mb="sm">
            <OriginBadge origin={group.origin} detail={group.origin_detail} />
            <Badge variant="outline" color="dark.2" size="sm">
              {group.symbols.length} symbols
            </Badge>
          </Group>

          <Table highlightOnHover data-testid="attribution-table">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Symbol</Table.Th>
                <Table.Th>Position</Table.Th>
                <Table.Th>Market value</Table.Th>
                <Table.Th>Open orders</Table.Th>
                <Table.Th>Last decision</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {group.symbols.map((row) => (
                <Table.Tr key={row.symbol} data-testid="attribution-row" data-symbol={row.symbol}>
                  <Table.Td fw={600}>
                    <Group gap={6}>
                      {row.symbol}
                      {row.origin_mixed ? <MixedOriginBadge /> : null}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    {row.has_open_position ? (
                      <Num>{`${formatQuantity(row.position_qty)} shares`}</Num>
                    ) : (
                      'no position'
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Num>{formatMoney(row.market_value)}</Num>
                  </Table.Td>
                  <Table.Td>
                    <Num>{row.open_order_count}</Num>
                  </Table.Td>
                  <Table.Td>
                    {group.origin === 'external' ? (
                      <Text size="xs" c="dimmed">
                        no local record
                      </Text>
                    ) : (
                      <Num>{formatLocalWithUtc(row.last_decision_at)}</Num>
                    )}
                  </Table.Td>
                  <Table.Td>
                    {row.last_decision_id ? (
                      <Anchor
                        component={Link}
                        to={`/decisions?symbol=${row.symbol}`}
                        size="xs"
                        data-testid="why-link"
                      >
                        <Group gap={4}>
                          why <IconArrowRight size={12} />
                        </Group>
                      </Anchor>
                    ) : null}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      ))}
    </Stack>
  );
}
