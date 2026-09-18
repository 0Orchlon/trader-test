/**
 * Гарын арилжааны ticket (T-49, LLD §16.5, FR-12, AC-31…AC-33).
 *
 * Илгээхээс ӨМНӨ харагдах зүйл:
 * - тооцоолсон notional (сүүлийн quote-оор, `stale` бол ил тэмдэгтэй);
 * - Risk-ийн урьдчилсан үнэлгээ — backend-ийн 409/422 хариу нь ӨӨРӨӨ
 *   урьдчилсан үнэлгээ болно (тусдаа «dry-run» endpoint нэмэхгүй).
 *
 * `HALTED` үед илгээх товч ИДЭВХГҮЙ + шалтгаан харагдана.
 * `WINDING_DOWN` үед зөвхөн позиц БАГАСГАХ чиглэл сонгогдоно.
 *
 * **Зориудаар БАЙХГҮЙ:** one-click order, chart-аас чирж тавих, «дахин
 * худалдан ав» товч (спек §8-ийн dark-pattern хориг, `plan.md` P-8).
 */
import { useMemo, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
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
import { IconAlertTriangle, IconCheck, IconSend } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError, api, type ManualOrderRequest, type RiskEvaluation } from '@/lib/api';
import { formatMoney, multiply } from '@/lib/money';
import { useSystemState } from '@/hooks/useSystemState';

type Side = 'buy' | 'sell';
type OrderType = 'market' | 'limit' | 'stop' | 'stop_limit';

const ORDER_TYPES: { value: OrderType; label: string }[] = [
  { value: 'market', label: 'Market' },
  { value: 'limit', label: 'Limit' },
  { value: 'stop', label: 'Stop' },
  { value: 'stop_limit', label: 'Stop limit' },
];

/**
 * `winding_down` үед ямар чиглэл зөвшөөрөгдөх вэ.
 *
 * Байгаа позицийн эсрэг тал нь БАГАСГАХ чиглэл. Позицгүй symbol дээр
 * ямар ч чиглэл нь ШИНЭ эрсдэл тул хоёул хаагдана. Backend-ийн R2 нь
 * эцсийн хаалга хэвээр — энэ нь зөвхөн UI-ийн эрт мэдэгдэл.
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

  // Notional нь СҮҮЛИЙН QUOTE-оос (LLD §16.5) — operator-ийн бичсэн үнээс БИШ.
  // Risk Agent-ийн R9 ч ижил лавлах үнэ ашигладаг тул дэлгэц дээрх дүн нь
  // backend-ийн шалгах дүнтэй нэг утгатай.
  const ticker = symbol.trim().toUpperCase();
  const quote = useQuery({
    queryKey: ['quote', ticker],
    queryFn: () => api.quote(ticker),
    enabled: ticker !== '',
    refetchInterval: 10_000,
    retry: false,
  });

  // Лавлах үнэ нь `app/risk/rules.py::reference_price`-тай ЯГ ИЖИЛ дараалал:
  // limit үнэ бичигдсэн бол ТЭР, эс бөгөөс сүүлийн quote. Өмнө нь UI үргэлж
  // quote-ыг авдаг байсан тул limit order дээр дэлгэцийн дүн ба R9-ийн шалгах
  // дүн зөрдөг байв (N-1).
  const reference = useMemo(() => {
    if (orderType === 'limit' && limitPrice) return { price: limitPrice, label: 'limit үнэ' };
    const last = quote.data?.quote.last;
    return last ? { price: last, label: 'сүүлийн үнэ' } : null;
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

  // Илгээх ОРОЛДЛОГЫН таних тэмдэг. Баталгаажуулалтын хоёр дахь дуудалт нь
  // ИЖИЛ оролдлого (ижил key), харин operator ижил маягтыг дахин илгээвэл
  // ШИНЭ оролдлого — эс бөгөөс backend-ийн дедуп хуучин order-ыг буцааж,
  // UI нь илгээгээгүй order-ыг «хүлээн авав» гэж баталгаажуулна.
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
      // 409/422-ийн `risk` нь ӨӨРӨӨ урьдчилсан үнэлгээ (LLD §16.5).
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
      <Title order={3}>Гарын арилжаа</Title>

      {halted ? (
        <Alert color="red" icon={<IconAlertTriangle size={18} />} data-testid="halted-notice">
          Систем ЗОГССОН{system?.reason ? ` — ${system.reason}` : ''}. Шинэ order илгээх
          боломжгүй. Дээрх «Идэвхжүүл» товчоор л дахин эхэлнэ.
        </Alert>
      ) : null}

      {state === 'winding_down' ? (
        <Alert color="yellow" icon={<IconAlertTriangle size={18} />} data-testid="wind-down-notice">
          Унтраах бэлтгэл — зөвхөн позиц БАГАСГАХ чиглэл сонгогдоно. Эрсдэл нэмэгдүүлэх
          order татгалзагдана.
        </Alert>
      ) : null}

      <Card withBorder padding="md" component="form" onSubmit={(e) => e.preventDefault()}>
        <Stack gap="sm">
          <Group grow>
            <TextInput
              label="Symbol"
              placeholder="AAPL"
              value={symbol}
              data-testid="ticket-symbol"
              onChange={(e) => setSymbol(e.currentTarget.value.toUpperCase())}
            />
            <Select
              label="Тал"
              data={[
                { value: 'buy', label: 'Авах (buy)', disabled: !sides.includes('buy') },
                { value: 'sell', label: 'Зарах (sell)', disabled: !sides.includes('sell') },
              ]}
              value={side}
              data-testid="ticket-side"
              onChange={(value) => setSide((value as Side) ?? 'buy')}
            />
          </Group>

          <Group grow>
            <NumberInput
              label="Тоо ширхэг"
              placeholder="10"
              value={qty}
              min={0}
              decimalScale={9}
              data-testid="ticket-qty"
              onChange={(value) => setQty(String(value ?? ''))}
            />
            <Select
              label="Order төрөл"
              data={ORDER_TYPES}
              value={orderType}
              data-testid="ticket-order-type"
              onChange={(value) => setOrderType((value as OrderType) ?? 'limit')}
            />
          </Group>

          <Group grow>
            <TextInput
              label="Limit үнэ"
              placeholder="221.50"
              value={limitPrice}
              data-testid="ticket-limit-price"
              disabled={orderType === 'market' || orderType === 'stop'}
              onChange={(e) => setLimitPrice(e.currentTarget.value)}
            />
            <TextInput
              label="Stop үнэ"
              placeholder="215.00"
              value={stopPrice}
              data-testid="ticket-stop-price"
              disabled={orderType === 'market' || orderType === 'limit'}
              onChange={(e) => setStopPrice(e.currentTarget.value)}
            />
          </Group>

          <Group justify="space-between">
            <Group gap={8}>
              <Text size="sm" data-testid="ticket-notional">
                Тооцоолсон notional:{' '}
                <b>{quote.isError && !reference ? 'quote байхгүй' : formatMoney(notional)}</b>
                {reference ? ` (${reference.label} ${formatMoney(reference.price)})` : ''}
                {position ? ` · одоогийн позиц ${position.qty} ш` : ''}
              </Text>
              {quote.data?.stale ? (
                <Badge color="orange" variant="outline" data-testid="quote-stale">
                  quote хуучирсан
                </Badge>
              ) : null}
            </Group>
            <Button
              type="submit"
              leftSection={<IconSend size={16} />}
              loading={submit.isPending}
              disabled={!canSubmit}
              data-testid="ticket-submit"
              onClick={() => {
                attempt.current = newAttempt();
                submit.mutate(undefined);
              }}
            >
              Илгээх
            </Button>
          </Group>
        </Stack>
      </Card>

      {submitted ? (
        <Alert color="green" icon={<IconCheck size={18} />} data-testid="ticket-accepted">
          Хүлээн авав — `client_order_id` {submitted}. Гүйцэтгэлийг order жагсаалтаас хараарай.
        </Alert>
      ) : null}

      {problem && problem.code !== 'confirmation_required' ? (
        <Alert color="red" icon={<IconAlertTriangle size={18} />} data-testid="ticket-problem">
          <Text fw={600}>{problem.code ?? 'алдаа'}</Text>
          <Text size="sm">{problem.detail}</Text>
        </Alert>
      ) : null}

      {preview ? <RiskPreview risk={preview} /> : null}

      <Modal
        opened={confirmation !== null}
        onClose={() => setConfirmation(null)}
        title="Баталгаажуулалт"
        data-testid="ticket-confirm-modal"
      >
        <Stack gap="md">
          <Text data-testid="ticket-confirm-prompt">{confirmation?.prompt}</Text>
          <Text size="sm" c="dimmed">
            {body.side === 'buy' ? 'Авах' : 'Зарах'} {body.qty} ш {body.symbol}
            {notional ? ` · ойролцоогоор ${formatMoney(notional)}` : ''}
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmation(null)}>
              Болих
            </Button>
            <Button
              data-testid="ticket-confirm-accept"
              onClick={() => confirmation && submit.mutate(confirmation.token)}
            >
              Батлаад илгээх
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}

/** Risk-ийн шалгалтууд — юу унасныг БҮХЭЛД нь харуулна (LLD §8.1). */
export function RiskPreview({ risk }: { risk: RiskEvaluation }) {
  return (
    <Card withBorder padding="md" data-testid="risk-preview">
      <Group mb="sm" gap="sm">
        <Text fw={600}>Risk Agent-ийн үнэлгээ</Text>
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
            <Table.Th>Дүрэм</Table.Th>
            <Table.Th>Үр дүн</Table.Th>
            <Table.Th>Хязгаар</Table.Th>
            <Table.Th>Бодит</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {(risk.checks ?? []).map((check) => (
            <Table.Tr key={check.rule} data-testid="risk-check" data-rule={check.rule}>
              <Table.Td>{check.rule}</Table.Td>
              <Table.Td>
                <Badge color={check.passed ? 'green' : 'red'} variant="light">
                  {check.passed ? 'дамжив' : 'унав'}
                </Badge>
              </Table.Td>
              <Table.Td>
                {check.limit_name ? `${check.limit_name} ${check.limit_value ?? ''}` : '—'}
              </Table.Td>
              <Table.Td>{check.actual_value ?? check.detail ?? '—'}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Card>
  );
}

/** Илгээх оролдлого бүрийн давтагдашгүй тэмдэг. */
function newAttempt(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * `Idempotency-Key` = бие + ОРОЛДЛОГО.
 *
 * Зөвхөн биеэс гаргавал ижил параметртэй order мөнхөд ижил key авч,
 * backend-ийн дедуп (LLD §9.2) хуучин order-ыг буцаана — operator шинэ
 * order илгээсэн гэж итгэнэ. Оролдлогын тэмдэг нь баталгаажуулалтын хоёр
 * дахь дуудалтад ТОГТМОЛ, дараагийн илгээлтэд ШИНЭ.
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
