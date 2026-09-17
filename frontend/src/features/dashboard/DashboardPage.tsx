/**
 * Dashboard (T-30, LLD §16.6, AC-2, AC-29).
 *
 * Equity, позиц, нээлттэй order, өдрийн P&L. Мөр бүрд **origin багана**
 * (AC-29): «энэ позицийг хэн үүсгэсэн» гэдэг нь тусдаа дэлгэц рүү орох
 * шаардлагагүй.
 *
 * Equity curve нь `last_equity` → `equity` гэсэн ХОЁР бодит цэг. Дунд нь
 * цэг ЗОХИОХГҮЙ: түүхэн equity-ийн эх сурвалж v1-д байхгүй (хавсралт 10).
 */
import {
  Alert,
  Badge,
  Button,
  Card,
  Loader,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core';
import { IconAlertTriangle, IconX } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { api } from '@/lib/api';
import { formatMoney, formatQuantity, formatUtcTime, isNegative } from '@/lib/money';
import { OriginBadge } from '@/features/attribution/AttributionPage';

export function DashboardPage() {
  const queryClient = useQueryClient();
  const account = useQuery({ queryKey: ['account'], queryFn: api.account, refetchInterval: 10_000 });
  const positions = useQuery({ queryKey: ['positions'], queryFn: api.positions });
  const orders = useQuery({ queryKey: ['orders'], queryFn: () => api.orders('status=open') });

  const cancel = useMutation({
    mutationFn: (id: string) => api.cancelOrder(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['orders'] }),
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

  return (
    <Stack gap="md">
      <Title order={3}>Хяналтын самбар</Title>

      <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
        <Stat label="Эквити" value={formatMoney(acct?.equity)} testId="stat-equity" />
        <Stat label="Бэлэн мөнгө" value={formatMoney(acct?.cash)} testId="stat-cash" />
        <Stat
          label="Худалдан авах чадвар"
          value={formatMoney(acct?.buying_power)}
          testId="stat-buying-power"
        />
        <Stat
          label="Өдрийн P&L"
          value={formatMoney(dailyPnl)}
          color={dailyPnl && isNegative(dailyPnl) ? 'red.6' : 'green.7'}
          testId="stat-daily-pnl"
        />
      </SimpleGrid>

      {acct?.trading_blocked ? (
        <Alert color="red" icon={<IconAlertTriangle size={18} />} data-testid="trading-blocked">
          Alpaca тал дээр арилжаа ХААГДСАН (`trading_blocked`).
        </Alert>
      ) : null}

      <Card withBorder padding="md">
        <Text fw={600} mb="xs">
          Эквитийн хөдөлгөөн (өдрийн нээлт → одоо)
        </Text>
        <div style={{ height: 180 }} data-testid="equity-chart">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={equitySeries(acct?.last_equity, acct?.equity)}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" />
              <YAxis domain={['auto', 'auto']} />
              <ChartTooltip />
              <Line type="monotone" dataKey="value" stroke="#5c7cfa" strokeWidth={2} dot />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <Text size="xs" c="dimmed" mt={4}>
          Хоёр бодит цэг. Түүхэн equity-ийн эх сурвалж v1-д байхгүй тул дунд нь цэг
          зохиохгүй.
        </Text>
      </Card>

      <Card withBorder padding="md">
        <Text fw={600} mb="sm">
          Нээлттэй позиц
        </Text>
        <Table highlightOnHover data-testid="positions-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Symbol</Table.Th>
              <Table.Th>Ширхэг</Table.Th>
              <Table.Th>Дундаж орц</Table.Th>
              <Table.Th>Зах зээлийн үнэ</Table.Th>
              <Table.Th>Биелээгүй P&L</Table.Th>
              <Table.Th>Гарал (origin)</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(positions.data?.positions ?? []).map((p) => (
              <Table.Tr key={p.symbol} data-testid="position-row" data-symbol={p.symbol}>
                <Table.Td fw={600}>{p.symbol}</Table.Td>
                <Table.Td>{formatQuantity(p.qty)}</Table.Td>
                <Table.Td>{formatMoney(p.avg_entry_price)}</Table.Td>
                <Table.Td>{formatMoney(p.market_value)}</Table.Td>
                <Table.Td c={isNegative(p.unrealized_pl) ? 'red.6' : 'green.7'}>
                  {formatMoney(p.unrealized_pl)}
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
                    Нээлттэй позиц алга.
                  </Text>
                </Table.Td>
              </Table.Tr>
            ) : null}
          </Table.Tbody>
        </Table>
      </Card>

      <Card withBorder padding="md">
        <Text fw={600} mb="sm">
          Нээлттэй order
        </Text>
        <Table highlightOnHover data-testid="orders-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Symbol</Table.Th>
              <Table.Th>Тал</Table.Th>
              <Table.Th>Ширхэг</Table.Th>
              <Table.Th>Төрөл</Table.Th>
              <Table.Th>Статус</Table.Th>
              <Table.Th>Гарал (origin)</Table.Th>
              <Table.Th>Илгээсэн</Table.Th>
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
                  {formatQuantity(o.filled_qty)} / {formatQuantity(o.qty)}
                </Table.Td>
                <Table.Td>{o.order_type}</Table.Td>
                <Table.Td>{o.status}</Table.Td>
                <Table.Td>
                  <OriginBadge origin={o.origin} detail={o.origin_detail} />
                </Table.Td>
                <Table.Td>{formatUtcTime(o.submitted_at)}</Table.Td>
                <Table.Td>
                  <Button
                    size="compact-xs"
                    variant="subtle"
                    color="red"
                    leftSection={<IconX size={12} />}
                    data-testid="cancel-order"
                    onClick={() => cancel.mutate(o.id)}
                  >
                    Цуцлах
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
            {(orders.data?.orders ?? []).length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={8}>
                  <Text size="sm" c="dimmed">
                    Нээлттэй order алга.
                  </Text>
                </Table.Td>
              </Table.Tr>
            ) : null}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  );
}

function Stat({
  label,
  value,
  color,
  testId,
}: {
  label: string;
  value: string;
  color?: string;
  testId: string;
}) {
  return (
    <Card withBorder padding="md" data-testid={testId}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="xl" fw={700} c={color}>
        {value}
      </Text>
    </Card>
  );
}

/** Мөнгөн хасалт — тэмдэгт мөрөөр. `Number()` хэрэглэхгүй (AC-25). */
export function subtract(a: string | undefined, b: string | null | undefined): string | null {
  if (!a || !b) return null;
  const scale = Math.max(fractionDigits(a), fractionDigits(b));
  const diff = toScaled(a, scale) - toScaled(b, scale);
  const negative = diff < 0n;
  const digits = (negative ? -diff : diff).toString().padStart(scale + 1, '0');
  const whole = digits.slice(0, digits.length - scale);
  const fraction = digits.slice(digits.length - scale);
  return `${negative ? '-' : ''}${whole}${scale ? `.${fraction}` : ''}`;
}

function fractionDigits(text: string): number {
  const index = text.indexOf('.');
  return index === -1 ? 0 : text.length - index - 1;
}

function toScaled(text: string, scale: number): bigint {
  const [whole = '0', fraction = ''] = text.split('.');
  return BigInt(`${whole}${fraction.padEnd(scale, '0')}`);
}

/** Зөвхөн БОДИТ цэг. Дунд нь интерполяци БАЙХГҮЙ. */
export function equitySeries(lastEquity: string | null | undefined, equity: string | undefined) {
  const points: { label: string; value: string }[] = [];
  if (lastEquity) points.push({ label: 'нээлт', value: lastEquity });
  if (equity) points.push({ label: 'одоо', value: equity });
  return points;
}
