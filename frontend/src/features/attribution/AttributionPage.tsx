/**
 * «Хэн юунд арилжаа хийж байна» (T-50, LLD §16.4, FR-11, AC-29, AC-30).
 *
 * Origin тус бүр НЭГ карт: AI (provider/model), авто-тохируулга, гараар,
 * системээс гадуур. Мөр бүрээс «яагаад →» нь шийдвэрийн лог руу нэг
 * даралтаар хүргэнэ.
 *
 * `external` позицийг agent-ийн нэрээр ХЭЗЭЭ Ч харуулахгүй: локал бичлэг
 * байхгүй бол «локал бичлэггүй» гэж ил бичнэ, хамгийн ойрын order-т
 * наахгүй (LLD §11.1).
 */
import { Alert, Anchor, Badge, Card, Group, Loader, Stack, Table, Text, Title } from '@mantine/core';
import { IconArrowRight, IconAlertTriangle } from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { api, type Origin } from '@/lib/api';
import { formatMoney, formatQuantity, formatUtcTime } from '@/lib/money';

export const ORIGIN_LABEL: Record<Origin, string> = {
  research_agent: 'AI судалгааны agent',
  auto_tuning: 'Авто-тохируулга',
  manual_operator: 'Гараар (operator)',
  external: 'Системээс гадуур',
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
 * Нэг symbol дээр олон origin (LLD §11.1). Ийм symbol нь холбогдох БҮХ
 * картад гарна — аль нэгэнд нь далдлахгүй (LLD §16.4). `origin` нь
 * сүүлийн fill-ийнх тул энэ тэмдэггүйгээр «зөвхөн тэр эзэн» гэж уншигдана.
 */
export function MixedOriginBadge() {
  return (
    <Badge color="orange" variant="outline" data-testid="mixed-origin-badge">
      холимог origin
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
      <Title order={3}>Хэн юунд арилжаа хийж байна</Title>
      <Text size="sm" c="dimmed">
        Бүлэг бүр `orders` / `positions`-ийн БОДИТ мөрөөс угсарсан. Тусдаа тооцоолсон
        кэш байхгүй тул энд харагдах symbol бүр дор хаяж нэг мөрөнд буцаж холбогдоно.
      </Text>

      {groups.length === 0 ? (
        <Alert color="gray" data-testid="attribution-empty">
          Нээлттэй позиц ч, нээлттэй order ч алга.
        </Alert>
      ) : null}

      {groups.map((group) => (
        <Card
          key={`${group.origin}:${group.origin_detail ?? ''}`}
          withBorder
          padding="md"
          data-testid="attribution-group"
          data-origin={group.origin}
        >
          <Group justify="space-between" mb="sm">
            <OriginBadge origin={group.origin} detail={group.origin_detail} />
            <Text size="xs" c="dimmed">
              {group.symbols.length} symbol
            </Text>
          </Group>

          <Table highlightOnHover data-testid="attribution-table">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Symbol</Table.Th>
                <Table.Th>Позиц</Table.Th>
                <Table.Th>Зах зээлийн үнэ</Table.Th>
                <Table.Th>Нээлттэй order</Table.Th>
                <Table.Th>Сүүлийн шийдвэр</Table.Th>
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
                    {row.has_open_position ? `${formatQuantity(row.position_qty)} ш` : 'позицгүй'}
                  </Table.Td>
                  <Table.Td>{formatMoney(row.market_value)}</Table.Td>
                  <Table.Td>{row.open_order_count}</Table.Td>
                  <Table.Td>
                    {group.origin === 'external' ? (
                      <Text size="xs" c="dimmed">
                        локал бичлэггүй
                      </Text>
                    ) : (
                      formatUtcTime(row.last_decision_at)
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
                          яагаад <IconArrowRight size={12} />
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
