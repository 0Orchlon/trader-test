/**
 * REST клиент. Төрлүүд нь `api.generated.ts`-ээс — **гараар бичсэн төрөл
 * БАЙХГҮЙ** (LLD §16.1). Гэрээ зөрвөл `tsc` унана.
 *
 * Алдааг ЗАЛГИХГҮЙ: `Problem` биетэй алдааг `ApiError` болгож дамжуулна,
 * ингэснээр UI нь `code`-оор салаална (жишээ: `confirmation_required` нь
 * алдаа биш, урсгалын алхам).
 */
import type { components, paths } from './api.generated';

export type Schemas = components['schemas'];
export type Problem = Schemas['Problem'];
export type SystemStateEnvelope = Schemas['SystemStateEnvelope'];
export type AccountEnvelope = Schemas['AccountEnvelope'];
export type PositionsEnvelope = Schemas['PositionsEnvelope'];
export type OrdersEnvelope = Schemas['OrdersEnvelope'];
export type AttributionEnvelope = Schemas['AttributionEnvelope'];
export type ApprovalsEnvelope = Schemas['ApprovalsEnvelope'];
export type AgentDecisionsEnvelope = Schemas['AgentDecisionsEnvelope'];
export type AgentDecisionDetail = Schemas['AgentDecisionDetail'];
export type ProvidersEnvelope = Schemas['ProvidersEnvelope'];
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

  /** Хоёр шаттай баталгаажуулалтын сорилт (LLD §8.4). */
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
  method?: 'GET' | 'POST';
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
  positions: () => request<PositionsEnvelope>('/positions'),
  orders: (query = 'status=open') => request<OrdersEnvelope>(`/orders?${query}`),
  attribution: () => request<AttributionEnvelope>('/attribution'),
  approvals: (state = 'pending') => request<ApprovalsEnvelope>(`/approvals?state=${state}`),
  decisions: (query = '') => request<AgentDecisionsEnvelope>(`/agent-decisions?${query}`),
  decision: (id: string) => request<AgentDecisionDetail>(`/agent-decisions/${id}`),
  providers: () => request<ProvidersEnvelope>('/providers'),
  tuning: () => request<TuningEnvelope>('/tuning/parameters'),
  systemState: () => request<SystemStateEnvelope>('/system/state'),

  killSwitch: (reason: string) =>
    request<SystemStateEnvelope>('/kill-switch', { method: 'POST', body: { reason } }),
  windDown: (reason: string) =>
    request<SystemStateEnvelope>('/system/wind-down', { method: 'POST', body: { reason } }),
  activate: (confirmationToken?: string) =>
    request<SystemStateEnvelope>('/system/activate', {
      method: 'POST',
      body: confirmationToken ? { confirmation_token: confirmationToken } : {},
    }),

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
