/**
 * Auto-Tuning Panel (T-34, LLD §16.6, AC-22…AC-24).
 *
 * Параметр, муж, одоогийн утга, түүх, walk-forward үр дүн. `promote` нь
 * хоёр шаттай баталгаажуулалттай.
 *
 * **Муж засах талбар ЭНД БАЙХГҮЙ** (AC-24): муж бол бодлого, түүнийг
 * UI-аас засах нь SPEC_APPROVE-ийн хаалгыг тойрно. Муж өөрчлөх = deploy.
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
import { formatUtc } from '@/lib/money';

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
        <Title order={3}>Авто-тохируулга</Title>
        <Button
          leftSection={<IconArrowUp size={16} />}
          disabled={selected.length === 0 || promote.isPending}
          data-testid="tuning-promote"
          onClick={() => promote.mutate(undefined)}
        >
          LIVE рүү дэвшүүлэх ({selected.length})
        </Button>
      </Group>

      <Alert color="blue" data-testid="tuning-policy">
        Муж нь config-оос ирнэ — энэ дэлгэцээс ЗАСАХ боломжгүй. Муж өөрчлөх нь deploy
        болон code review-ээр л явна. Автомат өөрчлөлт бүр `paper` дээр; `live` болох
        цорын ганц зам нь энэ дэлгэцийн дэвшүүлэх товч + баталгаажуулалт.
      </Alert>

      {parameters.map((p) => (
        <Card key={p.name} withBorder padding="md" data-testid="tuning-parameter" data-name={p.name}>
          <Group justify="space-between" mb="sm">
            <Group gap="sm">
              <Text fw={700}>{p.name}</Text>
              <Badge variant="light" data-testid="tuning-current">
                одоо: {p.current_value}
              </Badge>
              <Badge color={p.applies_to === 'live' ? 'red' : 'blue'} data-testid="tuning-applies">
                {p.applies_to}
              </Badge>
            </Group>
            <Text size="xs" c="dimmed" data-testid="tuning-bounds">
              муж [{p.bounds.min} … {p.bounds.max}] алхам {p.bounds.step}
            </Text>
          </Group>

          {(p.history ?? []).length === 0 ? (
            <Text size="sm" c="dimmed">
              Өөрчлөлтийн түүх алга — утга нь config-ийн анхдагч.
            </Text>
          ) : (
            <Table data-testid="tuning-history">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th />
                  <Table.Th>Хуучин → шинэ</Table.Th>
                  <Table.Th>Батласан</Table.Th>
                  <Table.Th>Walk-forward</Table.Th>
                  <Table.Th>Цаг</Table.Th>
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
                      {h.old_value} → <b>{h.new_value}</b>
                    </Table.Td>
                    <Table.Td>
                      <Badge color={h.approved_by === 'operator' ? 'green' : 'gray'} variant="light">
                        {h.approved_by}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs">
                        {h.walk_forward.folds} fold · in {h.walk_forward.in_sample_metric} · out{' '}
                        {h.walk_forward.out_of_sample_metric}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs">{formatUtc(h.changed_at)}</Text>
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
        title="LIVE рүү дэвшүүлэх"
        data-testid="tuning-confirm-modal"
      >
        <Stack gap="md">
          <Text data-testid="tuning-confirm-prompt">{confirmation?.prompt}</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmation(null)}>
              Болих
            </Button>
            <Button
              color="red"
              data-testid="tuning-confirm-accept"
              onClick={() => confirmation && promote.mutate(confirmation.token)}
            >
              Дэвшүүлэх
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal opened={error !== null} onClose={() => setError(null)} title="Алдаа">
        <Alert color="red" icon={<IconAlertTriangle size={18} />} data-testid="tuning-error">
          {error}
        </Alert>
      </Modal>
    </Stack>
  );
}
