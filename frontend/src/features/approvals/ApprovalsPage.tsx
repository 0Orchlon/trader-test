/**
 * Approval Queue UI (T-31, LLD §16.6, AC-5, AC-6).
 *
 * Санал бүрд: agent-ийн үндэслэл, ЦИТАТ өгөгдлийн холбоос, Risk-ийн
 * шалгалтууд, TTL тоолуур. «Зөвшөөр» товч нь үндэслэлийг харахаас ӨМНӨ
 * дарагдахаар байрлуулагдаагүй — үндэслэл нь картын ДОТОР, товчны дээр.
 *
 * `expected_version` нь мөр бүрийн `version`-оос — reaper-тэй уралдвал
 * backend 409 буцаана, UI дахин татна.
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
  SegmentedControl,
  Stack,
  Text,
  Textarea,
  Title,
} from '@mantine/core';
import { IconAlertTriangle, IconCheck, IconExternalLink, IconX } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { api, type Approval } from '@/lib/api';
import { formatMoney, formatQuantity, formatUtc } from '@/lib/money';
import { RiskPreview } from '@/features/manualTicket/ManualTicketPage';

const STATES = ['pending', 'approved', 'rejected', 'expired', 'all'] as const;

export function ApprovalsPage() {
  const queryClient = useQueryClient();
  const [state, setState] = useState<string>('pending');
  const [rejecting, setRejecting] = useState<Approval | null>(null);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['approvals', state],
    queryFn: () => api.approvals(state),
    refetchInterval: 10_000,
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['approvals'] });
    void queryClient.invalidateQueries({ queryKey: ['orders'] });
  };

  const approve = useMutation({
    mutationFn: (row: Approval) => api.approve(row.id, row.version),
    onSuccess: refresh,
    onError: (err: Error) => {
      setError(err.message);
      refresh();
    },
  });

  const reject = useMutation({
    mutationFn: (row: Approval) => api.reject(row.id, row.version, reason),
    onSuccess: () => {
      setRejecting(null);
      setReason('');
      refresh();
    },
    onError: (err: Error) => setError(err.message),
  });

  if (isLoading) return <Loader data-testid="approvals-loading" />;
  const rows = data?.approvals ?? [];

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={3}>Зөвшөөрлийн дараалал</Title>
        <SegmentedControl
          data={STATES.map((s) => ({ value: s, label: s }))}
          value={state}
          onChange={setState}
          data-testid="approvals-filter"
        />
      </Group>

      {rows.length === 0 ? (
        <Alert color="gray" data-testid="approvals-empty">
          Хүлээгдэж буй санал алга. Alpaca руу ямар ч дуудалт хийгдээгүй.
        </Alert>
      ) : null}

      {rows.map((row) => (
        <Card key={row.id} withBorder padding="md" data-testid="approval-card" data-id={row.id}>
          <Group justify="space-between" mb="sm">
            <Group gap="sm">
              <Text fw={700} size="lg">
                {row.proposed_order.symbol}
              </Text>
              <Badge color={row.proposed_order.side === 'buy' ? 'green' : 'orange'}>
                {row.proposed_order.side}
              </Badge>
              <Text>{formatQuantity(row.proposed_order.qty)} ш</Text>
              <Text c="dimmed">{row.proposed_order.order_type}</Text>
              {row.proposed_order.limit_price ? (
                <Text c="dimmed">@ {formatMoney(row.proposed_order.limit_price)}</Text>
              ) : null}
            </Group>
            <Group gap="sm">
              <Badge variant="light" data-testid="approval-state">
                {row.state}
              </Badge>
              <Text size="xs" c="dimmed" data-testid="approval-ttl">
                хугацаа: {formatUtc(row.expires_at)}
              </Text>
            </Group>
          </Group>

          <Text size="sm" c="dimmed" mb={4}>
            {row.proposed_order.provider} / {row.proposed_order.model} ·{' '}
            {formatMoney(row.proposed_order.estimated_notional)}
          </Text>

          <Card withBorder padding="sm" mb="sm" bg="var(--mantine-color-default-hover)">
            <Text size="sm" fw={600} mb={4}>
              Agent-ийн үндэслэл
            </Text>
            <Text size="sm" data-testid="approval-rationale">
              {row.proposed_order.rationale}
            </Text>
            <Group gap="xs" mt="xs">
              <Text size="xs" c="dimmed">
                Цитат өгөгдөл ({row.proposed_order.grounded_in.length} tool call):
              </Text>
              {row.decision_id ? (
                <Button
                  component={Link}
                  to={`/decisions/${row.decision_id}`}
                  size="compact-xs"
                  variant="subtle"
                  leftSection={<IconExternalLink size={12} />}
                  data-testid="approval-evidence-link"
                >
                  түүхий payload харах
                </Button>
              ) : null}
            </Group>
          </Card>

          <RiskPreview risk={row.risk} />

          {row.state === 'pending' ? (
            <Group justify="flex-end" mt="sm">
              <Button
                color="red"
                variant="outline"
                leftSection={<IconX size={16} />}
                data-testid="approval-reject"
                onClick={() => setRejecting(row)}
              >
                Татгалзах
              </Button>
              <Button
                color="green"
                leftSection={<IconCheck size={16} />}
                loading={approve.isPending}
                data-testid="approval-approve"
                onClick={() => approve.mutate(row)}
              >
                Зөвшөөрөх
              </Button>
            </Group>
          ) : (
            <Text size="sm" c="dimmed" mt="sm" data-testid="approval-resolution">
              {row.state} · {formatUtc(row.resolved_at)}
              {row.resolution_reason ? ` — ${row.resolution_reason}` : ''}
            </Text>
          )}
        </Card>
      ))}

      <Modal
        opened={rejecting !== null}
        onClose={() => setRejecting(null)}
        title="Татгалзах"
        data-testid="reject-modal"
      >
        <Stack gap="md">
          <Text size="sm">
            Татгалзсан санал ХЭЗЭЭ Ч илгээгдэхгүй. Энэ үйлдэл буцаах боломжгүй.
          </Text>
          <Textarea
            label="Шалтгаан"
            required
            value={reason}
            data-testid="reject-reason"
            onChange={(e) => setReason(e.currentTarget.value)}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setRejecting(null)}>
              Болих
            </Button>
            <Button
              color="red"
              disabled={reason.trim() === ''}
              data-testid="reject-confirm"
              onClick={() => rejecting && reject.mutate(rejecting)}
            >
              Татгалзах
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal opened={error !== null} onClose={() => setError(null)} title="Алдаа">
        <Alert color="red" icon={<IconAlertTriangle size={18} />} data-testid="approvals-error">
          {error}
        </Alert>
      </Modal>
    </Stack>
  );
}
