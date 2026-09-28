/**
 * Autonomous research cycle countdown + manual run button + watchlist
 * picker + manual-position auto-take-profit toggle (T-99, personal
 * project, not in the LLD). Re-reads `GET /research/status` every 10s
 * and counts down client-side every second (no spamming the server).
 * Click a badge to pick which symbols are active, then hit "Save" —
 * the next cycle scans only those.
 */
import { useEffect, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Group,
  ScrollArea,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
} from '@mantine/core';
import { IconCheck, IconPlayerPlay } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { formatCountdown, formatMoney } from '@/lib/money';
import { Num } from '@/components/Num';

export function ResearchCycleTimer() {
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: ['research-status'],
    queryFn: api.researchStatus,
    refetchInterval: 10_000,
  });
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<string> | null>(null);

  useEffect(() => {
    const nextRunAt = status.data?.next_run_at;
    if (!nextRunAt) {
      setSecondsLeft(null);
      return;
    }
    const target = Date.parse(nextRunAt);
    const tick = () => setSecondsLeft(Math.max(0, Math.round((target - Date.now()) / 1000)));
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [status.data?.next_run_at]);

  // Seed from the server's active selection ONLY ONCE — must NOT be
  // clobbered by a later refetch overriding what the user just clicked.
  useEffect(() => {
    if (selected === null && status.data?.symbols) {
      setSelected(new Set(status.data.symbols));
    }
  }, [selected, status.data?.symbols]);

  const runNow = useMutation({
    mutationFn: api.runResearchNow,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['research-status'] });
      // The LLM cycle takes several seconds — the decision list isn't
      // ready immediately, so wait a bit before asking again.
      window.setTimeout(
        () => void queryClient.invalidateQueries({ queryKey: ['agent-decisions'] }),
        20_000,
      );
    },
  });

  const saveWatchlist = useMutation({
    mutationFn: (symbols: string[]) => api.setResearchWatchlist(symbols),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['research-status'] }),
  });

  const manualTakeProfit = useQuery({
    queryKey: ['manual-take-profit'],
    queryFn: api.manualTakeProfit,
  });
  const setManualTakeProfit = useMutation({
    mutationFn: (enabled: boolean) => api.setManualTakeProfit(enabled),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['manual-take-profit'] }),
  });

  const running = status.data?.running ?? false;
  const available = status.data?.available_symbols ?? [];
  const stocks = available.filter((s) => !s.includes('/'));
  const crypto = available.filter((s) => s.includes('/'));
  const activeSet = status.data?.symbols ? new Set(status.data.symbols) : null;
  const dirty = selected !== null && activeSet !== null && !setsEqual(selected, activeSet);

  const toggle = (symbol: string) => {
    setSelected((prev) => {
      const next = new Set(prev ?? []);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      return next;
    });
  };

  const renderTable = (symbols: string[], label: string) => (
    <div>
      <Text size="xs" c="dimmed" tt="uppercase" fw={600} style={{ letterSpacing: '0.03em' }} mb={4}>
        {label} ({symbols.length})
      </Text>
      <ScrollArea h={220} type="auto">
        <Table stickyHeader highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={28} />
              <Table.Th>Symbol</Table.Th>
              <Table.Th>Price</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {symbols.map((s) => (
              <WatchlistRow
                key={s}
                symbol={s}
                selected={selected?.has(s) ?? false}
                onToggle={() => toggle(s)}
              />
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>
    </div>
  );

  return (
    <Card withBorder padding="sm" data-testid="research-cycle-timer">
      <Stack gap="xs">
        <Group justify="space-between">
          <Group gap="xs">
            <Text size="sm" c="dimmed">
              Next autonomous cycle:
            </Text>
            {running ? (
              <Badge color="blue" variant="light">
                running…
              </Badge>
            ) : (
              <Num fw={700} data-testid="research-cycle-countdown">
                {secondsLeft === null ? '—' : formatCountdown(secondsLeft)}
              </Num>
            )}
          </Group>
          <Button
            size="xs"
            variant="light"
            leftSection={<IconPlayerPlay size={14} />}
            loading={runNow.isPending || running}
            disabled={runNow.isPending || running}
            data-testid="research-run-now"
            onClick={() => runNow.mutate()}
          >
            Run now
          </Button>
        </Group>

        <Stack gap={4}>
          <Group justify="space-between">
            <Text size="xs" c="dimmed">
              Watchlist ({selected?.size ?? 0}/{available.length}) — click to select:
            </Text>
            <Button
              size="compact-xs"
              variant={dirty ? 'filled' : 'default'}
              leftSection={<IconCheck size={12} />}
              disabled={!dirty || saveWatchlist.isPending}
              loading={saveWatchlist.isPending}
              data-testid="watchlist-save"
              onClick={() => selected && saveWatchlist.mutate(Array.from(selected))}
            >
              Save
            </Button>
          </Group>
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm" data-testid="research-symbols">
            {renderTable(stocks, 'Stocks')}
            {renderTable(crypto, 'Crypto')}
          </SimpleGrid>
        </Stack>

        <Switch
          label="Auto-close manual positions once profitable"
          description="Leaves pure research_agent positions alone — exits.py manages those"
          checked={manualTakeProfit.data?.enabled ?? false}
          disabled={manualTakeProfit.isPending || setManualTakeProfit.isPending}
          data-testid="manual-take-profit-toggle"
          onChange={(e) => setManualTakeProfit.mutate(e.currentTarget.checked)}
        />
      </Stack>
    </Card>
  );
}

/**
 * One watchlist row, symbol + its own live price (T-99, personal project —
 * a watchlist without prices is just a settings list). Each row fetches
 * its own quote so this stays a plain per-item component, not a hook
 * called in a loop.
 */
function WatchlistRow({
  symbol,
  selected,
  onToggle,
}: {
  symbol: string;
  selected: boolean;
  onToggle: () => void;
}) {
  const quote = useQuery({
    queryKey: ['quote', symbol],
    queryFn: () => api.quote(symbol),
    refetchInterval: 30_000,
    retry: false,
  });
  const last = quote.data?.quote.last;
  return (
    <Table.Tr
      style={{ cursor: 'pointer' }}
      bg={selected ? 'var(--mantine-color-dark-6)' : undefined}
      data-testid="watchlist-symbol"
      data-selected={selected}
      onClick={onToggle}
    >
      <Table.Td>
        <Checkbox checked={selected} onChange={onToggle} size="xs" readOnly tabIndex={-1} />
      </Table.Td>
      <Table.Td fw={600}>{symbol}</Table.Td>
      <Table.Td>
        <Num size="xs">{last ? formatMoney(last) : '—'}</Num>
      </Table.Td>
    </Table.Tr>
  );
}

function setsEqual(a: Set<string>, b: Set<string>): boolean {
  if (a.size !== b.size) return false;
  for (const item of a) if (!b.has(item)) return false;
  return true;
}
