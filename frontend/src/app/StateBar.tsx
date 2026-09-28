/**
 * State bar + three buttons (T-51, LLD §16.2, §16.3, AC-38).
 *
 * Three buttons, three DIFFERENT meanings — different color, different
 * position, different question:
 *
 * | Button           | Color / position | Question |
 * |------------------|-------------------|----------|
 * | Kill switch      | red, left         | NONE — fires immediately |
 * | Wind down        | yellow, center     | NONE — a risk-REDUCING action |
 * | Activate         | green, right       | Backend's `confirmation.prompt` |
 *
 * Confirmation applies ONLY to a risk-INCREASING path (one of §8.4's three
 * actions). Wind-down is on the kill switch's side: it never adds new
 * risk, and misclicking it can be reversed with `Activate` (which does
 * confirm). This keeps policy text out of the UI (§16.3) — the one
 * remaining question comes straight from the backend's 409 response
 * (N-6's solution).
 */
import { useState } from 'react';
import { Badge, Button, Group, Modal, Stack, Text, Tooltip } from '@mantine/core';
import { IconPlayerPlay, IconPlayerStop, IconMoon } from '@tabler/icons-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { ApiError, api, type SystemStateEnvelope } from '@/lib/api';
import { formatCountdown } from '@/lib/money';
import { systemStateKey } from '@/hooks/useSystemState';
import { Num } from '@/components/Num';

const STATE_BADGE = {
  active: { color: 'green', label: 'ACTIVE' },
  winding_down: { color: 'yellow', label: 'WINDING DOWN' },
  halted: { color: 'red', label: 'HALTED' },
} as const;

type Pending = { action: 'activate'; prompt: string; token?: string } | null;

export function StateBar({ state }: { state: SystemStateEnvelope | undefined }) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<Pending>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: systemStateKey });
    void queryClient.invalidateQueries({ queryKey: ['orders'] });
  };

  const kill = useMutation({
    mutationFn: () => api.killSwitch('Operator kill switch'),
    onSuccess: refresh,
  });

  const windDown = useMutation({
    mutationFn: () => api.windDown('Operator: shutting down soon'),
    onSuccess: refresh,
    onError: (err: Error) => setError(err.message),
  });

  const activate = useMutation({
    mutationFn: (token?: string) => api.activate(token),
    onSuccess: () => {
      setPending(null);
      refresh();
    },
    onError: (err: Error) => {
      // A 409 `confirmation_required` is NOT an error — it's the next flow step.
      if (err instanceof ApiError && err.code === 'confirmation_required' && err.confirmation) {
        setPending({
          action: 'activate',
          prompt: err.confirmation.prompt,
          token: err.confirmation.token,
        });
        return;
      }
      setError(err.message);
    },
  });

  const current = state?.state;
  const badge = current ? STATE_BADGE[current] : null;
  const busy = kill.isPending || windDown.isPending || activate.isPending;

  return (
    <>
      <Group
        component="nav"
        data-testid="state-bar"
        data-state={current ?? 'unknown'}
        justify="space-between"
        px="md"
        py={8}
        style={{
          background: 'var(--mantine-color-dark-7)',
          borderBottom: '1px solid var(--mantine-color-dark-5)',
        }}
      >
        {/* LEFT — kill switch. No confirmation (AC-38). */}
        <Button
          data-testid="kill-switch"
          color="red"
          variant="filled"
          size="sm"
          leftSection={<IconPlayerStop size={16} />}
          loading={kill.isPending}
          disabled={busy}
          onClick={() => kill.mutate()}
        >
          Kill switch
        </Button>

        <Group gap="sm">
          {badge ? (
            <Badge color={badge.color} size="lg" data-testid="state-badge">
              {badge.label}
            </Badge>
          ) : null}
          {current === 'winding_down' ? (
            <Num size="sm" data-testid="wind-down-countdown">
              Winding down · {formatCountdown(state?.seconds_remaining ?? null)} remaining
            </Num>
          ) : null}
          {current === 'halted' && state?.reason ? (
            <Text size="sm" c="red.6" data-testid="halt-reason">
              {state.reason}
            </Text>
          ) : null}
        </Group>

        <Group gap="sm">
          {/* CENTER — wind down. */}
          <Tooltip
            label="Cannot wind down a halted system"
            disabled={current !== 'halted'}
          >
            <Button
              data-testid="wind-down"
              color="yellow"
              variant="filled"
              size="sm"
              leftSection={<IconMoon size={16} />}
              disabled={busy || current !== 'active'}
              loading={windDown.isPending}
              onClick={() => windDown.mutate()}
            >
              Wind down
            </Button>
          </Tooltip>

          {/* RIGHT — activate. */}
          <Button
            data-testid="activate"
            color="green"
            variant="filled"
            size="sm"
            leftSection={<IconPlayerPlay size={16} />}
            loading={activate.isPending}
            disabled={busy || current === 'active'}
            onClick={() => activate.mutate(undefined)}
          >
            Activate
          </Button>
        </Group>
      </Group>

      <Modal
        opened={pending !== null}
        onClose={() => setPending(null)}
        title="Activate"
        data-testid="confirm-modal"
      >
        <Stack gap="md">
          <Text data-testid="confirm-prompt">{pending?.prompt}</Text>
          <BreakerMetrics state={state} />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setPending(null)}>
              Cancel
            </Button>
            <Button
              data-testid="confirm-accept"
              color="green"
              onClick={() => activate.mutate(pending?.token)}
            >
              Yes
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal opened={error !== null} onClose={() => setError(null)} title="Error">
        <Text data-testid="state-error">{error}</Text>
      </Modal>
    </>
  );
}

/** Breaker's CURRENT metrics, before activating (AC-37). */
function BreakerMetrics({ state }: { state: SystemStateEnvelope | undefined }) {
  const metrics = state?.breaker_metrics ?? [];
  if (metrics.length === 0) return null;
  return (
    <Stack gap={4} data-testid="breaker-metrics">
      <Text size="sm" fw={600}>
        Current circuit breaker metrics
      </Text>
      {metrics.map((metric) => {
        // Showing "unmeasured" as a number is a false green: the operator
        // would read "api_error_rate 0.0000 — normal" (B-1, appendix 10).
        const unmeasured = metric.value === 'unmeasured';
        return (
          <Text
            key={metric.metric}
            size="xs"
            data-testid={`breaker-metric-${metric.metric}`}
            c={metric.tripped ? 'red.6' : unmeasured ? 'orange.7' : 'dimmed'}
          >
            {metric.metric}:{' '}
            <Num span size="xs" c="inherit">
              {unmeasured ? 'UNMEASURED' : metric.value}
            </Num>{' '}
            (limit {metric.limit_name}{' '}
            <Num span size="xs" c="inherit">
              {metric.limit_value}
            </Num>
            ){metric.tripped ? ' — TRIPPED' : ''}
          </Text>
        );
      })}
    </Stack>
  );
}
