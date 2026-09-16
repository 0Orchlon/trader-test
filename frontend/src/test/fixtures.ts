/**
 * Тестийн өгөгдөл — `contracts/openapi.yaml`-ийн жишээнүүдтэй нийцсэн.
 *
 * Мөнгө нь fixed-point тэмдэгт мөр, timestamp нь UTC `Z`, позиц бүр
 * `origin`-той: тест нь гэрээний хэлбэрээс гажуудвал дэлгэц нь бодит
 * backend-тэй ажиллахгүй.
 */
import type {
  AccountEnvelope,
  ApprovalsEnvelope,
  AttributionEnvelope,
  Health,
  OrdersEnvelope,
  PositionsEnvelope,
  ProvidersEnvelope,
  SystemStateEnvelope,
  TuningEnvelope,
} from '@/lib/api';

const ENVELOPE = {
  source: 'alpaca_paper',
  as_of: '2026-09-16T14:30:00Z',
  stale: false,
  system_state: 'active',
} as const;

export const systemState: SystemStateEnvelope = {
  ...ENVELOPE,
  state: 'active',
  reason: null,
  changed_at: '2026-09-16T09:00:00Z',
  changed_by: 'operator',
  wind_down_deadline: null,
  seconds_remaining: null,
  breaker_metrics: [
    {
      metric: 'daily_loss',
      value: '-312.44',
      limit_name: 'DAILY_LOSS_LIMIT',
      limit_value: '-2000.00',
      tripped: false,
    },
  ],
};

export const haltedState: SystemStateEnvelope = {
  ...systemState,
  system_state: 'halted',
  state: 'halted',
  reason: 'Өдрийн алдагдлын хязгаар давсан',
  changed_by: 'circuit_breaker',
};

export const windingDownState: SystemStateEnvelope = {
  ...systemState,
  system_state: 'winding_down',
  state: 'winding_down',
  reason: 'Operator: удахгүй унтраана',
  wind_down_deadline: '2026-09-16T14:45:00Z',
  seconds_remaining: 754,
};

export const liveState: SystemStateEnvelope = {
  ...systemState,
  source: 'alpaca_live',
};

export const account: AccountEnvelope = {
  ...ENVELOPE,
  account: {
    account_id: 'PA3X9QK2TLZ0',
    equity: '104238.17',
    cash: '38210.55',
    buying_power: '76421.10',
    last_equity: '103980.44',
    pattern_day_trader: false,
    day_trade_count: 1,
    trading_blocked: false,
  },
};

export const positions: PositionsEnvelope = {
  ...ENVELOPE,
  positions: [
    {
      symbol: 'AAPL',
      qty: '40',
      side: 'long',
      avg_entry_price: '221.40',
      market_value: '9012.00',
      unrealized_pl: '156.00',
      origin: 'research_agent',
      origin_detail: 'claude-mcp/claude-opus-5',
    },
    {
      symbol: 'TSLA',
      qty: '5',
      side: 'long',
      avg_entry_price: '248.90',
      market_value: '1252.50',
      unrealized_pl: '8.00',
      origin: 'external',
      origin_detail: null,
    },
  ],
};

export const orders: OrdersEnvelope = {
  ...ENVELOPE,
  orders: [
    {
      id: '9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d',
      broker_order_id: null,
      client_order_id: 'p3-9a8b7c6d',
      symbol: 'MSFT',
      side: 'sell',
      qty: '12',
      filled_qty: '0',
      order_type: 'market',
      time_in_force: 'day',
      status: 'accepted',
      origin: 'manual_operator',
      origin_detail: 'operator',
      decision_id: null,
      submitted_at: '2026-09-16T14:29:51Z',
    },
  ],
};

export const attribution: AttributionEnvelope = {
  ...ENVELOPE,
  groups: [
    {
      origin: 'research_agent',
      origin_detail: 'claude-mcp/claude-opus-5',
      symbols: [
        {
          symbol: 'AAPL',
          has_open_position: true,
          position_qty: '40',
          market_value: '9012.00',
          open_order_count: 0,
          last_decision_at: '2026-09-16T13:55:02Z',
          last_decision_id: '3c9d8e7f-6a5b-4c3d-8e1f-0a9b8c7d6e5f',
        },
      ],
    },
    {
      origin: 'external',
      origin_detail: null,
      symbols: [
        {
          symbol: 'TSLA',
          has_open_position: true,
          position_qty: '5',
          market_value: '1252.50',
          open_order_count: 0,
          last_decision_at: null,
          last_decision_id: null,
        },
      ],
    },
  ],
};

export const approvals: ApprovalsEnvelope = {
  ...ENVELOPE,
  approvals: [
    {
      id: '2d3e4f50-6172-4839-a0b1-c2d3e4f50617',
      version: 1,
      state: 'pending',
      decision_id: '3c9d8e7f-6a5b-4c3d-8e1f-0a9b8c7d6e5f',
      proposed_order: {
        symbol: 'NVDA',
        side: 'buy',
        qty: '25',
        order_type: 'limit',
        limit_price: '402.00',
        estimated_notional: '10050.00',
        rationale: '20/50 EMA огтлолцол + эзлэхүүн 1.8 дахин их.',
        grounded_in: ['11111111-2222-4333-8444-555555555555'],
        provider: 'claude-mcp',
        model: 'claude-opus-5',
      },
      risk: {
        decision: 'ESCALATE_TO_HUMAN',
        reason: 'Notional 10050.00 > MAX_ORDER_NOTIONAL 5000.00',
        evaluated_at: '2026-09-16T14:22:10Z',
        checks: [
          {
            rule: 'order_notional',
            passed: false,
            limit_name: 'MAX_ORDER_NOTIONAL',
            limit_value: '5000.00',
            actual_value: '10050.00',
          },
        ],
      },
      created_at: '2026-09-16T14:22:10Z',
      expires_at: '2026-09-16T14:37:10Z',
      resolved_at: null,
      resolution_reason: null,
    },
  ],
};

export const providers: ProvidersEnvelope = {
  ...ENVELOPE,
  providers: [
    {
      id: 'claude-mcp',
      vendor: 'anthropic',
      model: 'claude-opus-5',
      transport: 'mcp',
      healthy: true,
      read_only: false,
      last_error: null,
    },
    {
      id: 'openai-fc',
      vendor: 'openai',
      model: 'gpt-5',
      transport: 'function_calling',
      healthy: true,
      read_only: false,
      last_error: null,
    },
    {
      id: 'local-fallback',
      vendor: 'local',
      model: 'llama-3.1-70b',
      transport: 'stdio_json',
      healthy: true,
      read_only: true,
      last_error: null,
    },
  ],
  active: { research: 'claude-mcp' },
};

export const tuning: TuningEnvelope = {
  ...ENVELOPE,
  parameters: [
    {
      name: 'STOP_LOSS_PCT',
      current_value: '2.5',
      bounds: { min: '1.0', max: '5.0', step: '0.1' },
      applies_to: 'paper',
      history: [
        {
          id: 'aaaabbbb-cccc-4ddd-8eee-ffff00001111',
          old_value: '2.4',
          new_value: '2.5',
          changed_at: '2026-09-15T21:05:00Z',
          approved_by: 'system',
          walk_forward: {
            folds: 6,
            in_sample_metric: 'sharpe=1.31',
            out_of_sample_metric: 'sharpe=1.08',
          },
        },
      ],
    },
  ],
};

export const health: Health = {
  ...ENVELOPE,
  status: 'ok',
  broker: { name: 'alpaca_paper', reachable: true },
  database: { name: 'postgres', reachable: true },
  redis: { name: 'redis', reachable: false, detail: 'тохируулаагүй' },
  providers: [{ name: 'claude-mcp', reachable: true }],
};
