/** Route-ын тодорхойлолт (LLD §16.1). Найман дэлгэц, нэг shell. */
import type { RouteObject } from 'react-router-dom';

import { AppShell } from './AppShell';
import { ApprovalsPage } from '@/features/approvals/ApprovalsPage';
import { AttributionPage } from '@/features/attribution/AttributionPage';
import { DashboardPage } from '@/features/dashboard/DashboardPage';
import { DecisionsPage } from '@/features/decisions/DecisionsPage';
import { ManualTicketPage } from '@/features/manualTicket/ManualTicketPage';
import { ProvidersPage } from '@/features/providers/ProvidersPage';
import { SettingsPage } from '@/features/settings/SettingsPage';
import { TuningPage } from '@/features/tuning/TuningPage';

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'attribution', element: <AttributionPage /> },
      { path: 'ticket', element: <ManualTicketPage /> },
      { path: 'approvals', element: <ApprovalsPage /> },
      { path: 'decisions', element: <DecisionsPage /> },
      { path: 'decisions/:decisionId', element: <DecisionsPage /> },
      { path: 'providers', element: <ProvidersPage /> },
      { path: 'tuning', element: <TuningPage /> },
      { path: 'settings', element: <SettingsPage /> },
    ],
  },
];
