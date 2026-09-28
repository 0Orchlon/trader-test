/**
 * REST client. Types come from `api.generated.ts` — **no hand-written
 * types** (LLD §16.1). If the contract drifts, `tsc` fails.
 *
 * Errors are never swallowed: a `Problem`-shaped error is re-thrown as
 * `ApiError`, so the UI can branch on `code` (e.g. `confirmation_required`
 * is a flow step, not an error).
 */
import type { components, paths } from './api.generated';

export type Schemas = components['schemas'];
export type Problem = Schemas['Problem'];
export type SystemStateEnvelope = Schemas['SystemStateEnvelope'];
export type AccountEnvelope = Schemas['AccountEnvelope'];
export type EquityHistoryEnvelope = Schemas['EquityHistoryEnvelope'];
export type BarsEnvelope = Schemas['BarsEnvelope'];
export type ResearchStatusEnvelope = Schemas['ResearchStatusEnvelope'];
export type ManualTakeProfitEnvelope = Schemas['ManualTakeProfitEnvelope'];
export type PositionsEnvelope = Schemas['PositionsEnvelope'];
export type QuoteEnvelope = Schemas['QuoteEnvelope'];
export type OrdersEnvelope = Schemas['OrdersEnvelope'];
export type AttributionEnvelope = Schemas['AttributionEnvelope'];
export type PerformanceEnvelope = Schemas['PerformanceEnvelope'];
export type ApprovalsEnvelope = Schemas['ApprovalsEnvelope'];
export type AgentDecisionsEnvelope = Schemas['AgentDecisionsEnvelope'];
export type AgentDecisionDetail = Schemas['AgentDecisionDetail'];
export type ProvidersEnvelope = Schemas['ProvidersEnvelope'];
export type CapitalSummaryEnvelope = Schemas['CapitalSummaryEnvelope'];
export type CapitalLimitsEnvelope = Schemas['CapitalLimitsEnvelope'];
export type ReconcileReportEnvelope = Schemas['ReconcileReportEnvelope'];
export type TuningEnvelope = Schemas['TuningEnvelope'];
export type OrderAccepted = Schemas['OrderAccepted'];
export type ManualOrderRequest = Schemas['ManualOrderRequest'];
export type Health = Schemas['Health'];
export type Source = Schemas['Source'];
export type SystemState = Schemas['SystemState'];
export type Origin = Schemas['Origin'];
export type Order = Schemas['Order'];
export type Position = Schemas['Position'];
export type RiskEvaluation = Schemas['RiskEvaluation'];
export type Approval = Schemas['Approval'];
export type AgentDecision = Schemas['AgentDecision'];

export type Paths = paths;

export const BASE = '/api/v1';

export class ApiError extends Error {
  readonly status: number;
  readonly problem: Problem | null;

  constructor(status: number, problem: Problem | null, fallback: string) {
    super(problem?.detail ?? problem?.title ?? fallback);
    this.status = status;
    this.problem = problem;
  }

  get code(): string | undefined {
    return this.problem?.code;
  }

  /** Two-step confirmation challenge (LLD §8.4). */
  get confirmation(): { token: string; prompt: string; expires_at: string } | undefined {
    return this.problem?.confirmation as
      | { token: string; prompt: string; expires_at: string }
      | undefined;
  }

  get risk(): RiskEvaluation | undefined {
    return this.problem?.risk;
  }
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT';
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
};

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: options.method ?? 'GET',
    headers: { 'Content-Type': 'application/json', ...(options.headers ?? {}) },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });

  const text = await response.text();
  const payload = text ? (JSON.parse(text) as unknown) : null;

  if (!response.ok) {
    throw new ApiError(response.status, payload as Problem | null, response.statusText);
  }
  return payload as T;
}

export const api = {
  health: () => request<Health>('/health'),
  account: () => request<AccountEnvelope>('/account'),
  equityHistory: (minutes = 240) =>
    request<EquityHistoryEnvelope>(`/equity/history?minutes=${minutes}`),
  positions: () => request<PositionsEnvelope>('/positions'),
  orders: (query = 'status=open') => request<OrdersEnvelope>(`/orders?${query}`),
  attribution: () => request<AttributionEnvelope>('/attribution'),
  performance: () => request<PerformanceEnvelope>('/performance'),
  quote: (symbol: string) => request<QuoteEnvelope>(`/market/quote/${encodeURIComponent(symbol)}`),
  bars: (symbol: string, timeframe = '5Min', minutes = 240) =>
    request<BarsEnvelope>(
      `/market/bars/${encodeURIComponent(symbol)}?timeframe=${timeframe}&minutes=${minutes}`,
    ),
  approvals: (state = 'pending') => request<ApprovalsEnvelope>(`/approvals?state=${state}`),
  decisions: (query = '') => request<AgentDecisionsEnvelope>(`/agent-decisions?${query}`),
  decision: (id: string) => request<AgentDecisionDetail>(`/agent-decisions/${id}`),
  providers: () => request<ProvidersEnvelope>('/providers'),
  tuning: () => request<TuningEnvelope>('/tuning/parameters'),
  systemState: () => request<SystemStateEnvelope>('/system/state'),
  researchStatus: () => request<ResearchStatusEnvelope>('/research/status'),
  capitalSummary: () => request<CapitalSummaryEnvelope>('/capital/summary'),
  capitalLimits: () => request<CapitalLimitsEnvelope>('/capital/limits'),
  runResearchNow: () => request<unknown>('/research/run-now', { method: 'POST' }),
  setResearchWatchlist: (symbols: string[]) =>
    request<unknown>('/research/watchlist', { method: 'PUT', body: { symbols } }),

  manualTakeProfit: () => request<ManualTakeProfitEnvelope>('/manual-take-profit'),
  setManualTakeProfit: (enabled: boolean) =>
    request<ManualTakeProfitEnvelope>('/manual-take-profit', {
      method: 'PUT',
      body: { enabled },
    }),

  killSwitch: (reason: string) =>
    request<SystemStateEnvelope>('/kill-switch', { method: 'POST', body: { reason } }),
  windDown: (reason: string) =>
    request<SystemStateEnvelope>('/system/wind-down', { method: 'POST', body: { reason } }),
  activate: (confirmationToken?: string) =>
    request<SystemStateEnvelope>('/system/activate', {
      method: 'POST',
      body: confirmationToken ? { confirmation_token: confirmationToken } : {},
    }),
  reconcileNow: () =>
    request<ReconcileReportEnvelope>('/system/reconcile-now', { method: 'POST' }),

  manualOrder: (body: ManualOrderRequest, idempotencyKey: string) =>
    request<OrderAccepted>('/orders/manual', {
      method: 'POST',
      body,
      headers: { 'Idempotency-Key': idempotencyKey },
    }),
  cancelOrder: (orderId: string) =>
    request<unknown>(`/orders/${orderId}/cancel`, { method: 'POST' }),

  approve: (id: string, expectedVersion: number, note?: string) =>
    request<OrderAccepted>(`/approvals/${id}/approve`, {
      method: 'POST',
      body: { expected_version: expectedVersion, note },
    }),
  reject: (id: string, expectedVersion: number, reason: string) =>
    request<unknown>(`/approvals/${id}/reject`, {
      method: 'POST',
      body: { expected_version: expectedVersion, reason },
    }),

  switchProvider: (role: string, providerId: string) =>
    request<Schemas['ProviderSwitchResult']>(`/providers/${role}/switch`, {
      method: 'POST',
      body: { provider_id: providerId },
    }),
  promoteTuning: (ids: string[], confirmationToken?: string) =>
    request<unknown>('/tuning/promote', {
      method: 'POST',
      body: {
        tuning_history_ids: ids,
        ...(confirmationToken ? { confirmation_token: confirmationToken } : {}),
      },
    }),
};
