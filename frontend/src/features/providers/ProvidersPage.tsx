/**
 * Provider Switcher (T-33, LLD §16.6, FR-8, AC-10).
 *
 * Shows each role's active provider, health, and read/write permission.
 * Switching has **NO restart** — it's a single reference reassignment on
 * the backend. An in-flight tool call finishes on the OLD provider and
 * is recorded under the OLD one (AC-11).
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
import { IconAlertTriangle, IconPlugConnected, IconRefresh } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { Num } from '@/components/Num';

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
          `${result.in_flight_calls} in-flight calls will finish on the OLD provider.`,
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
      <Group gap="xs">
        <IconPlugConnected size={20} color="var(--mantine-color-brand-5)" />
        <Title order={3}>AI provider</Title>
      </Group>

      {noWritableHealthy ? (
        <Alert color="orange" icon={<IconAlertTriangle size={18} />} data-testid="no-writable">
          No healthy provider capable of proposing trades. No new proposals will be
          made — existing positions and orders are unaffected. Risk, the kill switch,
          and the circuit breaker keep working normally.
        </Alert>
      ) : null}

      <Card withBorder padding="md">
        <Group align="flex-end" gap="sm">
          <Select
            label="Provider for the research role"
            data={providers.map((p) => ({
              value: p.id,
              label: `${p.id} · ${p.model}${p.read_only ? ' (read-only)' : ''}`,
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
            Switch
          </Button>
        </Group>
        <Text size="xs" c="dimmed" mt="xs">
          Switching does not restart the system. A provider never changes mid-conversation
          — a switch takes effect on the NEXT session.
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
              <Table.Th>Model</Table.Th>
              <Table.Th>Transport</Table.Th>
              <Table.Th>Healthy</Table.Th>
              <Table.Th>Permission</Table.Th>
              <Table.Th>Last error</Table.Th>
              <Table.Th>Active</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {providers.map((p) => (
              <Table.Tr key={p.id} data-testid="provider-row" data-id={p.id}>
                <Table.Td>
                  <Num fw={600}>{p.id}</Num>
                </Table.Td>
                <Table.Td>{p.vendor}</Table.Td>
                <Table.Td>{p.model}</Table.Td>
                <Table.Td>{p.transport}</Table.Td>
                <Table.Td>
                  <Badge color={p.healthy ? 'green' : 'red'} variant="light">
                    {p.healthy ? 'healthy' : 'down'}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Badge color={p.read_only ? 'gray' : 'blue'} variant="light">
                    {p.read_only ? 'read-only' : 'can propose'}
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
