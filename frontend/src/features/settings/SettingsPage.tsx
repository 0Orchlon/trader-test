/**
 * Settings (T-35, LLD §16.6, AC-24).
 *
 * **READ ONLY.** §7's limits are policy (P-2) — an editable UI would go
 * around SPEC_APPROVE's gate. Changes go through `.env` + deploy.
 *
 * An API key NEVER reaches here: the backend only reports a reference
 * (`key_ref`) and whether it's reachable (NFR-3).
 */
import { Alert, Badge, Card, Group, Loader, Stack, Table, Text, Title } from '@mantine/core';
import { IconKey, IconLock, IconPlugConnected, IconToggleRight } from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';

import { api, type Source } from '@/lib/api';
import { useSystemState } from '@/hooks/useSystemState';
import { MODE_STYLES } from '@/app/ModeBanner';

// Same hue mapping as ModeBanner's gradients — the badge here is just a
// quieter, static echo of it, not a new color story.
const MODE_BADGE_COLOR: Record<Source, string> = {
  alpaca_paper: 'blue',
  alpaca_live: 'red',
  backtest: 'gray',
};

export function SettingsPage() {
  const { data: health, isLoading } = useQuery({ queryKey: ['health'], queryFn: api.health });
  const { data: system } = useSystemState();

  if (isLoading) return <Loader data-testid="settings-loading" />;

  const dependencies = [health?.broker, health?.database, health?.redis, ...(health?.providers ?? [])];

  return (
    <Stack gap="md">
      <Title order={3}>Settings</Title>

      <Alert color="blue" icon={<IconLock size={18} />} data-testid="settings-readonly">
        This screen is READ ONLY. Risk limits are policy — changing them goes through
        `.env` + deploy + code review. No editable fields exist here by design.
      </Alert>

      <Card withBorder padding="md">
        <Group gap="xs" mb="sm">
          <IconToggleRight size={16} color="var(--mantine-color-dimmed)" />
          <Text fw={600} tt="uppercase" fz="xs" style={{ letterSpacing: '0.03em' }} c="dimmed">
            Mode
          </Text>
        </Group>
        <Group gap="sm">
          <Badge size="lg" variant="light" color={system?.source ? MODE_BADGE_COLOR[system.source] : 'gray'} data-testid="settings-mode">
            {system?.source ? MODE_STYLES[system.source].label : 'unknown'}
          </Badge>
          <Text size="sm" c="dimmed">
            System state: {system?.state ?? '—'}
          </Text>
        </Group>
      </Card>

      <Card withBorder padding="md">
        <Group gap="xs" mb="sm">
          <IconPlugConnected size={16} color="var(--mantine-color-dimmed)" />
          <Text fw={600} tt="uppercase" fz="xs" style={{ letterSpacing: '0.03em' }} c="dimmed">
            Dependency status
          </Text>
        </Group>
        <Table data-testid="settings-dependencies">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Dependency</Table.Th>
              <Table.Th>Reachable</Table.Th>
              <Table.Th>Detail</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {dependencies
              .filter((d): d is NonNullable<typeof d> => Boolean(d))
              .map((dependency) => (
                <Table.Tr key={dependency.name} data-testid="dependency-row">
                  <Table.Td fw={600}>{dependency.name}</Table.Td>
                  <Table.Td>
                    <Badge color={dependency.reachable ? 'green' : 'red'} variant="light">
                      {dependency.reachable ? 'reachable' : 'unreachable'}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {dependency.detail ?? '—'}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ))}
          </Table.Tbody>
        </Table>
      </Card>

      <Card withBorder padding="md">
        <Group gap="xs" mb="sm">
          <IconKey size={16} color="var(--mantine-color-dimmed)" />
          <Text fw={600} tt="uppercase" fz="xs" style={{ letterSpacing: '0.03em' }} c="dimmed">
            API keys
          </Text>
        </Group>
        <Text size="sm" c="dimmed" data-testid="settings-keys">
          Keys are stored in a secrets manager. The backend only knows a REFERENCE;
          the key value NEVER reaches the API, logs, or this screen.
        </Text>
      </Card>
    </Stack>
  );
}
