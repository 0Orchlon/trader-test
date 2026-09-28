/**
 * Dashboard (T-30, LLD §16.6, AC-2, AC-29).
 *
 * Equity, positions, open orders, daily P&L. Every row has an **origin
 * column** (AC-29): "who created this position" never needs a separate
 * screen.
 *
 * Equity curve (T-99, personal project, not in the LLD): REAL
 * once-a-minute samples from `GET /equity/history`
 * (`system/scheduler.py::snapshot_equity`). If samples haven't
 * accumulated yet (fresh deploy), falls back to the old two-point line
 * (`last_equity` → `equity`) — no interpolation/estimation ever happens
 * either way.
 */
import { useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core';
import { IconAlertTriangle, IconRefresh, IconX } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { api, type Position } from '@/lib/api';
import {
  exposureReading,
  formatLocalDateTimeWithUtc,
  formatLocalTime,
  formatLocalWithUtc,
  formatMoney,
  formatQuantity,
  subtract,
  sumMoney,
} from '@/lib/money';
import { OriginBadge } from '@/features/attribution/AttributionPage';
import { ResearchCycleTimer } from '@/features/dashboard/ResearchCycleTimer';
import { TradeChart } from '@/features/dashboard/TradeChart';
import { Num } from '@/components/Num';
import { Pnl } from '@/components/Pnl';

export function DashboardPage() {
  const queryClient = useQueryClient();
  const [openTrade, setOpenTrade] = useState<Position | null>(null);
  const account = useQuery({ queryKey: ['account'], queryFn: api.account, refetchInterval: 10_000 });
  const history = useQuery({
    queryKey: ['equity-history'],
    queryFn: () => api.equityHistory(240),
    refetchInterval: 15_000,
  });
  const positions = useQuery({
    queryKey: ['positions'],
    queryFn: api.positions,
    refetchInterval: 10_000,
  });
  const orders = useQuery({ queryKey: ['orders'], queryFn: () => api.orders('status=open') });
  const performance = useQuery({
    queryKey: ['performance'],
    queryFn: api.performance,
    refetchInterval: 30_000,
  });
  const capital = useQuery({
    queryKey: ['capital-summary'],
    queryFn: api.capitalSummary,
    refetchInterval: 15_000,
  });
  const limits = useQuery({ queryKey: ['capital-limits'], queryFn: api.capitalLimits });

  const cancel = useMutation({
    mutationFn: (id: string) => api.cancelOrder(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['orders'] }),
  });

  // WS trade-update stream can miss a fill (or drop it across a restart —
  // the daily reconcile_eod cron has no jobstore, so a restart at fire time
  // just skips that day). This copies Alpaca's own truth for every locally
  // "open" order right now, same logic reconcile_eod runs, without the wait.
  const reconcile = useMutation({
    mutationFn: api.reconcileNow,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['orders'] });
      void queryClient.invalidateQueries({ queryKey: ['positions'] });
    },
  });

  if (account.isLoading) return <Loader data-testid="dashboard-loading" />;
  if (account.error) {
    return (
      <Alert color="red" icon={<IconAlertTriangle size={18} />} data-testid="dashboard-error">
        {(account.error as Error).message}
      </Alert>
    );
  }

  const acct = account.data?.account;
  const dailyPnl = acct ? subtract(acct.equity, acct.last_equity) : null;
  // The tile shows the ALL-TIME closed total (`total`) — `net`/`per_symbol`
  // is the prompt's last-20-row window, so using it here would freeze at 20.
  const closedNet = performance.data?.total?.net ?? null;
  const closedTrades = performance.data?.total?.trades ?? 0;
  const totalExposure = sumMoney((positions.data?.positions ?? []).map((p) => p.market_value));
  const exposure = exposureReading(
    totalExposure,
    capital.data?.effective_equity,
    limits.data?.max_total_exposure_pct,
  );

  return (
    <Stack gap="md">
      <Title order={3}>Dashboard</Title>

      <ResearchCycleTimer />

      <SimpleGrid cols={{ base: 1, sm: 2, lg: 6 }} spacing="sm">
        <Stat label="Equity" testId="stat-equity">
          <Num size="1.5rem" fw={700}>
            {formatMoney(acct?.equity)}
          </Num>
        </Stat>
        <Stat label="Cash" testId="stat-cash">
          <Num size="1.5rem" fw={700}>
            {formatMoney(acct?.cash)}
          </Num>
        </Stat>
        <Stat label="Buying power" testId="stat-buying-power">
          <Num size="1.5rem" fw={700}>
            {formatMoney(acct?.buying_power)}
          </Num>
        </Stat>
        <Stat label="Daily P&L" testId="stat-daily-pnl">
          <Pnl value={dailyPnl} costBasis={acct?.last_equity} size="1.5rem" fw={700} />
        </Stat>
        <Stat label={`Closed trades (${closedTrades})`} testId="stat-closed-pnl">
          <Pnl value={closedNet} size="1.5rem" fw={700} />
        </Stat>
        <Stat label="Exposure" testId="stat-exposure">
          <Num
            size="1.5rem"
            fw={700}
            c={
              exposure === null
                ? undefined
                : exposure.ratioOfLimit >= 0.9
                  ? 'red.6'
                  : exposure.ratioOfLimit >= 0.75
                    ? 'orange.6'
                    : undefined
            }
          >
            {exposure?.pct ?? '—'}
          </Num>
          {limits.data ? (
            <Text size="xs" c="dimmed">
              of {limits.data.max_total_exposure_pct}% cap
            </Text>
          ) : null}
        </Stat>
      </SimpleGrid>

      {acct?.trading_blocked ? (
        <Alert color="red" icon={<IconAlertTriangle size={18} />} data-testid="trading-blocked">
          Trading is BLOCKED on Alpaca's side (`trading_blocked`).
        </Alert>
      ) : null}

      <Card withBorder padding="md">
        <Text fw={600} mb="xs">
          Equity over time (per minute)
        </Text>
        <div style={{ height: 220 }} data-testid="equity-chart">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={equityPoints(history.data?.points, acct?.last_equity, acct?.equity)}>
              <defs>
                <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--mantine-color-brand-5)" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="var(--mantine-color-brand-5)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--mantine-color-dark-5)" />
              <XAxis
                dataKey="label"
                minTickGap={30}
                stroke="var(--mantine-color-dark-4)"
                tick={{ fontFamily: 'var(--mantine-font-family-monospace)', fontSize: 11 }}
              />
              <YAxis
                domain={['auto', 'auto']}
                stroke="var(--mantine-color-dark-4)"
                tick={{ fontFamily: 'var(--mantine-font-family-monospace)', fontSize: 11 }}
              />
              <ChartTooltip
                labelFormatter={(_, payload) => formatLocalDateTimeWithUtc(payload?.[0]?.payload?.ts)}
                contentStyle={{
                  background: 'var(--mantine-color-dark-7)',
                  border: '1px solid var(--mantine-color-dark-5)',
                  fontFamily: 'var(--mantine-font-family-monospace)',
                  fontSize: 12,
                }}
                labelStyle={{ color: 'var(--mantine-color-dimmed)' }}
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke="var(--mantine-color-brand-5)"
                strokeWidth={2}
                fill="url(#equityFill)"
                dot={false}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <Text size="xs" c="dimmed" mt={4}>
          {history.data?.points.length
            ? `Last ${history.data.points.length} real samples (per minute, refreshes every 15s).`
            : "Samples haven't accumulated yet — showing today's open → now as two real points."}
        </Text>
      </Card>

      <Card withBorder padding="md">
        <Text fw={600} mb={4}>
          Open positions
        </Text>
        <Text size="xs" c="dimmed" mb="sm">
          Click a row to open its live candle chart, with entry line, P&L, and a manual close button.
        </Text>
        <Table highlightOnHover data-testid="positions-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Symbol</Table.Th>
              <Table.Th>Qty</Table.Th>
              <Table.Th>Avg entry</Table.Th>
              <Table.Th>Market value</Table.Th>
              <Table.Th>Unrealized P&L</Table.Th>
              <Table.Th>Origin</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(positions.data?.positions ?? []).map((p) => (
              <Table.Tr
                key={p.symbol}
                data-testid="position-row"
                data-symbol={p.symbol}
                onClick={() => setOpenTrade(p)}
                style={{ cursor: 'pointer' }}
              >
                <Table.Td fw={600}>{p.symbol}</Table.Td>
                <Table.Td>
                  <Num>{formatQuantity(p.qty)}</Num>
                </Table.Td>
                <Table.Td>
                  <Num>{formatMoney(p.avg_entry_price)}</Num>
                </Table.Td>
                <Table.Td>
                  <Num>{formatMoney(p.market_value)}</Num>
                </Table.Td>
                <Table.Td>
                  <Pnl value={p.unrealized_pl} costBasis={subtract(p.market_value, p.unrealized_pl)} />
                </Table.Td>
                <Table.Td>
                  <OriginBadge origin={p.origin} detail={p.origin_detail} mixed={p.origin_mixed} />
                </Table.Td>
              </Table.Tr>
            ))}
            {(positions.data?.positions ?? []).length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={6}>
                  <Text size="sm" c="dimmed">
                    No open positions.
                  </Text>
                </Table.Td>
              </Table.Tr>
            ) : null}
          </Table.Tbody>
        </Table>
      </Card>

      <Card withBorder padding="md">
        <Group justify="space-between" mb="sm">
          <Text fw={600}>Open orders</Text>
          <Group gap="xs">
            {reconcile.data ? (
              <Text size="xs" c="dimmed" data-testid="reconcile-result">
                {reconcile.data.drift_count === 0
                  ? 'No drift found'
                  : `Fixed ${reconcile.data.drift_count} drifted order(s)`}
              </Text>
            ) : null}
            <Button
              size="compact-xs"
              variant="light"
              leftSection={<IconRefresh size={12} />}
              loading={reconcile.isPending}
              data-testid="reconcile-now"
              onClick={() => reconcile.mutate()}
            >
              Reconcile now
            </Button>
          </Group>
        </Group>
        <Table highlightOnHover data-testid="orders-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Symbol</Table.Th>
              <Table.Th>Side</Table.Th>
              <Table.Th>Qty</Table.Th>
              <Table.Th>Type</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Origin</Table.Th>
              <Table.Th>Submitted</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(orders.data?.orders ?? []).map((o) => (
              <Table.Tr key={o.id} data-testid="order-row" data-symbol={o.symbol}>
                <Table.Td fw={600}>{o.symbol}</Table.Td>
                <Table.Td>
                  <Badge color={o.side === 'buy' ? 'green' : 'orange'} variant="light">
                    {o.side}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Num>
                    {formatQuantity(o.filled_qty)} / {formatQuantity(o.qty)}
                  </Num>
                </Table.Td>
                <Table.Td>{o.order_type}</Table.Td>
                <Table.Td>{o.status}</Table.Td>
                <Table.Td>
                  <OriginBadge origin={o.origin} detail={o.origin_detail} />
                </Table.Td>
                <Table.Td>
                  <Num>{formatLocalWithUtc(o.submitted_at)}</Num>
                </Table.Td>
                <Table.Td>
                  <Button
                    size="compact-xs"
                    variant="subtle"
                    color="red"
                    leftSection={<IconX size={12} />}
                    data-testid="cancel-order"
                    onClick={() => cancel.mutate(o.id)}
                  >
                    Cancel
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
            {(orders.data?.orders ?? []).length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={8}>
                  <Text size="sm" c="dimmed">
                    No open orders.
                  </Text>
                </Table.Td>
              </Table.Tr>
            ) : null}
          </Table.Tbody>
        </Table>
      </Card>

      <Modal
        opened={openTrade !== null}
        onClose={() => setOpenTrade(null)}
        title={openTrade ? `${openTrade.symbol} — live` : ''}
        size="xl"
        data-testid="trade-chart-modal"
      >
        {openTrade ? <TradeChart position={openTrade} onClose={() => setOpenTrade(null)} /> : null}
      </Modal>
    </Stack>
  );
}

function Stat({
  label,
  testId,
  children,
}: {
  label: string;
  testId: string;
  children: React.ReactNode;
}) {
  return (
    <Card withBorder padding="sm" data-testid={testId}>
      <Text size="xs" c="dimmed" tt="uppercase" style={{ letterSpacing: '0.03em' }}>
        {label}
      </Text>
      {children}
    </Card>
  );
}

/**
 * REAL points only — NO interpolation. Uses `snapshot_equity`'s
 * once-a-minute series when samples exist; otherwise falls back to the
 * old two-point line (open → now).
 */
export function equityPoints(
  history: { ts: string; equity: string }[] | undefined,
  lastEquity: string | null | undefined,
  equity: string | undefined,
) {
  if (history && history.length > 0) {
    return history.map((p) => ({ label: formatLocalTime(p.ts), value: p.equity, ts: p.ts }));
  }
  const points: { label: string; value: string; ts?: string }[] = [];
  if (lastEquity) points.push({ label: 'open', value: lastEquity });
  if (equity) points.push({ label: 'now', value: equity });
  return points;
}
