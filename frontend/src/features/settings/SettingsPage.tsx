/**
 * Settings (T-35, LLD §16.6, AC-24).
 *
 * **ЗӨВХӨН УНШИХ.** §7-ийн хязгаар бол бодлого (P-2) — UI-аас засах
 * боломж нь SPEC_APPROVE-ийн хаалгыг тойрно. Өөрчлөх нь `.env` + deploy.
 *
 * API key нь ХЭЗЭЭ Ч энд ирэхгүй: backend зөвхөн лавлагаа (`key_ref`) ба
 * хүрэх эсэхийг мэдээлнэ (NFR-3).
 */
import { Alert, Badge, Card, Group, Loader, Stack, Table, Text, Title } from '@mantine/core';
import { IconLock } from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { useSystemState } from '@/hooks/useSystemState';
import { MODE_STYLES } from '@/app/ModeBanner';

export function SettingsPage() {
  const { data: health, isLoading } = useQuery({ queryKey: ['health'], queryFn: api.health });
  const { data: system } = useSystemState();

  if (isLoading) return <Loader data-testid="settings-loading" />;

  const dependencies = [health?.broker, health?.database, health?.redis, ...(health?.providers ?? [])];

  return (
    <Stack gap="md">
      <Title order={3}>Тохиргоо</Title>

      <Alert color="blue" icon={<IconLock size={18} />} data-testid="settings-readonly">
        Энэ дэлгэц ЗӨВХӨН УНШИНА. Эрсдэлийн хязгаар бол бодлого — өөрчлөх нь `.env` +
        deploy + code review. UI-аас засах талбар зориудаар байхгүй.
      </Alert>

      <Card withBorder padding="md">
        <Text fw={600} mb="sm">
          Горим
        </Text>
        <Group gap="sm">
          <Badge size="lg" data-testid="settings-mode">
            {system?.source ? MODE_STYLES[system.source].label : 'тодорхойгүй'}
          </Badge>
          <Text size="sm" c="dimmed">
            Системийн төлөв: {system?.state ?? '—'}
          </Text>
        </Group>
      </Card>

      <Card withBorder padding="md">
        <Text fw={600} mb="sm">
          Хамаарлын байдал
        </Text>
        <Table data-testid="settings-dependencies">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Хамаарал</Table.Th>
              <Table.Th>Хүрэх эсэх</Table.Th>
              <Table.Th>Тайлбар</Table.Th>
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
                      {dependency.reachable ? 'хүрнэ' : 'хүрэхгүй'}
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
        <Text fw={600} mb="sm">
          API түлхүүр
        </Text>
        <Text size="sm" c="dimmed" data-testid="settings-keys">
          Түлхүүр нь secrets manager-т хадгалагдана. Backend нь зөвхөн ЛАВЛАГААГ мэднэ;
          түлхүүрийн утга API, лог, энэ дэлгэцэд ХЭЗЭЭ Ч ирэхгүй.
        </Text>
      </Card>
    </Stack>
  );
}
