/**
 * App shell (T-29, LLD §16.1).
 *
 * ```
 * AppShell
 *  ├─ ModeBanner       ← source   (PAPER / LIVE / BACKTEST)
 *  ├─ StateBar         ← state    (ACTIVE / WINDING_DOWN / HALTED)
 *  ├─ StalenessBanner  ← WS silent > 5s
 *  └─ <Outlet/>
 * ```
 *
 * All three appear on EVERY route: switching screens must never open a
 * window where mode, state, or freshness disappears.
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
import { formatLocalWithUtc } from '@/lib/money';

export const ROUTES = [
  { path: '/', label: 'Dashboard', icon: IconChartLine },
  { path: '/attribution', label: 'Who is trading what', icon: IconUsersGroup },
  { path: '/ticket', label: 'Manual order', icon: IconTargetArrow },
  { path: '/approvals', label: 'Approval queue', icon: IconClipboardCheck },
  { path: '/decisions', label: 'Decision log', icon: IconListDetails },
  { path: '/providers', label: 'AI provider', icon: IconCpu },
  { path: '/tuning', label: 'Auto-tuning', icon: IconSlideshow },
  { path: '/settings', label: 'Settings', icon: IconSettings },
] as const;

export function AppShell() {
  const { data: state } = useSystemState();
  const { stale, lastSeen } = useLiveSocket();
  const location = useLocation();

  return (
    <MantineShell header={{ height: 96 }} navbar={{ width: 260, breakpoint: 'sm' }} padding="md">
      <MantineShell.Header style={{ background: 'var(--mantine-color-dark-7)', border: 'none' }}>
        <ModeBanner source={state?.source} />
        <StateBar state={state} />
      </MantineShell.Header>

      <MantineShell.Navbar
        p="xs"
        style={{ background: 'var(--mantine-color-dark-8)', border: 'none' }}
      >
        <ScrollArea>
          {ROUTES.map(({ path, label, icon: Icon }) => {
            const active = location.pathname === path;
            return (
              <NavLink
                key={path}
                component={RouterNavLink}
                to={path}
                label={label}
                leftSection={<Icon size={18} />}
                active={active}
                style={
                  active
                    ? {
                        borderLeft: '3px solid var(--mantine-color-brand-5)',
                        background: 'var(--mantine-color-dark-6)',
                      }
                    : undefined
                }
              />
            );
          })}
        </ScrollArea>
      </MantineShell.Navbar>

      <MantineShell.Main style={{ background: 'var(--mantine-color-dark-9)' }}>
        {stale ? <StalenessBanner lastSeen={lastSeen} /> : null}
        <Outlet />
      </MantineShell.Main>
    </MantineShell>
  );
}

/**
 * Staleness banner (AC-2, LLD §16.7).
 *
 * Stale data must NEVER be shown labeled as live. The banner shows the
 * UTC time of the last update — "how stale" is a number, not a guess.
 */
export function StalenessBanner({ lastSeen }: { lastSeen: string | null }) {
  return (
    <Alert
      color="orange"
      icon={<IconAlertTriangle size={18} />}
      data-testid="staleness-banner"
      mb="sm"
    >
      <Group gap="xs">
        <Text size="sm" fw={600}>
          Live stream is silent — the data below may be STALE.
        </Text>
        <Text size="sm" c="dimmed">
          last message: {formatLocalWithUtc(lastSeen)}
        </Text>
      </Group>
    </Alert>
  );
}
