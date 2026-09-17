/**
 * Төлөвийн самбар + гурван товч (T-51, LLD §16.2, §16.3, AC-38).
 *
 * Гурван товч, гурван ӨӨР утга — өөр өнгө, өөр байрлал, өөр асуулт:
 *
 * | Товч             | Өнгө / байрлал | Асуулт |
 * |------------------|----------------|--------|
 * | Зогсоо           | улаан, зүүн    | БАЙХГҮЙ — тэр дор нь ажиллана |
 * | Унтраах бэлтгэл  | шар, төв       | БАЙХГҮЙ — эрсдэл БУУРУУЛАХ үйлдэл |
 * | Идэвхжүүл        | ногоон, баруун | Backend-ийн `confirmation.prompt` |
 *
 * Баталгаажуулалт нь ЗӨВХӨН эрсдэл НЭМЭГДҮҮЛЭХ замд (§8.4-ийн гурван
 * үйлдэл). Wind-down нь kill switch-тэй нэг тал дээр: шинэ эрсдэл
 * нэмэхгүй, буруу дарвал `Идэвхжүүл`-ээр (баталгаажуулалттай) буцна.
 * Ингэснээр UI-д бодлогын текст хатуу кодлогдохгүй (§16.3) — үлдсэн
 * ганц асуулт нь backend-ийн 409 хариунаас ирнэ (N-6-ийн шийдэл).
 */
import { useState } from 'react';
import { Badge, Button, Group, Modal, Stack, Text, Tooltip } from '@mantine/core';
import { IconPlayerPlay, IconPlayerStop, IconMoon } from '@tabler/icons-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { ApiError, api, type SystemStateEnvelope } from '@/lib/api';
import { formatCountdown } from '@/lib/money';
import { systemStateKey } from '@/hooks/useSystemState';

const STATE_BADGE = {
  active: { color: 'green', label: 'ИДЭВХТЭЙ' },
  winding_down: { color: 'yellow', label: 'ХААХ ЦОНХ' },
  halted: { color: 'red', label: 'ЗОГССОН' },
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
    mutationFn: () => api.windDown('Operator: удахгүй унтраана'),
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
      // 409 `confirmation_required` нь АЛДАА БИШ — урсгалын дараагийн алхам.
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
        style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}
      >
        {/* ЗҮҮН — Зогсоо. Асуулт БАЙХГҮЙ (AC-38). */}
        <Button
          data-testid="kill-switch"
          color="red"
          variant="filled"
          leftSection={<IconPlayerStop size={16} />}
          loading={kill.isPending}
          disabled={busy}
          onClick={() => kill.mutate()}
        >
          Зогсоо
        </Button>

        <Group gap="sm">
          {badge ? (
            <Badge color={badge.color} size="lg" data-testid="state-badge">
              {badge.label}
            </Badge>
          ) : null}
          {current === 'winding_down' ? (
            <Text size="sm" data-testid="wind-down-countdown">
              Позиц хаах цонх · үлдсэн {formatCountdown(state?.seconds_remaining ?? null)}
            </Text>
          ) : null}
          {current === 'halted' && state?.reason ? (
            <Text size="sm" c="red.6" data-testid="halt-reason">
              {state.reason}
            </Text>
          ) : null}
        </Group>

        <Group gap="sm">
          {/* ТӨВ — Унтраах бэлтгэл. */}
          <Tooltip
            label="Зогссон системийг wind-down хийх боломжгүй"
            disabled={current !== 'halted'}
          >
            <Button
              data-testid="wind-down"
              color="yellow"
              variant="filled"
              leftSection={<IconMoon size={16} />}
              disabled={busy || current !== 'active'}
              loading={windDown.isPending}
              onClick={() => windDown.mutate()}
            >
              Унтраах бэлтгэл
            </Button>
          </Tooltip>

          {/* БАРУУН — Идэвхжүүл. */}
          <Button
            data-testid="activate"
            color="green"
            variant="filled"
            leftSection={<IconPlayerPlay size={16} />}
            loading={activate.isPending}
            disabled={busy || current === 'active'}
            onClick={() => activate.mutate(undefined)}
          >
            Идэвхжүүл
          </Button>
        </Group>
      </Group>

      <Modal
        opened={pending !== null}
        onClose={() => setPending(null)}
        title="Идэвхжүүлэх"
        data-testid="confirm-modal"
      >
        <Stack gap="md">
          <Text data-testid="confirm-prompt">{pending?.prompt}</Text>
          <BreakerMetrics state={state} />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setPending(null)}>
              Болих
            </Button>
            <Button
              data-testid="confirm-accept"
              color="green"
              onClick={() => activate.mutate(pending?.token)}
            >
              Тийм
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal opened={error !== null} onClose={() => setError(null)} title="Алдаа">
        <Text data-testid="state-error">{error}</Text>
      </Modal>
    </>
  );
}

/** Идэвхжүүлэхийн өмнө breaker-ийн ОДООГИЙН хэмжилт (AC-37). */
function BreakerMetrics({ state }: { state: SystemStateEnvelope | undefined }) {
  const metrics = state?.breaker_metrics ?? [];
  if (metrics.length === 0) return null;
  return (
    <Stack gap={4} data-testid="breaker-metrics">
      <Text size="sm" fw={600}>
        Circuit breaker-ийн одоогийн метрик
      </Text>
      {metrics.map((metric) => (
        <Text key={metric.metric} size="xs" c={metric.tripped ? 'red.6' : 'dimmed'}>
          {metric.metric}: {metric.value} (хязгаар {metric.limit_name} {metric.limit_value})
          {metric.tripped ? ' — УНАСАН' : ''}
        </Text>
      ))}
    </Stack>
  );
}
