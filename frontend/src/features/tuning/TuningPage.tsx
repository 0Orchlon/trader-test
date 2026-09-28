/**
 * Auto-Tuning Panel (T-34, LLD §16.6, AC-22…AC-24).
 *
 * Parameter, bounds, current value, history, walk-forward results.
 * `promote` requires two-step confirmation.
 *
 * **No bounds-editing field exists here** (AC-24): bounds are policy —
 * editing them from the UI would go around SPEC_APPROVE's gate. Changing
 * bounds means a deploy.
 */
import { useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Group,
  Loader,
  Modal,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core';
import { IconAlertTriangle, IconArrowUp } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError, api } from '@/lib/api';
import { formatLocalDateTimeWithUtc } from '@/lib/money';
import { Num } from '@/components/Num';

export function TuningPage() {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string[]>([]);
  const [confirmation, setConfirmation] = useState<{ token: string; prompt: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({ queryKey: ['tuning'], queryFn: api.tuning });

  const promote = useMutation({
    mutationFn: (token?: string) => api.promoteTuning(selected, token),
    onSuccess: () => {
      setConfirmation(null);
      setSelected([]);
      void queryClient.invalidateQueries({ queryKey: ['tuning'] });
    },
    onError: (err: Error) => {
      if (err instanceof ApiError && err.code === 'confirmation_required' && err.confirmation) {
        setConfirmation({ token: err.confirmation.token, prompt: err.confirmation.prompt });
        return;
      }
      setError(err.message);
    },
  });

  if (isLoading) return <Loader data-testid="tuning-loading" />;
  const parameters = data?.parameters ?? [];

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={3}>Auto-tuning</Title>
        <Button
          leftSection={<IconArrowUp size={16} />}
          disabled={selected.length === 0 || promote.isPending}
          data-testid="tuning-promote"
          onClick={() => promote.mutate(undefined)}
        >
          Promote to LIVE ({selected.length})
        </Button>
      </Group>

      <Alert color="blue" data-testid="tuning-policy">
        Bounds come from config — they cannot be EDITED from this screen. Changing
        bounds only happens through a deploy and code review. Every automatic
        change is on `paper`; the ONLY path to `live` is this screen's promote
        button plus confirmation.
      </Alert>

      {parameters.map((p) => (
        <Card key={p.name} withBorder padding="md" data-testid="tuning-parameter" data-name={p.name}>
          <Group justify="space-between" mb="sm">
            <Group gap="sm">
              <Text fw={700}>{p.name}</Text>
              <Badge variant="light" data-testid="tuning-current">
                current: <Num span>{p.current_value}</Num>
              </Badge>
              <Badge color={p.applies_to === 'live' ? 'red' : 'blue'} data-testid="tuning-applies">
                <Num span>{p.applies_to}</Num>
              </Badge>
            </Group>
            <Num size="xs" c="dimmed" data-testid="tuning-bounds">
              bounds [{p.bounds.min} … {p.bounds.max}] step {p.bounds.step}
            </Num>
          </Group>

          {(p.history ?? []).length === 0 ? (
            <Text size="sm" c="dimmed">
              No change history — value is config's default.
            </Text>
          ) : (
            <Table data-testid="tuning-history">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th />
                  <Table.Th>Old → new</Table.Th>
                  <Table.Th>Approved by</Table.Th>
                  <Table.Th>Walk-forward</Table.Th>
                  <Table.Th>Time</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {(p.history ?? []).map((h) => (
                  <Table.Tr key={h.id} data-testid="tuning-history-row">
                    <Table.Td>
                      <Checkbox
                        checked={selected.includes(h.id)}
                        disabled={h.approved_by === 'operator'}
                        data-testid="tuning-select"
                        onChange={(e) =>
                          setSelected((prev) =>
                            e.currentTarget.checked
                              ? [...prev, h.id]
                              : prev.filter((id) => id !== h.id),
                          )
                        }
                      />
                    </Table.Td>
                    <Table.Td>
                      <Num span>{h.old_value}</Num> → <Num span fw={700}>{h.new_value}</Num>
                    </Table.Td>
                    <Table.Td>
                      <Badge color={h.approved_by === 'operator' ? 'green' : 'gray'} variant="light">
                        {h.approved_by}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Num size="xs">
                        {h.walk_forward.folds} fold · in {h.walk_forward.in_sample_metric} · out{' '}
                        {h.walk_forward.out_of_sample_metric}
                      </Num>
                    </Table.Td>
                    <Table.Td>
                      <Num size="xs">{formatLocalDateTimeWithUtc(h.changed_at)}</Num>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Card>
      ))}

      <Modal
        opened={confirmation !== null}
        onClose={() => setConfirmation(null)}
        title="Promote to LIVE"
        data-testid="tuning-confirm-modal"
      >
        <Stack gap="md">
          <Text data-testid="tuning-confirm-prompt">{confirmation?.prompt}</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmation(null)}>
              Cancel
            </Button>
            <Button
              color="red"
              data-testid="tuning-confirm-accept"
              onClick={() => confirmation && promote.mutate(confirmation.token)}
            >
              Promote
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal opened={error !== null} onClose={() => setError(null)} title="Error">
        <Alert color="red" icon={<IconAlertTriangle size={18} />} data-testid="tuning-error">
          {error}
        </Alert>
      </Modal>
    </Stack>
  );
}
