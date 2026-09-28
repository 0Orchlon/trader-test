/**
 * Agent Activity Log (T-32, LLD §16.6, AC-7, AC-8).
 *
 * Every row expands into the **RAW tool call payload**. No summarizing:
 * the answer to "why did the AI say this" is DATA, not a conclusion.
 * Summarizing would leave the operator no choice but to trust the model.
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
import { formatLocalDateTimeWithUtc, formatMoney, formatQuantity } from '@/lib/money';
import { distinctSources } from '@/lib/source';
import { Num } from '@/components/Num';

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
      <Title order={3}>Decision log</Title>

      <Card withBorder padding="sm" bg="dark.7">
        <Group>
          <TextInput
            label="Symbol"
            placeholder="all"
            value={symbol}
            data-testid="decisions-symbol"
            onChange={(e) => {
              const next = e.currentTarget.value.toUpperCase();
              setParams(next ? { symbol: next } : {});
            }}
          />
          <Select
            label="Outcome"
            placeholder="all"
            clearable
            data={Object.keys(OUTCOME_COLOR)}
            value={outcome}
            data-testid="decisions-outcome"
            onChange={setOutcome}
          />
          <TextInput
            label="Provider"
            placeholder="all"
            value={provider ?? ''}
            data-testid="decisions-provider"
            onChange={(e) => setProvider(e.currentTarget.value || null)}
          />
        </Group>
      </Card>

      {rows.length === 0 ? (
        <Alert color="gray" data-testid="decisions-empty">
          No decisions match this filter.
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
                  <Text size="sm">
                    <Num span size="sm">
                      {formatQuantity(row.proposal.qty)}
                    </Num>{' '}
                    shares
                  </Text>
                  <Badge color={OUTCOME_COLOR[row.outcome] ?? 'gray'} data-testid="decision-outcome">
                    {row.outcome}
                  </Badge>
                </Group>
                <Group gap="sm">
                  <Text size="xs" c="dimmed">
                    {row.provider} / {row.model}
                  </Text>
                  <Num span size="xs" c="dimmed">
                    {formatLocalDateTimeWithUtc(row.created_at)}
                  </Num>
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
  // One table = one source (N-5). Don't repeat the label per row: repetition
  // hides a mix — the eye won't catch the difference.
  const sources = distinctSources((data?.tool_calls ?? []).map((call) => call.source));

  return (
    <Stack gap="sm">
      <Card withBorder padding="sm">
        <Text size="sm" fw={600} mb={4}>
          Rationale
        </Text>
        <Text size="sm" data-testid="decision-rationale">
          {decision.proposal.rationale}
        </Text>
        {decision.proposal.estimated_notional ? (
          <Text size="xs" c="dimmed" mt={4}>
            Estimated notional:{' '}
            <Num span size="xs" c="dimmed">
              {formatMoney(decision.proposal.estimated_notional)}
            </Num>
          </Text>
        ) : null}
      </Card>

      {decision.grounding ? (
        <Alert
          color={decision.grounding.not_run ? 'gray' : decision.grounding.passed ? 'green' : 'orange'}
          data-testid="decision-grounding"
        >
          <Text size="sm" fw={600}>
            Grounding check:{' '}
            {/* "Not run" is NOT the same as "failed" — calling both by
                the same word makes an unchecked claim look checked (appendix 10). */}
            {decision.grounding.not_run
              ? 'not run (proposal rejected earlier)'
              : decision.grounding.passed
                ? 'passed'
                : 'FAILED'}
          </Text>
          {/* The actual COUNT of claims checked. "0 claims checked" and
              "12 claims checked" looking identically green would make an
              unchecked claim look checked (N-4). */}
          {decision.grounding.not_run ? null : (
            <Text size="xs" c="dimmed" data-testid="grounding-checked-claims">
              {decision.grounding.checked_claims ?? 0} claims checked
            </Text>
          )}
          {(decision.grounding.unverified_claims ?? []).length > 0 ? (
            <Text size="sm">
              Claims NOT found in cited evidence:{' '}
              {(decision.grounding.unverified_claims ?? []).join(', ')}
            </Text>
          ) : null}
        </Alert>
      ) : null}

      <Card withBorder padding="sm">
        <Group justify="space-between" mb="xs">
          <Text size="sm" fw={600}>
            Cited tool calls — RAW payload
          </Text>
          {sources.length === 1 ? (
            <Badge variant="light" color="gray" data-testid="tool-calls-source">
              {sources[0]}
            </Badge>
          ) : null}
        </Group>
        {isLoading ? <Loader size="sm" /> : null}
        {sources.length > 1 ? (
          <Alert color="red" data-testid="mixed-source">
            This table has a MIXED source ({sources.join(', ')}) — which one is
            real data is ambiguous, so it isn't shown (LLD §16.2).
          </Alert>
        ) : (
        <Table data-testid="tool-calls-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Tool</Table.Th>
              <Table.Th>Time</Table.Th>
              <Table.Th>Request / response</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(data?.tool_calls ?? []).map((call) => (
              <Table.Tr key={call.id} data-testid="tool-call-row">
                <Table.Td>
                  <Text size="sm" fw={600}>
                    {call.tool_name}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Num size="xs">{formatLocalDateTimeWithUtc(call.called_at)}</Num>
                  <Num size="xs" c="dimmed">
                    {call.latency_ms ?? '—'} ms
                  </Num>
                </Table.Td>
                <Table.Td>
                  <ScrollArea.Autosize mah={220}>
                    <Code block fz="sm" data-testid="tool-call-payload">
                      {JSON.stringify({ request: call.request, response: call.response }, null, 2)}
                    </Code>
                  </ScrollArea.Autosize>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        )}
      </Card>
    </Stack>
  );
}
