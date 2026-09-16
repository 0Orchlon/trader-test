/**
 * Agent Activity Log (T-32, LLD §16.6, AC-7, AC-8).
 *
 * Мөр бүр **ТҮҮХИЙ tool call payload** руу задарна. Хураангуй БАЙХГҮЙ:
 * «AI яагаад ингэж хэлсэн бэ» гэдгийн хариу нь дүгнэлт биш, ӨГӨГДӨЛ.
 * Хураангуйлбал operator-т модельд итгэхээс өөр сонголт үлдэхгүй.
 */
import { useState } from 'react';
import {
  Accordion,
  Alert,
  Badge,
  Card,
  Code,
  Group,
  Loader,
  ScrollArea,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';

import { api, type AgentDecision } from '@/lib/api';
import { formatMoney, formatQuantity, formatUtc } from '@/lib/money';

const OUTCOME_COLOR: Record<string, string> = {
  executed: 'green',
  approved: 'green',
  awaiting_approval: 'yellow',
  risk_rejected: 'red',
  grounding_failed: 'orange',
  order_failed: 'red',
};

export function DecisionsPage() {
  const [params, setParams] = useSearchParams();
  const [outcome, setOutcome] = useState<string | null>(null);
  const [provider, setProvider] = useState<string | null>(null);
  const symbol = params.get('symbol') ?? '';

  const query = new URLSearchParams();
  if (symbol) query.set('symbol', symbol);
  if (outcome) query.set('outcome', outcome);
  if (provider) query.set('provider', provider);

  const { data, isLoading } = useQuery({
    queryKey: ['decisions', query.toString()],
    queryFn: () => api.decisions(query.toString()),
    refetchInterval: 15_000,
  });

  if (isLoading) return <Loader data-testid="decisions-loading" />;
  const rows = data?.decisions ?? [];

  return (
    <Stack gap="md">
      <Title order={3}>Шийдвэрийн лог</Title>

      <Group>
        <TextInput
          label="Symbol"
          placeholder="бүгд"
          value={symbol}
          data-testid="decisions-symbol"
          onChange={(e) => {
            const next = e.currentTarget.value.toUpperCase();
            setParams(next ? { symbol: next } : {});
          }}
        />
        <Select
          label="Үр дүн"
          placeholder="бүгд"
          clearable
          data={Object.keys(OUTCOME_COLOR)}
          value={outcome}
          data-testid="decisions-outcome"
          onChange={setOutcome}
        />
        <TextInput
          label="Provider"
          placeholder="бүгд"
          value={provider ?? ''}
          data-testid="decisions-provider"
          onChange={(e) => setProvider(e.currentTarget.value || null)}
        />
      </Group>

      {rows.length === 0 ? (
        <Alert color="gray" data-testid="decisions-empty">
          Энэ шүүлтэд тохирох шийдвэр алга.
        </Alert>
      ) : null}

      <Accordion variant="separated" data-testid="decisions-feed">
        {rows.map((row) => (
          <Accordion.Item key={row.id} value={row.id}>
            <Accordion.Control data-testid="decision-row" data-id={row.id}>
              <Group justify="space-between" pr="md">
                <Group gap="sm">
                  <Text fw={600}>{row.proposal.symbol}</Text>
                  <Badge color={row.proposal.side === 'buy' ? 'green' : 'orange'} variant="light">
                    {row.proposal.side}
                  </Badge>
                  <Text size="sm">{formatQuantity(row.proposal.qty)} ш</Text>
                  <Badge color={OUTCOME_COLOR[row.outcome] ?? 'gray'} data-testid="decision-outcome">
                    {row.outcome}
                  </Badge>
                </Group>
                <Group gap="sm">
                  <Text size="xs" c="dimmed">
                    {row.provider} / {row.model}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {formatUtc(row.created_at)}
                  </Text>
                </Group>
              </Group>
            </Accordion.Control>
            <Accordion.Panel>
              <DecisionDetail decision={row} />
            </Accordion.Panel>
          </Accordion.Item>
        ))}
      </Accordion>
    </Stack>
  );
}

function DecisionDetail({ decision }: { decision: AgentDecision }) {
  const { data, isLoading } = useQuery({
    queryKey: ['decision', decision.id],
    queryFn: () => api.decision(decision.id),
  });

  return (
    <Stack gap="sm">
      <Card withBorder padding="sm">
        <Text size="sm" fw={600} mb={4}>
          Үндэслэл
        </Text>
        <Text size="sm" data-testid="decision-rationale">
          {decision.proposal.rationale}
        </Text>
        {decision.proposal.estimated_notional ? (
          <Text size="xs" c="dimmed" mt={4}>
            Тооцоолсон notional: {formatMoney(decision.proposal.estimated_notional)}
          </Text>
        ) : null}
      </Card>

      {decision.grounding ? (
        <Alert
          color={decision.grounding.passed ? 'green' : 'orange'}
          data-testid="decision-grounding"
        >
          <Text size="sm" fw={600}>
            Үндэслэлийн шалгалт: {decision.grounding.passed ? 'дамжсан' : 'УНАСАН'}
          </Text>
          {(decision.grounding.unverified_claims ?? []).length > 0 ? (
            <Text size="sm">
              Цитат өгөгдөлд ОЛДООГҮЙ тоо:{' '}
              {(decision.grounding.unverified_claims ?? []).join(', ')}
            </Text>
          ) : null}
        </Alert>
      ) : null}

      <Card withBorder padding="sm">
        <Text size="sm" fw={600} mb="xs">
          Иш татсан tool call — ТҮҮХИЙ payload
        </Text>
        {isLoading ? <Loader size="sm" /> : null}
        <Table data-testid="tool-calls-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Tool</Table.Th>
              <Table.Th>Цаг</Table.Th>
              <Table.Th>Хүсэлт / хариу</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(data?.tool_calls ?? []).map((call) => (
              <Table.Tr key={call.id} data-testid="tool-call-row">
                <Table.Td>
                  <Text size="sm" fw={600}>
                    {call.tool_name}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {call.source}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="xs">{formatUtc(call.called_at)}</Text>
                  <Text size="xs" c="dimmed">
                    {call.latency_ms ?? '—'} ms
                  </Text>
                </Table.Td>
                <Table.Td>
                  <ScrollArea.Autosize mah={220}>
                    <Code block data-testid="tool-call-payload">
                      {JSON.stringify({ request: call.request, response: call.response }, null, 2)}
                    </Code>
                  </ScrollArea.Autosize>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  );
}
