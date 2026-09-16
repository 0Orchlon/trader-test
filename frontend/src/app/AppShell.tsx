/**
 * App shell (T-29, LLD §16.1).
 *
 * ```
 * AppShell
 *  ├─ ModeBanner       ← source   (PAPER / LIVE / BACKTEST)
 *  ├─ StateBar         ← state    (ACTIVE / WINDING_DOWN / HALTED)
 *  ├─ StalenessBanner  ← WS чимээгүй > 5s
 *  └─ <Outlet/>
 * ```
 *
 * Гурвуулаа БҮХ route дээр байна: дэлгэц солигдоход горим, төлөв, шинэлэг
 * байдал алга болох цонх БАЙХГҮЙ.
 */
import { Alert, AppShell as MantineShell, Group, NavLink, ScrollArea, Text } from '@mantine/core';
import {
  IconAlertTriangle,
  IconChartLine,
  IconClipboardCheck,
  IconCpu,
  IconListDetails,
  IconSettings,
  IconSlideshow,
  IconTargetArrow,
  IconUsersGroup,
} from '@tabler/icons-react';
import { NavLink as RouterNavLink, Outlet, useLocation } from 'react-router-dom';

import { ModeBanner } from './ModeBanner';
import { StateBar } from './StateBar';
import { useLiveSocket, useSystemState } from '@/hooks/useSystemState';
import { formatUtcTime } from '@/lib/money';

export const ROUTES = [
  { path: '/', label: 'Хяналтын самбар', icon: IconChartLine },
  { path: '/attribution', label: 'Хэн юунд арилжаа хийж байна', icon: IconUsersGroup },
  { path: '/ticket', label: 'Гарын арилжаа', icon: IconTargetArrow },
  { path: '/approvals', label: 'Зөвшөөрлийн дараалал', icon: IconClipboardCheck },
  { path: '/decisions', label: 'Шийдвэрийн лог', icon: IconListDetails },
  { path: '/providers', label: 'AI provider', icon: IconCpu },
  { path: '/tuning', label: 'Авто-тохируулга', icon: IconSlideshow },
  { path: '/settings', label: 'Тохиргоо', icon: IconSettings },
] as const;

export function AppShell() {
  const { data: state } = useSystemState();
  const { stale, lastSeen } = useLiveSocket();
  const location = useLocation();

  return (
    <MantineShell header={{ height: 96 }} navbar={{ width: 260, breakpoint: 'sm' }} padding="md">
      <MantineShell.Header>
        <ModeBanner source={state?.source} />
        <StateBar state={state} />
      </MantineShell.Header>

      <MantineShell.Navbar p="xs">
        <ScrollArea>
          {ROUTES.map(({ path, label, icon: Icon }) => (
            <NavLink
              key={path}
              component={RouterNavLink}
              to={path}
              label={label}
              leftSection={<Icon size={18} />}
              active={location.pathname === path}
            />
          ))}
        </ScrollArea>
      </MantineShell.Navbar>

      <MantineShell.Main>
        {stale ? <StalenessBanner lastSeen={lastSeen} /> : null}
        <Outlet />
      </MantineShell.Main>
    </MantineShell>
  );
}

/**
 * Staleness banner (AC-2, LLD §16.7).
 *
 * Хуучин өгөгдөл live мэт шошгогүй ХЭЗЭЭ Ч харагдахгүй. Banner дээр сүүлийн
 * шинэчлэлтийн UTC хугацаа — «хэр хуучин» гэдэг нь таамаг биш, тоо.
 */
export function StalenessBanner({ lastSeen }: { lastSeen: string | null }) {
  return (
    <Alert
      color="orange"
      icon={<IconAlertTriangle size={18} />}
      data-testid="staleness-banner"
      mb="md"
    >
      <Group gap="xs">
        <Text size="sm" fw={600}>
          Шууд урсгал чимээгүй байна — доорх өгөгдөл ХУУЧИН байж болно.
        </Text>
        <Text size="sm" c="dimmed">
          сүүлийн мессеж: {formatUtcTime(lastSeen)}
        </Text>
      </Group>
    </Alert>
  );
}
