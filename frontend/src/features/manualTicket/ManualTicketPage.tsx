/**
 * Manual trade ticket (T-49, LLD §16.5, FR-12, AC-31…AC-33).
 *
 * Shown BEFORE submitting:
 * - estimated notional (from the last quote, marked `stale` if it is);
 * - Risk's preview — the backend's 409/422 response itself IS the
 *   preview (no separate "dry-run" endpoint is added).
 *
 * Submit is DISABLED + a reason is shown while `HALTED`.
 * While `WINDING_DOWN`, only a position-REDUCING direction is selectable.
 *
 * **Deliberately absent:** one-click orders, drag-from-chart, a "buy
 * again" button (dark-pattern ban in spec §8, `plan.md` P-8).
 */
import { useMemo, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Divider,
  Group,
  Modal,
  NumberInput,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { IconAlertTriangle, IconCheck, IconReceipt2, IconSend, IconWallet } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError, api, type ManualOrderRequest, type RiskEvaluation } from '@/lib/api';
import { formatMoney, formatQuantity, multiply, subtract } from '@/lib/money';
import { useSystemState } from '@/hooks/useSystemState';
import { Num } from '@/components/Num';
import { Pnl } from '@/components/Pnl';
import { PriceChart } from '@/components/PriceChart';

type Side = 'buy' | 'sell';
type OrderType = 'market' | 'limit' | 'stop' | 'stop_limit';

const ORDER_TYPES: { value: OrderType; label: string }[] = [
  { value: 'market', label: 'Market' },
  { value: 'limit', label: 'Limit' },
  { value: 'stop', label: 'Stop' },
  { value: 'stop_limit', label: 'Stop limit' },
];

/**
 * Which direction is allowed while `winding_down`.
 *
 * The opposite side of an existing position REDUCES it. On a symbol with
 * no position, either direction adds NEW risk, so both are blocked.
 * Backend R2 remains the final gate — this is only an early UI notice.
 */
export function allowedSides(
  state: string | undefined,
  positionQty: string | null | undefined,
): Side[] {
  if (state === 'halted') return [];
  if (state !== 'winding_down') return ['buy', 'sell'];
  if (!positionQty) return [];
  return positionQty.trimStart().startsWith('-') ? ['buy'] : ['sell'];
}

export function ManualTicketPage() {
  const queryClient = useQueryClient();
  const { data: system } = useSystemState();
  const { data: positions } = useQuery({ queryKey: ['positions'], queryFn: api.positions });
  const { data: capital } = useQuery({
    queryKey: ['capital-summary'],
    queryFn: api.capitalSummary,
    refetchInterval: 15_000,
  });
  // Quick-pick reuses the research agent's configured symbol universe
  // (same list as the Dashboard's watchlist picker) — not a separate
  // "most active" screener. Clicking one only fills the Symbol field;
  // it never submits (see the dark-pattern ban in the module docstring).
  const { data: researchStatus } = useQuery({
    queryKey: ['research-status'],
    queryFn: api.researchStatus,
  });
  const quickPick = researchStatus?.available_symbols ?? [];
  const quickPickStocks = quickPick.filter((s) => !s.includes('/'));
  const quickPickCrypto = quickPick.filter((s) => s.includes('/'));

  const [symbol, setSymbol] = useState('');
  const [side, setSide] = useState<Side>('buy');
  const [qty, setQty] = useState('');
  const [orderType, setOrderType] = useState<OrderType>('limit');
  const [limitPrice, setLimitPrice] = useState('');
  const [stopPrice, setStopPrice] = useState('');

  const [preview, setPreview] = useState<RiskEvaluation | null>(null);
  const [problem, setProblem] = useState<{ code?: string; detail: string } | null>(null);
  const [confirmation, setConfirmation] = useState<{ token: string; prompt: string } | null>(null);
  const [submitted, setSubmitted] = useState<string | null>(null);

  const state = system?.state;
  const position = positions?.positions.find((p) => p.symbol === symbol.toUpperCase());
  const sides = allowedSides(state, position?.qty ?? null);
  const halted = state === 'halted';

  // Notional comes from the LAST QUOTE (LLD §16.5) — not a price the
  // operator typed. The Risk Agent's R9 uses the same reference price, so
  // the number on screen matches what the backend checks.
  const ticker = symbol.trim().toUpperCase();
  const quote = useQuery({
    queryKey: ['quote', ticker],
    queryFn: () => api.quote(ticker),
    enabled: ticker !== '',
    refetchInterval: 10_000,
    retry: false,
  });

  // Reference price follows the EXACT same order as
  // `app/risk/rules.py::reference_price`: the limit price if one was
  // entered, otherwise the last quote. The UI used to always take the
  // quote, so on a limit order the on-screen figure and R9's check
  // figure disagreed (N-1).
  const reference = useMemo(() => {
    if (orderType === 'limit' && limitPrice) return { price: limitPrice, label: 'limit price' };
    const last = quote.data?.quote.last;
    return last ? { price: last, label: 'last price' } : null;
  }, [orderType, limitPrice, quote.data]);

  const notional = useMemo(() => {
    if (!qty || !reference) return null;
    return multiply(qty, reference.price);
  }, [qty, reference]);

  const body: ManualOrderRequest = useMemo(
    () => ({
      symbol: symbol.toUpperCase(),
      side,
      qty,
      order_type: orderType,
      time_in_force: 'day',
      ...(limitPrice ? { limit_price: limitPrice } : {}),
      ...(stopPrice ? { stop_price: stopPrice } : {}),
    }),
    [symbol, side, qty, orderType, limitPrice, stopPrice],
  );

  // Identifies each submit ATTEMPT. Confirmation's second call is the
  // SAME attempt (same key), but the operator resubmitting the same form
  // is a NEW attempt — otherwise the backend's dedup (LLD §9.2) would
  // return the old order, and the UI would confirm an order that was
  // never actually sent.
  const attempt = useRef(newAttempt());

  const submit = useMutation({
    mutationFn: (token?: string) =>
      api.manualOrder(
        token ? { ...body, confirmation_token: token } : body,
        idempotencyKeyFor(body, attempt.current),
      ),
    onSuccess: (result) => {
      setPreview(result.risk);
      setProblem(null);
      setConfirmation(null);
      setSubmitted(result.order.client_order_id);
      void queryClient.invalidateQueries({ queryKey: ['orders'] });
      void queryClient.invalidateQueries({ queryKey: ['positions'] });
      void queryClient.invalidateQueries({ queryKey: ['attribution'] });
    },
    onError: (err: Error) => {
      setSubmitted(null);
      if (!(err instanceof ApiError)) {
        setProblem({ detail: err.message });
        return;
      }
      // A 409/422's `risk` field IS the preview (LLD §16.5).
      setPreview(err.risk ?? null);
      setProblem({ code: err.code, detail: err.message });
      if (err.code === 'confirmation_required' && err.confirmation) {
        setConfirmation({ token: err.confirmation.token, prompt: err.confirmation.prompt });
      }
    },
  });

  const canSubmit =
    !halted && symbol.trim() !== '' && qty.trim() !== '' && sides.includes(side) && !submit.isPending;

  return (
    <Stack gap="md">
      <Group gap={8}>
        <IconReceipt2 size={22} color="var(--mantine-color-brand-5)" />
        <Title order={3}>Manual order</Title>
      </Group>

      <Card withBorder padding="sm" radius="md" maw={640} data-testid="available-to-trade">
        <Group gap={8}>
          <IconWallet size={16} color="var(--mantine-color-dimmed)" />
          <Text size="xs" c="dimmed" tt="uppercase" fw={600} style={{ letterSpacing: '0.03em' }}>
            Available to trade
          </Text>
        </Group>
        <Num fz={22} fw={700} span>
          {formatMoney(capital?.effective_equity)}
        </Num>
        <Text size="xs" c="dimmed">
          Broker equity {formatMoney(capital?.broker_equity)} minus {formatMoney(capital?.total_withdrawn)}{' '}
          withdrawn — this is the pool every risk check sizes against, not the raw account equity.
        </Text>
      </Card>

      {halted ? (
        <Alert color="red" icon={<IconAlertTriangle size={18} />} data-testid="halted-notice">
          System is HALTED{system?.reason ? ` — ${system.reason}` : ''}. New orders cannot
          be submitted. Use "Activate" above to resume.
        </Alert>
      ) : null}

      {state === 'winding_down' ? (
        <Alert color="yellow" icon={<IconAlertTriangle size={18} />} data-testid="wind-down-notice">
          Winding down — only a position-REDUCING direction can be selected.
          Risk-increasing orders are rejected.
        </Alert>
      ) : null}

      <Group align="flex-start" gap="md" wrap="wrap">
        <Stack gap="md" style={{ flex: '0 0 640px', maxWidth: 640 }}>
          {quickPick.length > 0 ? (
            <Card withBorder padding="sm" radius="md">
              <Text size="xs" c="dimmed" tt="uppercase" fw={600} style={{ letterSpacing: '0.03em' }} mb={6}>
                Quick pick — click to fill the symbol below
              </Text>
          <Group gap={4} data-testid="quick-pick-symbols">
            {quickPickStocks.map((s) => (
              <Badge
                key={s}
                size="sm"
                variant={symbol.toUpperCase() === s ? 'filled' : 'light'}
                color="blue"
                style={{ cursor: 'pointer' }}
                data-testid="quick-pick-symbol"
                onClick={() => setSymbol(s)}
              >
                {s}
              </Badge>
            ))}
            {quickPickCrypto.map((s) => (
              <Badge
                key={s}
                size="sm"
                variant={symbol.toUpperCase() === s ? 'filled' : 'light'}
                color="orange"
                style={{ cursor: 'pointer' }}
                data-testid="quick-pick-symbol"
                onClick={() => setSymbol(s)}
              >
                {s}
              </Badge>
            ))}
          </Group>
        </Card>
      ) : null}

      <Card withBorder padding="lg" radius="md" maw={640} component="form" onSubmit={(e) => e.preventDefault()}>
        <Stack gap="xs">
          <Group grow>
            <TextInput
              size="sm"
              label="Symbol"
              placeholder="AAPL"
              value={symbol}
              data-testid="ticket-symbol"
              onChange={(e) => setSymbol(e.currentTarget.value.toUpperCase())}
            />
            <Select
              size="sm"
              label="Side"
              data={[
                { value: 'buy', label: 'Buy', disabled: !sides.includes('buy') },
                { value: 'sell', label: 'Sell', disabled: !sides.includes('sell') },
              ]}
              value={side}
              data-testid="ticket-side"
              onChange={(value) => setSide((value as Side) ?? 'buy')}
            />
          </Group>

          <Group grow>
            <NumberInput
              size="sm"
              label="Quantity"
              placeholder="10"
              value={qty}
              min={0}
              decimalScale={9}
              data-testid="ticket-qty"
              onChange={(value) => setQty(String(value ?? ''))}
            />
            <Select
              size="sm"
              label="Order type"
              data={ORDER_TYPES}
              value={orderType}
              data-testid="ticket-order-type"
              onChange={(value) => setOrderType((value as OrderType) ?? 'limit')}
            />
          </Group>

          <Group grow>
            <TextInput
              size="sm"
              label="Limit price"
              placeholder="221.50"
              value={limitPrice}
              data-testid="ticket-limit-price"
              disabled={orderType === 'market' || orderType === 'stop'}
              onChange={(e) => setLimitPrice(e.currentTarget.value)}
            />
            <TextInput
              size="sm"
              label="Stop price"
              placeholder="215.00"
              value={stopPrice}
              data-testid="ticket-stop-price"
              disabled={orderType === 'market' || orderType === 'limit'}
              onChange={(e) => setStopPrice(e.currentTarget.value)}
            />
          </Group>

          <Divider my={2} />

          <Group justify="space-between" align="flex-end" wrap="wrap" gap="sm">
            <Stack gap={2} data-testid="ticket-notional">
              <Group gap={6}>
                <Text size="xs" c="dimmed" tt="uppercase" fw={600} style={{ letterSpacing: '0.03em' }}>
                  Estimated notional
                </Text>
                {quote.data?.stale ? (
                  <Badge color="orange" variant="outline" size="xs" data-testid="quote-stale">
                    quote stale
                  </Badge>
                ) : null}
              </Group>
              <Num fz={28} fw={700} span>
                {quote.isError && !reference ? 'no quote' : formatMoney(notional)}
              </Num>
              <Text size="sm" c="dimmed">
                {reference ? `(${reference.label} ${formatMoney(reference.price)})` : ''}
                {position ? ` · current position ${position.qty} shares` : ''}
              </Text>
            </Stack>
            <Button
              type="submit"
              size="md"
              leftSection={<IconSend size={16} />}
              loading={submit.isPending}
              disabled={!canSubmit}
              data-testid="ticket-submit"
              onClick={() => {
                attempt.current = newAttempt();
                submit.mutate(undefined);
              }}
            >
              Send
            </Button>
          </Group>
        </Stack>
      </Card>
        </Stack>

        <Card
          withBorder
          padding="md"
          radius="md"
          style={{ flex: 1, minWidth: 280 }}
          data-testid="symbol-snapshot"
        >
          <Text size="xs" c="dimmed" tt="uppercase" fw={600} style={{ letterSpacing: '0.03em' }} mb={8}>
            Symbol snapshot
          </Text>
          {ticker === '' ? (
            <Text size="sm" c="dimmed">
              Pick a symbol to see its live quote and your current position here.
            </Text>
          ) : (
            <Stack gap="sm">
              <Group justify="space-between">
                <Text fw={700}>{ticker}</Text>
                {quote.data?.stale ? (
                  <Badge color="orange" variant="outline" size="xs">
                    quote stale
                  </Badge>
                ) : null}
              </Group>

              <Group grow>
                <Stack gap={0}>
                  <Text size="xs" c="dimmed">
                    Bid
                  </Text>
                  <Num fw={600}>{quote.data ? formatMoney(quote.data.quote.bid) : '—'}</Num>
                </Stack>
                <Stack gap={0}>
                  <Text size="xs" c="dimmed">
                    Ask
                  </Text>
                  <Num fw={600}>{quote.data ? formatMoney(quote.data.quote.ask) : '—'}</Num>
                </Stack>
                <Stack gap={0}>
                  <Text size="xs" c="dimmed">
                    Last
                  </Text>
                  <Num fw={600}>{quote.data ? formatMoney(quote.data.quote.last) : '—'}</Num>
                </Stack>
              </Group>

              <PriceChart symbol={ticker} entryPrice={position?.avg_entry_price} height={220} />

              <Divider my={2} />

              <Text size="xs" c="dimmed" tt="uppercase" fw={600} style={{ letterSpacing: '0.03em' }}>
                Your position
              </Text>
              {position ? (
                <Stack gap={4}>
                  <Group justify="space-between">
                    <Text size="sm" c="dimmed">
                      Qty
                    </Text>
                    <Num size="sm">{formatQuantity(position.qty)}</Num>
                  </Group>
                  <Group justify="space-between">
                    <Text size="sm" c="dimmed">
                      Avg entry
                    </Text>
                    <Num size="sm">{formatMoney(position.avg_entry_price)}</Num>
                  </Group>
                  <Group justify="space-between">
                    <Text size="sm" c="dimmed">
                      Market value
                    </Text>
                    <Num size="sm">{formatMoney(position.market_value)}</Num>
                  </Group>
                  <Group justify="space-between">
                    <Text size="sm" c="dimmed">
                      Unrealized P&amp;L
                    </Text>
                    <Pnl
                      size="sm"
                      value={position.unrealized_pl}
                      costBasis={subtract(position.market_value, position.unrealized_pl)}
                    />
                  </Group>
                </Stack>
              ) : (
                <Text size="sm" c="dimmed">
                  No open position in {ticker}.
                </Text>
              )}
            </Stack>
          )}
        </Card>
      </Group>

      {submitted ? (
        <Alert color="green" icon={<IconCheck size={18} />} data-testid="ticket-accepted">
          Accepted — `client_order_id` {submitted}. Check the orders list for fill status.
        </Alert>
      ) : null}

      {problem && problem.code !== 'confirmation_required' ? (
        <Alert color="red" icon={<IconAlertTriangle size={18} />} data-testid="ticket-problem">
          <Text fw={600}>{problem.code ?? 'error'}</Text>
          <Text size="sm">{problem.detail}</Text>
        </Alert>
      ) : null}

      {preview ? <RiskPreview risk={preview} /> : null}

      <Modal
        opened={confirmation !== null}
        onClose={() => setConfirmation(null)}
        title="Confirmation"
        data-testid="ticket-confirm-modal"
      >
        <Stack gap="md">
          <Text data-testid="ticket-confirm-prompt">{confirmation?.prompt}</Text>
          <Text size="sm" c="dimmed">
            {body.side === 'buy' ? 'Buy' : 'Sell'} {body.qty} shares {body.symbol}
            {notional ? ` · approximately ${formatMoney(notional)}` : ''}
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmation(null)}>
              Cancel
            </Button>
            <Button
              data-testid="ticket-confirm-accept"
              onClick={() => confirmation && submit.mutate(confirmation.token)}
            >
              Confirm and send
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}

/** Risk's checks — shows ALL of what failed, not just one (LLD §8.1). */
export function RiskPreview({ risk }: { risk: RiskEvaluation }) {
  return (
    <Card withBorder padding="md" radius="md" data-testid="risk-preview">
      <Group mb="sm" gap="sm">
        <Text fw={600}>Risk Agent's evaluation</Text>
        <Badge color={risk.decision === 'APPROVE' ? 'green' : 'red'}>{risk.decision}</Badge>
      </Group>
      {risk.reason ? (
        <Text size="sm" c="dimmed" mb="sm">
          {risk.reason}
        </Text>
      ) : null}
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Rule</Table.Th>
            <Table.Th>Result</Table.Th>
            <Table.Th>Limit</Table.Th>
            <Table.Th>Actual</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {(risk.checks ?? []).map((check) => (
            <Table.Tr key={check.rule} data-testid="risk-check" data-rule={check.rule}>
              <Table.Td>{check.rule}</Table.Td>
              <Table.Td>
                <Badge color={check.passed ? 'green' : 'red'} variant="light">
                  {check.passed ? 'passed' : 'failed'}
                </Badge>
              </Table.Td>
              <Table.Td>
                {check.limit_name ? (
                  <Group gap={4} wrap="nowrap">
                    <Text size="sm" c="dimmed">
                      {check.limit_name}
                    </Text>
                    {check.limit_value ? <Num size="sm">{check.limit_value}</Num> : null}
                  </Group>
                ) : (
                  '—'
                )}
              </Table.Td>
              <Table.Td>
                {check.actual_value ? <Num size="sm">{check.actual_value}</Num> : (check.detail ?? '—')}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Card>
  );
}

/** A unique tag for each submit ATTEMPT. */
function newAttempt(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * `Idempotency-Key` = body + ATTEMPT.
 *
 * From the body alone, an identical-parameter order would keep the same
 * key forever, and the backend's dedup (LLD §9.2) would return the old
 * order — leading the operator to believe a new order was submitted. The
 * attempt tag stays FIXED across confirmation's second call, and is NEW
 * on the next submit.
 */
export function idempotencyKeyFor(body: ManualOrderRequest, attempt: string): string {
  const canonical = JSON.stringify([
    attempt,
    body.symbol,
    body.side,
    body.qty,
    body.order_type,
    body.time_in_force,
    body.limit_price ?? null,
    body.stop_price ?? null,
  ]);
  let h1 = 0x811c9dc5;
  let h2 = 0x01000193;
  for (let i = 0; i < canonical.length; i += 1) {
    h1 = Math.imul(h1 ^ canonical.charCodeAt(i), 0x01000193) >>> 0;
    h2 = Math.imul(h2 + canonical.charCodeAt(i), 0x85ebca6b) >>> 0;
  }
  const hex = (n: number) => n.toString(16).padStart(8, '0');
  const digits = `${hex(h1)}${hex(h2)}${hex(h1 ^ h2)}${hex((h1 + h2) >>> 0)}`;
  return [
    digits.slice(0, 8),
    digits.slice(8, 12),
    `4${digits.slice(13, 16)}`,
    `8${digits.slice(17, 20)}`,
    digits.slice(20, 32),
  ].join('-');
}
