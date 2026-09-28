/**
 * Approval Queue UI (T-31, LLD §16.6, AC-5, AC-6).
 *
 * Every proposal shows: the agent's rationale, a link to the cited
 * evidence, the Risk checks, a TTL countdown. The "Approve" button is
 * NOT placed where it could be clicked before seeing the rationale — the
 * rationale is INSIDE the card, above the button.
 *
 * `expected_version` comes from each row's `version` — racing the reaper
 * gets a 409 from the backend, and the UI re-fetches.
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
import { formatLocalDateTimeWithUtc, formatMoney, formatQuantity } from '@/lib/money';
import { RiskPreview } from '@/features/manualTicket/ManualTicketPage';
import { Num } from '@/components/Num';

const STATES = ['pending', 'approved', 'rejected', 'expired', 'all'] as const;

const STATE_COLOR: Record<string, string> = {
  pending: 'yellow',
  approved: 'green',
  rejected: 'red',
  expired: 'gray',
};

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
        <Title order={3}>Approval queue</Title>
        <SegmentedControl
          data={STATES.map((s) => ({ value: s, label: s }))}
          value={state}
          onChange={setState}
          data-testid="approvals-filter"
        />
      </Group>

      {rows.length === 0 ? (
        <Alert color="gray" data-testid="approvals-empty">
          No pending proposals. No calls have been made to Alpaca.
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
              <Num span>{formatQuantity(row.proposed_order.qty)} shares</Num>
              <Text c="dimmed">{row.proposed_order.order_type}</Text>
              {row.proposed_order.limit_price ? (
                <Num span c="dimmed">
                  @ {formatMoney(row.proposed_order.limit_price)}
                </Num>
              ) : null}
            </Group>
            <Group gap="sm">
              <Badge variant="light" color={STATE_COLOR[row.state] ?? 'gray'} data-testid="approval-state">
                {row.state}
              </Badge>
              <Num span size="xs" c="dimmed" data-testid="approval-ttl">
                expires: {formatLocalDateTimeWithUtc(row.expires_at)}
              </Num>
            </Group>
          </Group>

          <Text size="sm" c="dimmed" mb={4}>
            {row.proposed_order.provider} / {row.proposed_order.model} ·{' '}
            <Num span c="dimmed" fw={600}>
              {formatMoney(row.proposed_order.estimated_notional)}
            </Num>
          </Text>

          <Card withBorder padding="sm" mb="sm" bg="dark.6">
            <Text size="sm" fw={600} mb={4}>
              Agent's rationale
            </Text>
            <Text size="sm" data-testid="approval-rationale">
              {row.proposed_order.rationale}
            </Text>
            <Group gap="xs" mt="xs">
              <Text size="xs" c="dimmed">
                Cited evidence ({row.proposed_order.grounded_in.length} tool calls):
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
                  view raw payload
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
                Reject
              </Button>
              <Button
                color="green"
                leftSection={<IconCheck size={16} />}
                loading={approve.isPending}
                data-testid="approval-approve"
                onClick={() => approve.mutate(row)}
              >
                Approve
              </Button>
            </Group>
          ) : (
            <Text size="sm" c="dimmed" mt="sm" data-testid="approval-resolution">
              {row.state} ·{' '}
              <Num span c="dimmed">
                {formatLocalDateTimeWithUtc(row.resolved_at)}
              </Num>
              {row.resolution_reason ? ` — ${row.resolution_reason}` : ''}
            </Text>
          )}
        </Card>
      ))}

      <Modal
        opened={rejecting !== null}
        onClose={() => setRejecting(null)}
        title="Reject"
        data-testid="reject-modal"
      >
        <Stack gap="md">
          <Text size="sm">
            A rejected proposal is NEVER submitted. This action cannot be undone.
          </Text>
          <Textarea
            label="Reason"
            required
            value={reason}
            data-testid="reject-reason"
            onChange={(e) => setReason(e.currentTarget.value)}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setRejecting(null)}>
              Cancel
            </Button>
            <Button
              color="red"
              disabled={reason.trim() === ''}
              data-testid="reject-confirm"
              onClick={() => rejecting && reject.mutate(rejecting)}
            >
              Reject
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal opened={error !== null} onClose={() => setError(null)} title="Error">
        <Alert color="red" icon={<IconAlertTriangle size={18} />} data-testid="approvals-error">
          {error}
        </Alert>
      </Modal>
    </Stack>
  );
}
