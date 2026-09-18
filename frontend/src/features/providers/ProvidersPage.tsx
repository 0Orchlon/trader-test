/**
 * Provider Switcher (T-33, LLD §16.6, FR-8, AC-10).
 *
 * Role тус бүрийн идэвхтэй provider, эрүүл мэнд, унших/бичих эрх.
 * Солих нь **restart БАЙХГҮЙ** — backend талд лавлагааг дахин оноох ганц
 * заалт. Нислэг дунд байгаа tool call хуучин provider-ээр дуусаж,
 * ХУУЧНААР нь бүртгэгдэнэ (AC-11).
 */
import { useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Select,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core';
import { IconAlertTriangle, IconRefresh } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

export function ProvidersPage() {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const { data, isLoading } = useQuery({ queryKey: ['providers'], queryFn: api.providers });

  const swap = useMutation({
    mutationFn: (providerId: string) => api.switchProvider('research', providerId),
    onSuccess: (result) => {
      setError(null);
      setNote(
        `${result.previous_provider_id} → ${result.new_provider_id}. ` +
          `Нислэг дунд байсан ${result.in_flight_calls} дуудалт ХУУЧНААР дуусна.`,
      );
      void queryClient.invalidateQueries({ queryKey: ['providers'] });
    },
    onError: (err: Error) => {
      setNote(null);
      setError(err.message);
    },
  });

  if (isLoading) return <Loader data-testid="providers-loading" />;

  const providers = data?.providers ?? [];
  const active = data?.active ?? {};
  const writable = providers.filter((p) => !p.read_only);
  const noWritableHealthy = writable.every((p) => !p.healthy);

  return (
    <Stack gap="md">
      <Title order={3}>AI provider</Title>

      {noWritableHealthy ? (
        <Alert color="orange" icon={<IconAlertTriangle size={18} />} data-testid="no-writable">
          Санал гаргах чадвартай эрүүл provider БАЙХГҮЙ. Шинэ санал гарахгүй — байгаа
          позиц, order хөндөгдөхгүй. Risk, зогсоолт, circuit breaker хэвийн ажиллана.
        </Alert>
      ) : null}

      <Card withBorder padding="md">
        <Group align="flex-end" gap="sm">
          <Select
            label="research role-ийн provider"
            data={providers.map((p) => ({
              value: p.id,
              label: `${p.id} · ${p.model}${p.read_only ? ' (зөвхөн унших)' : ''}`,
              disabled: !p.healthy,
            }))}
            value={selected ?? active['research'] ?? null}
            data-testid="provider-select"
            onChange={setSelected}
          />
          <Button
            leftSection={<IconRefresh size={16} />}
            loading={swap.isPending}
            disabled={!selected || selected === active['research']}
            data-testid="provider-switch"
            onClick={() => selected && swap.mutate(selected)}
          >
            Солих
          </Button>
        </Group>
        <Text size="xs" c="dimmed" mt="xs">
          Солилт нь систем дахин ачаалахгүй. Нэг харилцан яриа дунд provider солигдохгүй —
          солилт нь ДАРААГИЙН session-д хүчинтэй.
        </Text>
      </Card>

      {note ? (
        <Alert color="green" data-testid="provider-note">
          {note}
        </Alert>
      ) : null}
      {error ? (
        <Alert color="red" icon={<IconAlertTriangle size={18} />} data-testid="provider-error">
          {error}
        </Alert>
      ) : null}

      <Card withBorder padding="md">
        <Table data-testid="providers-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>ID</Table.Th>
              <Table.Th>Vendor</Table.Th>
              <Table.Th>Модель</Table.Th>
              <Table.Th>Транспорт</Table.Th>
              <Table.Th>Эрүүл</Table.Th>
              <Table.Th>Эрх</Table.Th>
              <Table.Th>Сүүлийн алдаа</Table.Th>
              <Table.Th>Идэвхтэй</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {providers.map((p) => (
              <Table.Tr key={p.id} data-testid="provider-row" data-id={p.id}>
                <Table.Td fw={600}>{p.id}</Table.Td>
                <Table.Td>{p.vendor}</Table.Td>
                <Table.Td>{p.model}</Table.Td>
                <Table.Td>{p.transport}</Table.Td>
                <Table.Td>
                  <Badge color={p.healthy ? 'green' : 'red'} variant="light">
                    {p.healthy ? 'эрүүл' : 'унасан'}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Badge color={p.read_only ? 'gray' : 'blue'} variant="light">
                    {p.read_only ? 'зөвхөн унших' : 'санал гаргана'}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Text size="xs" c="dimmed">
                    {p.last_error ?? '—'}
                  </Text>
                </Table.Td>
                <Table.Td>
                  {Object.entries(active)
                    .filter(([, id]) => id === p.id)
                    .map(([role]) => (
                      <Badge key={role} color="violet" data-testid="active-role">
                        {role}
                      </Badge>
                    ))}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  );
}
