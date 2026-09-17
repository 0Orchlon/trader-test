<!-- PERSONAL-3 · lld · DESIGN · 2026-09-16 -->

# PERSONAL-3 — Alpaca худалдааны системийн нарийвчилсан загвар (LLD v1.0)

**Ажил:** PERSONAL-3 · **Салбар:** `issue/personal-3` · **Шат:** DESIGN
**Оролт:** `spec.md` v1.1 (SPEC), `plan.md` v1.1, `tasks.md` v1.1 (T-01…T-52),
Hefesto хавсралт id=42…52
**Хамт гарсан баримт:** `contracts.yaml` (OpenAPI 3.1 + AsyncAPI 3.0 + Tool
Contract v1), `lld.html` (дэлгэцийн дуурайлт)
**Дараагийн гарц:** LLD_APPROVE → IMPLEMENT

---

## 0. Энэ баримтын хамрах хүрээ ба хилийн заалт

Энэ бол **DESIGN** шатны гарц: спекийн ЮУ-г **ХЭРХЭН** барихыг тогтооно —
модулийн хил, өгөгдлийн загвар, төлөвийн машин, алгоритм, дэлгэцийн бүтэц.

**Энд БАЙХГҮЙ (зориудаар):**

| Байхгүй зүйл | Хаана байгаа |
|---|---|
| Шаардлага, AC | `spec.md` v1.1 |
| Milestone, дараалал, эрсдэл | `plan.md` v1.1 |
| Task-ийн задаргаа, DoD | `tasks.md` v1.1 (T-01…T-52) |
| Гэрээний бодит схем | `contracts.yaml` |
| §7-ийн 10 хязгаарын ТООН утга | SPEC_APPROVE-ийн гарц. Энэ загвар тоог **нэрээр** иш татна. |

> **Хяналтын загварын гэрээ:** энэ баримтад бичигдсэн зүйлийг шалгана,
> бичигдээгүй зүйлээр кодыг буруутгахгүй. Кодын хяналт (CODE_REVIEW) нь
> §19-ийн «шалгах боломжтой цэгүүд»-ийн жагсаалтыг ашиглана.

### 0.1 Хяналтын саналын хучилт (энэ шат юуг нэмэв)

Хянагчийн буцаасан гурван шаардлага нь SPEC v1.1-д OP-11/12/13 болж орсон.
Энэ LLD дотор тэдгээр нь дараах бүлгүүдээр загварчлагдав:

| Хянагчийн үг | OP | LLD бүлэг |
|---|---|---|
| «AI эсвэл алгоритм юунд арилжаа хийж байгааг frontend дээр харах» | OP-11 | §5.2 `orders.origin`, §11 Attribution resolver, §16.4 «Хэн юунд» дэлгэц |
| «Frontend-ээс өөрөө гараар арилжаа хийх» | OP-12 | §9.3 гарын order-ийн урсгал, §16.5 Ticket UI, §8.4 хоёр шаттай баталгаажуулалт |
| «Унтраана гэж AI-д мэдэгдэх товч → ашгаа түргэн авч зогсоно → идэвхжүүл товч дартал зогссон» | OP-13 | §6 төлөвийн машин, §8.2 wind-down дүрэм, §12.4 tool result-ийн `system_state`, §16.6 төлөвийн самбар |

---

## 1. Загварын үл хөдлөх зарчим (энэ баримтын бүх шийдвэрийн үндэс)

`plan.md` §2-ийн зургаан зарчмыг загварын хэл рүү буулгав. Тэдгээр нь энд
**бүтцийн шинж** болж хатуурна — сахилга биш, хэлбэр.

| # | Зарчим | Загварын илэрхийлэл |
|---|---|---|
| P-1 | LLM-ээс Alpaca-ийн submit хүрэх зам БАЙХГҮЙ | `BrokerPort.submit_order`-ийг дуудах эрх зөвхөн `execution` package-д. Import-graph тест (§18.2) энэ хилийг барина. |
| P-2 | Хязгаар нь бодлого, код БИШ | `RiskLimits` нь `frozen` dataclass, зөвхөн `Settings`-ээс. Кодод анхдагч утга БАЙХГҮЙ — дутуу бол `startup` унана. |
| P-3 | Live анхдагч болох зам БАЙХГҮЙ | `TradingMode` нь `resolve_mode()`-ийн цорын ганц гаралт; `live` болох нөхцөл нь гурван ил дохионы БҮГД (§17.2). |
| P-4 | Тоо бүр гарал үүсэлтэй | `Envelope` (source + as_of + stale) бүх гаралтын заавал хэсэг; `Money = Decimal`; `Instant = datetime(tz=UTC)`. |
| P-5 | Order бүр эзэнтэй | `orders.origin NOT NULL`, анхдагчгүй. Position-ийн origin = `client_order_id`-ийн ТААРАЛТ, таамаг биш. |
| P-6 | Зогссон төлөв наалдамхай | Төлөв Postgres-д, Redis-д БИШ. Startup нь хадгалагдсан төлвийг УНШИНА, эхлүүлэхгүй. |

---

## 2. Бүрэлдэхүүн ба урсгалын зураг

```
┌──────────────────────────── frontend/ (React + TS + Vite) ─────────────────────────────┐
│  AppShell (горим + төлөвийн байнгын заалт)                                              │
│  Dashboard · Attribution · ManualTicket · ApprovalQueue · DecisionLog                    │
│  ProviderSwitcher · TuningPanel · Settings                                               │
│  useSystemState() ──┐   TanStack Query (REST)   ┌── useLiveSocket() (нэг WS холболт)     │
└─────────────────────┼───────────────────────────┼───────────────────────────────────────┘
                      │ REST /api/v1              │ WS /ws
┌─────────────────────▼───────────────────────────▼───────────────────────────────────────┐
│ backend/app/api/          FastAPI router-ууд — ЗӨВХӨН orchestration, дүрэм байхгүй        │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│ backend/app/system/       StateMachine · KillSwitch · CircuitBreaker · Confirmation       │
│ backend/app/risk/         RiskAgent (цэвэр функц, LLM БИШ)      ◄── ганц хаалга           │
│ backend/app/execution/    ExecutionAgent — submit_order-ийн ЦОРЫН ГАНЦ дуудагч            │
│ backend/app/approvals/    ApprovalQueue + TTL reaper                                      │
│ backend/app/agents/       Gateway · ToolHandlers · GroundingChecker · ProviderRouter      │
│ backend/app/broker/       BrokerPort (Protocol) · AlpacaAdapter · Reconciler              │
│ backend/app/audit/        HashChainWriter · Verifier · Redactor                           │
│ backend/app/tuning/       BoundedSearch · WalkForward · PromoteGate                       │
│ backend/app/stream/       RedisFanout · WsHub                                             │
│ backend/app/config/       Settings · resolve_mode() · LiveEgressGuard                     │
└───────┬────────────────────────────────┬──────────────────────────────┬──────────────────┘
        │                                │                              │
   ┌────▼─────┐                  ┌───────▼────────┐            ┌────────▼─────────┐
   │ Postgres │                  │ Redis pub/sub  │            │ Alpaca REST + WS │
   │ 10 хүсн. │                  │ (fan-out only) │            │ paper эсвэл live │
   └──────────┘                  └────────────────┘            └──────────────────┘
                                          ▲
                        ┌─────────────────┴──────────────────┐
                        │ Provider adapters (LLM, Research role)│
                        │ claude-mcp · openai-fc · xai-fc ·     │
                        │ opencode-stdio · local (read-only)     │
                        └────────────────────────────────────────┘
```

**Дээш чиглэсэн хамаарал БАЙХГҮЙ.** `risk` нь `api`-г мэдэхгүй; `agents` нь
`execution`-ыг мэдэхгүй; `broker` нь `risk`-ийг мэдэхгүй. Энэ нь гоо зүйн
дүрэм биш — P-1-ийг барих механизм (§18.2).

---

## 3. Репогийн бүтэц

```
backend/
  app/
    main.py                  FastAPI app factory, lifespan (startup gates)
    api/                     v1 router-ууд (contracts.yaml-ийн 1:1 тусгал)
      account.py  orders.py  attribution.py  approvals.py
      decisions.py  providers.py  tuning.py  system.py  health.py  ws.py
    config/
      settings.py            pydantic-settings; анхдагч утгагүй хязгаарууд
      mode.py                resolve_mode(), TradingMode
      egress.py              LiveEgressGuard (тестэд live host руу 0 дуудалт)
    broker/
      port.py                BrokerPort Protocol
      alpaca.py              AlpacaAdapter (ганц хэрэгжүүлэлт)
      models.py              Account, Position, Order, Tick, TradeUpdate
      reconcile.py           EOD reconciliation job
    risk/
      agent.py               evaluate(ctx, req) -> RiskEvaluation  [цэвэр функц]
      rules.py               дүрэм тус бүр нэг функц
      limits.py              RiskLimits (frozen)
    execution/
      agent.py               ЦОРЫН ГАНЦ submit_order дуудагч
      idempotency.py         client_order_id деривац
    approvals/
      queue.py  reaper.py
    agents/
      gateway.py             tool dispatch + envelope
      tools.py               Tool Contract v1 handler-ууд
      grounding.py           GroundingChecker
      router.py              ProviderRouter (hot-swap)
      adapters/              claude_mcp.py  openai_fc.py  xai_fc.py
                             opencode_stdio.py  local_readonly.py
    system/
      state.py               StateMachine (ACTIVE/WINDING_DOWN/HALTED)
      killswitch.py  breaker.py  confirmation.py
    audit/
      chain.py  verifier.py  redact.py
    tuning/
      search.py  walkforward.py  promote.py
    stream/
      fanout.py  hub.py
  migrations/                Alembic
  tests/
    unit/  property/  integration/  static/  adversarial/
  pyproject.toml  uv.lock
frontend/
  src/
    app/          AppShell.tsx  routes.tsx  ModeBanner.tsx  StateBar.tsx
    features/     dashboard/ attribution/ manualTicket/ approvals/
                  decisions/ providers/ tuning/ settings/
    lib/          api.ts (generated from contracts.yaml)  ws.ts  money.ts
    hooks/        useSystemState.ts  useLiveSocket.ts  useStaleness.ts
  tests/e2e/      Playwright
  package.json  package-lock.json
docs/PERSONAL-3/  spec.md  plan.md  tasks.md  lld.md  lld.html  contracts.yaml
.github/workflows/ci.yml    matrix: backend, frontend
```

> **netos-ийн хамаарал:** энэ репо netos template БИШ (`pom.xml`,
> `compliance.yaml`, `.gitlab-ci.yml` алга; GitHub репо; `gitlabProjectPath`
> байхгүй) — `spec.md` A-5, `plan.md` §1-ийн шийдвэрийг үргэлжлүүлэв. Тиймээс
> `java-service` / `bff-*` / `web-app` / `native-app` гадаргууны хэлбэр, netos
> parent pin, `rules/*.yaml` хаалга энд ХАМААРАХГҮЙ. Хэрэв OQ-4-т «netos
> template» гэж хариулбал §3 ба §18 дахин бичигдэнэ; §4–§17 хүчинтэй хэвээр.

---

## 4. Хөндлөн огтлолын төрлүүд

```python
# backend/app/broker/models.py — бүх давхаргын нийтлэг толь
Money   = Decimal            # ХЭЗЭЭ Ч float. JSON-д str(quantize(2))
Qty     = Decimal            # crypto-д бутархай
Instant = datetime           # tzinfo=UTC ЗААВАЛ; naive datetime нь алдаа

class Source(StrEnum):       ALPACA_LIVE; ALPACA_PAPER; BACKTEST
class SystemState(StrEnum):  ACTIVE; WINDING_DOWN; HALTED
class Origin(StrEnum):       RESEARCH_AGENT; AUTO_TUNING; MANUAL_OPERATOR; EXTERNAL
class RiskDecision(StrEnum): APPROVE; REJECT; ESCALATE_TO_HUMAN

@dataclass(frozen=True)
class Envelope[T]:
    data: T
    source: Source
    as_of: Instant
    stale: bool                 # ил False бичнэ, орхихгүй
    system_state: SystemState
```

**Money-ийн хилийн дүрэм (AC-25):**
`Decimal` нь DB (`NUMERIC(20,8)`) ↔ домэйн хооронд; API хил дээр
`str` (`quantize(Decimal("0.01"))`). `float(...)` нь мөнгөн замд lint-ээр
хоригдоно (§18.2 R-3). JSON parse нь `parse_float=Decimal`.

**Instant-ийн хилийн дүрэм (AC-26):** `timestamptz` баганууд; `datetime.now()`
хоригтой, зөвхөн `now_utc()` helper. Naive datetime нь `ValueError`.

---

## 5. Өгөгдлийн загвар (Postgres, 10 хүснэгт)

`tasks.md` T-02-ийн 7 хүснэгт + T-44-ийн `system_state` + `approvals` +
`confirmations`. Баганын жагсаалт нь **хамгийн бага хангалттай** олонлог —
хэрэггүй талбар нэмэхгүй.

### 5.1 `accounts`
| Багана | Төрөл | Тэмдэглэл |
|---|---|---|
| `id` | `uuid pk` | |
| `broker_account_id` | `text not null unique` | Alpaca-аас |
| `mode` | `text not null check (mode in ('paper','live'))` | |
| `key_ref` | `text not null` | Secrets manager-ийн ЛАВЛАГАА. Түлхүүр өөрөө ХЭЗЭЭ Ч энд орохгүй (NFR-3). |
| `created_at` | `timestamptz not null default now()` | |

### 5.2 `orders` — системийн гол хүснэгт
| Багана | Төрөл | Тэмдэглэл |
|---|---|---|
| `id` | `uuid pk` | |
| `client_order_id` | `text not null unique` | Idempotency-ийн ганц эх (§9.2) |
| `broker_order_id` | `text unique` | Alpaca-аас; илгээгдтэл `null` |
| `account_id` | `uuid not null fk accounts` | |
| `symbol` | `text not null` | |
| `side` | `text not null check in ('buy','sell')` | |
| `qty` | `numeric(20,8) not null check (qty > 0)` | |
| `order_type` | `text not null` | |
| `limit_price`, `stop_price` | `numeric(20,8)` | |
| `time_in_force` | `text not null` | |
| `status` | `text not null` | §9.1-ийн төлөвүүд |
| **`origin`** | **`text not null check in ('research_agent','auto_tuning','manual_operator','external')`** | **Анхдагч утга БАЙХГҮЙ** (AC-29, P-5) |
| `origin_detail` | `text` | provider/model эсвэл actor |
| `decision_id` | `uuid fk agent_decisions` | `manual_operator` үед `null` |
| `approval_id` | `uuid fk approvals` | Босгоос дээш үед |
| `risk_evaluation` | `jsonb not null` | Шалгалт бүрийн үр дүн, ил |
| `mode` | `text not null` | `paper` \| `live` — мөр бүр өөрөө мэднэ (AC-21) |
| `submitted_at`, `filled_at` | `timestamptz` | |

Индекс: `(status) where status in ('accepted','partially_filled')`,
`(symbol, submitted_at desc)`, `(origin)`, `(client_order_id)`.

> **Яагаад `origin` анхдагчгүй:** анхдагч утга нь «мэдэхгүй»-г «мэднэ» болгож
> хувиргана. `NOT NULL` + анхдагчгүй нь дуудагч бүрийг ил заахад хүргэнэ —
> AC-29-ийн «ХЭЗЭЭ Ч таамаглахгүй» дүрмийн схем дэх илэрхийлэл.

### 5.3 `fills`
`id`, `order_id fk`, `broker_fill_id unique`, `qty`, `price`, `filled_at`,
`raw jsonb`. **Локал тооцоолол БАЙХГҮЙ** — Alpaca-ийн мэдээлсэн гүйцэтгэл л
орно (хавсралт 02 §6).

### 5.4 `agent_decisions`
`id`, `agent`, `provider`, `model`, `session_id`, `proposal jsonb`,
`grounding jsonb` (`passed`, `unverified_claims`), `risk_evaluation jsonb`,
`outcome`, `order_id fk`, `created_at`.
⚠ Гарын order энд мөр ҮҮСГЭХГҮЙ (AC-32) — тэр нь agent-ийн шийдвэр биш.

### 5.5 `tool_calls`
`id`, `decision_id fk (nullable)`, `session_id`, `tool_name`,
`request jsonb`, `response jsonb`, `source`, `called_at`, `latency_ms`,
`provider`.
Хариу нь **redaction-аас өөр засваргүй** (AC-8). Grounding checker энэ
payload-аас хайна. Бичилт нь LLM-д хариу буцахаас **ӨМНӨ** (INV-4).

### 5.6 `tuning_history`
`id`, `parameter`, `old_value`, `new_value`, `bounds jsonb`,
`backtest_window jsonb`, `walk_forward jsonb`, `applies_to`,
`approved_by check in ('system','operator')`, `changed_at`.

### 5.7 `audit_log` — append-only, hash-chained
| Багана | Төрөл |
|---|---|
| `seq` | `bigserial pk` |
| `ts` | `timestamptz not null default now()` |
| `event_type` | `text not null` |
| `actor` | `text not null` (`operator` \| `research_agent:<provider>/<model>` \| `system:<component>`) |
| `payload` | `jsonb not null` (redact-лагдсан) |
| `prev_hash` | `bytea not null` |
| `hash` | `bytea not null unique` |

Гурван `RULE`/trigger нь `UPDATE`, `DELETE`, `TRUNCATE`-ыг татгалзана.
App хэрэглэгчид `INSERT`, `SELECT`-ээс өөр GRANT байхгүй.

### 5.8 `system_state` — append-only төлөвийн түүх
`seq bigserial pk`, `state check in ('active','winding_down','halted')`,
`reason`, `changed_by check in ('operator','circuit_breaker','scheduler')`,
`changed_at timestamptz not null`, `wind_down_deadline timestamptz`.
**Одоогийн төлөв = хамгийн их `seq`-тэй мөр.** `UPDATE`/`DELETE` татгалзана.

### 5.9 `approvals`
`id`, `version int not null default 1`, `state`, `decision_id fk`,
`proposed_order jsonb`, `risk_evaluation jsonb`, `created_at`,
`expires_at not null`, `resolved_at`, `resolved_by`, `resolution_reason`.
Индекс: `(state, expires_at) where state = 'pending'` — reaper-ийн скан.

### 5.10 `confirmations` — хоёр шаттай баталгаажуулалт (§8.4)
`token text pk`, `action text not null`, `payload_hash bytea not null`,
`created_at`, `expires_at`, `consumed_at`.
Нэг удаа хэрэглэгдэнэ (`consumed_at` тавигдмагц дахин хүчингүй).

### 5.11 Хамаарлын зураг

```
accounts ─< orders >─ approvals >─ agent_decisions >─ tool_calls
              │                            │
              └─< fills                    └── (grounding эх сурвалж)
system_state (бие даасан)   tuning_history (бие даасан)
audit_log (бүгдийн тусгал, hash chain)     confirmations (богино настай)
```

---

## 6. Арилжааны төлөвийн машин (OP-13-ийн цөм)

### 6.1 Төлөв ба шилжилт

```
                  POST /system/wind-down
        ┌──────────────────────────────────────┐
        │                                      ▼
   ┌─────────┐                        ┌───────────────┐
   │ ACTIVE  │                        │ WINDING_DOWN  │
   └─────────┘                        └───────────────┘
        │  POST /kill-switch                 │   │
        │  эсвэл breaker trip                │   │ grace дуусав (scheduler)
        │                                    │   │ эсвэл POST /kill-switch
        ▼                                    │   ▼
   ┌──────────────────────────────────────────────┐
   │                  HALTED                       │
   └──────────────────────────────────────────────┘
        ▲                                    │
        │  process restart (төлөв хадгалагдана)
        │                                    │
        └──── POST /system/activate ─────────┘
              (баталгаажуулалт + breaker дахин хэмжилт)
```

| Одоогийн | Үйлдэл | Шинэ | Нөхцөл |
|---|---|---|---|
| `active` | `wind-down` | `winding_down` | `deadline = now + WIND_DOWN_GRACE` |
| `active` | `kill-switch` | `halted` | нөхцөлгүй |
| `active` | breaker trip | `halted` | `changed_by=circuit_breaker`, `reason=<metric>` |
| `winding_down` | `kill-switch` | `halted` | grace-ийг богиносгоно |
| `winding_down` | grace дуусав | `halted` | `changed_by=scheduler` |
| `winding_down` | breaker trip | `halted` | |
| `winding_down` | `wind-down` | — | идемпотент, deadline СУНГАХГҮЙ |
| `halted` | `wind-down` | — | 409 `already_halted` |
| `halted`/`winding_down` | `activate` | `active` | token хүчинтэй **БА** breaker метрик бүр босгоос доош |
| `active` | `activate` | — | 409 `already_active` |
| аль ч | process restart | өөрчлөгдөхгүй | §6.3 |

> **Зориудаар БАЙХГҮЙ шилжилт:** `halted → winding_down`. Зогссоны дараа
> «бага зэрэг арилжаа» гэсэн завсрын горим нь kill switch-ийн утгыг сулруулна.

### 6.2 Хэрэгжүүлэлт — `system/state.py`

```python
class StateMachine:
    async def current(self) -> SystemStateRow:
        """Хамгийн их seq-тэй мөр. 200ms TTL-тэй process-дотоод кэш —
        Redis-д БИШ (P-6). Бичилт бүр кэшийг устгана."""

    async def transition(self, to, *, by, reason, deadline=None) -> SystemStateRow:
        """Нэг транзакц дотор:
           1) SELECT ... FOR UPDATE — `system_state`-ийн дэвшилтийн lock мөр
           2) шилжилтийн хүснэгтийг шалгах (хориотой бол InvalidTransition)
           3) шинэ мөр INSERT
           4) audit_log-д бичих (нэг транзакц — хоёулаа орно, эсвэл аль нь ч биш)
           5) commit ДАРАА Redis `system` суваг руу нийтлэх
        """
```

Дараалал чухал: **commit → дараа нь нийтлэх**. Эсрэгээр хийвэл клиент DB-д
байхгүй төлөв харах цонх үүснэ. 1 секундын шаардлага (AC-34) нь энэ гурвыг
багтаана: transaction commit + Redis publish + WS fan-out. Хэмжилт нь
`transition()` дуудагдсанаас клиент хүлээж авах хүртэл.

### 6.3 Наалдамхай байдал ба restart (AC-37)

`main.py` lifespan-ийн эхэнд:

```python
state = await state_machine.current()      # DB-ээс УНШИНА
# ЭХЛҮҮЛЭХГҮЙ. Мөр байхгүй бол (анхны deploy) → 'halted' гэж INSERT,
# reason='initial_deploy'. Анхдагч нь ХАМГИЙН АЮУЛГҮЙ төлөв.
if state.state is WINDING_DOWN and state.wind_down_deadline <= now_utc():
    await state_machine.transition(HALTED, by="scheduler", reason="grace_expired_while_down")
```

Унтарсан хугацаанд grace дууссан бол **сэрэхдээ `halted`**. Энэ нь «унтарсан
цагийг grace-аас хасахгүй» гэсэн шийдвэр — хуанлийн цаг (OQ-8-ийн таамаг).

Redis унасан ч төлөв алдагдахгүй: эх нь Postgres. Redis сэргэх үед fan-out
сэргэнэ; клиент `GET /system/state`-ээр нөхнө.

### 6.4 Grace-ийн scheduler

APScheduler-ийн `interval` job (10 секунд тутам) нь `winding_down` төлөвт
`deadline <= now` эсэхийг шалгаад `halted` руу шилжүүлнэ. Мөн
`transition(WINDING_DOWN)` нь deadline дээр `date` job бүртгэнэ — хоёулаа
байгаа нь зориуд: `date` job нь нарийвчлалыг, `interval` нь restart-ийн
дараах нөхөлтийг өгнө. Хоёул `transition()` дуудах тул давхардал нь
идемпотент (`halted → halted` = үйлдэлгүй).

---

## 7. `BrokerPort` ба `AlpacaAdapter`

```python
class BrokerPort(Protocol):
    async def get_account(self) -> Envelope[Account]: ...
    async def get_positions(self) -> Envelope[list[Position]]: ...
    async def get_open_orders(self) -> Envelope[list[BrokerOrder]]: ...
    async def submit_order(self, req: ValidatedOrder) -> BrokerOrder: ...
    async def cancel_order(self, broker_order_id: str) -> None: ...
    def stream_market_data(self, symbols) -> AsyncIterator[Tick]: ...
    def stream_trade_updates(self) -> AsyncIterator[TradeUpdate]: ...
```

**`submit_order`-ийн оролт нь `ValidatedOrder`** — `ManualOrderRequest` ч,
`ProposedOrder` ч биш. `ValidatedOrder`-ыг үүсгэх ЦОРЫН ГАНЦ газар нь
`risk.agent.evaluate()`-ийн `APPROVE` салаа. Энэ нь P-1-ийг **төрлийн
системээр** барьж байгаа хэлбэр: Risk-ийг тойрсон дуудагч нь тохирох
объектыг гартаа авч чадахгүй. Import-graph тест (§18.2) нь хоёр дахь давхарга.

**Adapter-ийн дүрэм:**
- Alpaca-ийн хариу нь домэйн модель рүү **зөвхөн буулгагдана**, дахин
  тооцогдохгүй (AC-1). `market_value` нь Alpaca-аас ирнэ, `qty × price`-аар
  ХЭЗЭЭ Ч тооцогдохгүй.
- Түүхий хариу нь `tool_calls.response`-д ба `Envelope.source`-той хамт хадгалагдана.
- `source` нь `resolve_mode()`-оос: `paper → ALPACA_PAPER`, `live → ALPACA_LIVE`.
- Alpaca хүрэхгүй бол: `BrokerUnavailable` raise. **Кэшээс хуучин утга
  буцаахгүй** — 503 + `stale: true`.
- Retry: зөвхөн УНШИХ дуудалтад (exponential backoff, 3 оролдлого).
  `submit_order` нь ЗӨВХӨН сүлжээний timeout дээр, `client_order_id`-ийн
  ижил утгаар дахин илгээгдэнэ (§9.2) — өөр алдаанд retry БАЙХГҮЙ.

**EOD reconciliation (T-10):** өдөр бүр зах зээл хаагдсаны дараа Alpaca-ийн
position/order-ийг локал мөртэй тулгана. Зөрүү гарвал: локалыг Alpaca-аар
ЗАСНА (Alpaca нь эх сурвалж), зөрүүг `audit_log`-д `reconciliation_drift`
болгож бичнэ, зөрүү `RECONCILE_DRIFT_LIMIT`-ээс их бол breaker trip.

---

## 8. Risk Agent — детерминистик хаалга

### 8.1 Гарын үсэг ба дүрмийн дараалал

```python
def evaluate(ctx: RiskContext, req: OrderIntent) -> RiskEvaluation:
    """ЦЭВЭР ФУНКЦ. I/O БАЙХГҮЙ, цаг унших БАЙХГҮЙ, random БАЙХГҮЙ.
    Бүх оролт ctx-д: account, positions, quote, day_trades, system_state,
    limits, now. Тиймээс 10 000 property кейс нь DB-гүй ажиллана."""
```

Дүрэм бүр `rules.py`-д нэг функц, дараалал нь ТОГТМОЛ (эхний унасан нь
шийднэ, гэхдээ **бүх** дүрэм ажиллаж `checks[]` бүрэн бөглөгдөнө — operator
юу унасныг бүхэлд нь харна):

| # | Дүрэм | Config | Гаралт |
|---|---|---|---|
| R1 | `system_state` | — | `halted` → REJECT; `winding_down` → R2 руу |
| R2 | `wind_down_direction` | — | `winding_down` үед exposure нэмэгдүүлбэл REJECT (§8.2) |
| R3 | `restricted_symbol` | `RESTRICTED_SYMBOLS` | жагсаалтад байвал REJECT |
| R4 | `price_sanity` | `PRICE_SANITY_PCT` | limit/stop нь сүүлийн quote-оос хэт хол → REJECT (fat-finger) |
| R5 | `pdt_day_trades` | `MAX_DAY_TRADES` | equity < $25k **БА** day trade хэтэрсэн → REJECT |
| R6 | `position_pct` | `MAX_POSITION_PCT` | шинэ позицийн % equity-ээс хэтэрвэл REJECT |
| R7 | `total_exposure_pct` | `MAX_TOTAL_EXPOSURE_PCT` | нийт exposure хэтэрвэл REJECT |
| R8 | `daily_loss_limit` | `DAILY_LOSS_LIMIT` | өдрийн алдагдал босго давсан → REJECT |
| R9 | `order_notional` | `MAX_ORDER_NOTIONAL` | хэтэрвэл **ESCALATE_TO_HUMAN** (REJECT биш) |

**Нэгтгэх дүрэм:** аль нэг R1…R8 унавал `REJECT`; бүгд дамжаад R9 л
асуувал `ESCALATE_TO_HUMAN`; бүгд дамжвал `APPROVE`.
`REJECT` нь `ESCALATE`-ээс ДАВУУ — хоёул унавал `REJECT`.

**`APPROVE` нь `ValidatedOrder`-ыг ХАМТ буцаана** (§7-ийн төрлийн хаалт).
Тэр объектод Risk-ийн харсан `qty`, `limit_price` нь **хөлдөнө** — Execution
түүнийг өөрчилж чадахгүй (frozen dataclass).

### 8.2 Wind-down чиглэлийн дүрэм (R2, AC-35)

«Exposure нэмэгдүүлэх» тодорхойлолт (`tasks.md` T-45-ийг алгоритм болгов):

```python
def increases_exposure(pos: Position | None, req: OrderIntent) -> bool:
    if pos is None:                       return True   # шинэ symbol
    if pos.side is LONG  and req.side is BUY:  return True   # нэмж авах
    if pos.side is SHORT and req.side is SELL: return True   # нэмж богиносгох
    # эсрэг тийш: хаалт эсвэл эргүүлэлт
    return req.qty > abs(pos.qty)         # хэтрүүлэн эргүүлэх = нэмэгдүүлэх
```

- `req.qty <= abs(pos.qty)` эсрэг тийш → **хэсэгчилсэн эсвэл бүрэн хаалт**,
  зөвшөөрөгдөнө.
- `req.qty > abs(pos.qty)` эсрэг тийш → **эргүүлэлт**, татгалзана. Хэрэгтэй
  бол operator хоёр order болгож хийнэ (эхлээд хаах — гэхдээ хоёр дахь нь
  нэмэгдүүлэх тул wind-down үед дамжихгүй; энэ нь зорилготой).
- **§7-ийн хязгаарууд wind-down үед СУЛРАХГҮЙ:** R3…R9 хаах order-т ч
  бүрэн ажиллана. Wind-down нь дүрэм НЭМНЭ, хасахгүй.

### 8.3 `RiskContext`-ийн угсралт

`api` давхарга нь дараах дарааллаар угсарна (бүгд БОДИТ уншилт, кэш биш):
`state_machine.current()` → `broker.get_account()` → `broker.get_positions()`
→ `broker.get_quote(symbol)` → `limits` (Settings-ээс) → `now_utc()`.
Quote ирэхгүй бол R4 ажиллах боломжгүй → **REJECT** (`reason=no_quote`).
Мэдэхгүй байдал нь зөвшөөрөл БИШ.

### 8.4 Хоёр шаттай баталгаажуулалт (нэг механизм, гурван хэрэглээ)

`ESCALATE_TO_HUMAN` гарын замд, `POST /system/activate`,
`POST /tuning/promote` — гурвуулаа НЭГ механизм ашиглана:

```
1) Клиент үйлдлийг token-гүй дуудна.
2) Сервер: `confirmations`-д мөр INSERT (token, action, payload_hash,
   expires_at = now + CONFIRMATION_TTL) → 409 `confirmation_required` +
   `confirmation.prompt` (үйлдэл тус бүрд ӨӨР текст).
3) Клиент ЯГ ижил биеийг `confirmation_token`-той дахин илгээнэ.
4) Сервер: token байгаа, хугацаа дуусаагүй, `consumed_at is null`,
   `payload_hash` ТААРНА → `consumed_at` тавиад үргэлжилнэ.
```

`payload_hash` нь чухал: token авсныхаа дараа биеийг өөрчлөх (жишээ нь
хэмжээг өсгөх) боломжгүй. Prompt-ийн текст өөр байх нь AC-38-ийн «хоёр
товчийг андуурахгүй» шаардлагын backend тал.

`POST /kill-switch` нь **баталгаажуулалт ШААРДАХГҮЙ** — яаралтай зогсоох
замд саад тавих нь аюулгүй байдлыг бууруулна.

---

## 9. Order-ийн амьдралын мөчлөг

### 9.1 Төлөвийн диаграм

```
pending_risk ──REJECT──► rejected            (Alpaca руу 0 дуудалт)
     │
     ├──ESCALATE──► pending_approval ──reject/TTL──► rejected
     │                     │ approve
     ▼                     ▼
  accepted (Alpaca хүлээн авав) ──► partially_filled ──► filled
     │                                    │
     └──────────► canceled / expired ◄────┘
  (submit-ийн алдаа) ──► failed
```

`pending_risk` → `accepted` хооронд `client_order_id` аль хэдийн тогтсон
байна — submit амжилтгүй болсон ч давхардал үүсэхгүй.

### 9.2 Idempotency (T-08)

```python
client_order_id = "p3-" + blake2s(
    idempotency_key + "|" + canonical_json(order_fields), digest_size=12
).hexdigest()
```

- Клиентээс `Idempotency-Key` (UUID) заавал.
- Ижил key + ижил талбар → ижил `client_order_id` → DB-ийн `unique` барина →
  байгаа order-ыг буцаана (шинэ submit БАЙХГҮЙ).
- Ижил key + өөр талбар → hash өөр → гэхдээ `Idempotency-Key`-ийн
  бүртгэлээс зөрүү илэрч **409 `idempotency_conflict`**. (Зөвхөн hash дээр
  түшиглэвэл өөр биетэй давхар order дамжина — тиймээс key-ийн бүртгэл
  тусдаа шалгагдана.)
- Alpaca руу `client_order_id`-г дамжуулна — сүлжээний timeout дээр дахин
  илгээхэд Alpaca тал дээр ч давхардахгүй.

### 9.3 Гарын order-ийн урсгал (OP-12, AC-31…33)

```
Operator → UI Ticket
   │  POST /orders/manual  (Idempotency-Key)
   ▼
api/orders.py
   │  1. state = state_machine.current()
   │     halted        → 409 system_halted            [Alpaca дуудалт 0]
   │  2. RiskContext угсрах (§8.3)
   │  3. risk.evaluate(ctx, intent)
   │       REJECT              → 422 risk_rejected + checks[]   [дуудалт 0]
   │       ESCALATE_TO_HUMAN   → 409 confirmation_required      [дуудалт 0]
   │         (token-той дахин ирвэл үргэлжилнэ)
   │       APPROVE             → ValidatedOrder
   ▼
execution.agent.submit(validated, origin=MANUAL_OPERATOR, actor=<operator>)
   │  → orders INSERT (origin='manual_operator', decision_id=NULL)
   │  → BrokerPort.submit_order   ◄── ЦОРЫН ГАНЦ дуудагч
   │  → audit_log: manual_order_submitted (actor + confirmation token id)
   ▼
202 Accepted { order, risk }
```

**Зориудаар БАЙХГҮЙ:** `agent_decisions`-д мөр, grounding шалгалт, approval
queue-ийн мөр. Гарын order нь **agent-ийн санал БИШ** (AC-32) — decision
feed-д agent-ийн шийдвэр мэт харагдахгүй. UI нь түүнийг тусдаа «Гарын»
шошготой харуулна.

**Зориудаар ИЖИЛ:** Risk Agent, Execution модуль, `submit_order`-ийн
дуудагчийн хязгаарлалт, §7-ийн бүх хязгаар, audit. «Operator өөрөө шүү дээ»
гэсэн үндэслэлээр нүх гаргахгүй (`plan.md` P-6).

### 9.4 Agent-ийн order-ийн урсгал

```
Research Agent (LLM) → propose_order tool
   ▼ agents/tools.py
   1. system_state шалгах:
        halted        → stage=risk_rejected, reason=halted   [Risk хүртэл очихгүй]
        winding_down + increases_exposure → ил татгалзал
        (Энэ нь Risk-ийн R1/R2-ыг ОРЛОХГҮЙ — эхний давхарга, agent-т
         ойлгомжтой хариу өгөхийн тулд. Risk хоёр дахь давхарга хэвээр.)
   2. GroundingChecker (§13) → унавал stage=grounding_failed,
      agent_decisions-д бичигдэнэ, Risk хүртэл ОЧИХГҮЙ
   3. risk.evaluate(...)
        REJECT   → agent_decisions(outcome=risk_rejected)
        ESCALATE → approvals INSERT (expires_at = now + APPROVAL_TTL)
                   → WS system: approval_created
        APPROVE  → execution.agent.submit(validated,
                       origin=RESEARCH_AGENT, origin_detail=f"{provider}/{model}")
```

---

## 10. Execution Agent

```python
# execution/agent.py — BrokerPort.submit_order-ийн ЦОРЫН ГАНЦ дуудагч
async def submit(order: ValidatedOrder, *, origin: Origin,
                 origin_detail: str | None, decision_id: UUID | None,
                 approval_id: UUID | None) -> Order
```

- `ValidatedOrder`-ын талбарыг **өөрчилж чадахгүй** (frozen) — Risk-ийн
  зөвшөөрснөөс өөр зүйл илгээгдэх боломжгүй.
- Дараалал: `orders` INSERT (`pending_risk` → `accepted` хүртэл) →
  `BrokerPort.submit_order` → `broker_order_id` UPDATE → `audit_log`.
  DB бичилт нь Alpaca дуудалтаас **ӨМНӨ** — ингэснээр «илгээгдсэн ч
  бүртгэгдээгүй» цонх үүсэхгүй. Alpaca унавал мөр `failed` болно.
- `submit_order` нь дуудагдахаас өмнө `state_machine.current()`-ийг ДАХИН
  шалгана (TOCTOU: Risk-ийн шалгалтаас хойш kill switch дарагдсан байж
  болно). `halted` бол илгээхгүй, `failed` + `reason=halted_before_submit`.

---

## 11. Attribution (OP-11)

### 11.1 Position-ийн origin тогтоох алгоритм

```python
def resolve_origin(pos: Position, local_orders: dict[str, Order]) -> tuple[Origin, str | None]:
    """Alpaca нь position-д client_order_id өгдөггүй. Тиймээс тухайн
    symbol дээрх ХАМГИЙН СҮҮЛИЙН filled локал order-оор тодорхойлно."""
    candidates = [o for o in local_orders.values()
                  if o.symbol == pos.symbol and o.status in (FILLED, PARTIALLY_FILLED)]
    if not candidates:
        return Origin.EXTERNAL, None          # ХЭЗЭЭ Ч таамаглахгүй
    latest = max(candidates, key=lambda o: o.filled_at)
    return latest.origin, latest.origin_detail
```

**Ил хязгаарлалт (ЭНЭ ЗАГВАРЫН ХИЛ):** нэг symbol дээр олон origin-ээс
хуримтлагдсан позицийг энэ алгоритм НЭГ origin-д оноож байна (хамгийн сүүлийн
fill). Энэ нь буруу оноолт биш, харин **бүрэн бус** — жинлэсэн задаргаа
хийхийн тулд `fills`-ийг order-оор нь задлах хэрэгтэй. v1-д гаргалгаа:
UI нь ийм symbol дээр «холимог» тэмдэг харуулна (§16.4), жинлэсэн задаргаа
нь backlog. Локал fill огт байхгүй бол `external` — таамаг БАЙХГҮЙ (AC-29).

### 11.2 `GET /attribution`-ийн угсралт

Нэг SQL query — тусдаа кэш БАЙХГҮЙ (AC-30):

```sql
-- нээлттэй order-ийн symbol-ууд origin-оор
SELECT origin, origin_detail, symbol, count(*) AS open_order_count
FROM orders WHERE status IN ('accepted','partially_filled','pending_approval')
GROUP BY 1,2,3
-- + Alpaca-аас ирсэн нээлттэй позицууд (§11.1-ээр origin оноогдсон)
-- + сүүлийн шийдвэрийн хугацаа: agent_decisions-аас symbol-оор LATERAL JOIN
```

Гаралтын symbol олонлог нь `orders` ∪ `positions`-ийн symbol олонлогтой
**ЯГ тэнцүү** байх ёстой — T-46-ийн DoD энэ тэнцлийг set харьцуулалтаар
шалгана. Илүү symbol = зохиосон өгөгдөл; дутуу symbol = нуусан эрсдэл.

---

## 12. Agent Gateway ба Provider Router

### 12.1 Tool dispatch

```
LLM → adapter → gateway.dispatch(tool_name, args, session)
  1. session-ийн provider-ийг тогтоох (солигдсон ч ЭНЭ дуудалт хуучнаар)
  2. tool_calls INSERT (request, provider, called_at) → tool_call_id
  3. handler ажиллуулах (broker / backtest / tuning уншилт)
  4. tool_calls UPDATE (response, latency_ms) — ХАРИУ БУЦААХААС ӨМНӨ (INV-4)
  5. result_envelope угсрах: tool_call_id + timestamp + source
     + system_state (§12.4) + ok/error + data
  6. redact (§14.3) → adapter → LLM
```

### 12.2 Provider Router ба hot-swap (AC-10, AC-11)

```python
class ProviderRouter:
    _active: dict[Role, ProviderAdapter]      # atomic reference swap
    _in_flight: dict[str, int]                # provider_id → тоо

    async def switch(self, role: Role, provider_id: str) -> SwitchResult:
        """1) шинэ adapter-ийн health check (унавал 422, солихгүй)
           2) _active[role] = new   ← ганц заалт, lock хэрэггүй (GIL)
           3) audit_log + WS system: provider_switched
           Нислэг дунд байгаа дуудалт нь өөрийн session-ийн adapter-ийн
           ЛАВЛАГААГ атгасан тул хуучнаар дуусна, хуучнаар бүртгэгдэнэ."""
```

Restart БАЙХГҮЙ (NFR-4). Session нь эхлэхдээ adapter-ийн лавлагааг барьж
авдаг тул нэг харилцан яриа дунд provider солигдохгүй — солилт нь
**дараагийн** session-д хүчинтэй. Энэ нь «нэг шийдвэр хоёр модель» гэсэн
будлианаас сэргийлнэ, `agent_decisions.provider` нь үргэлж нэг утгатай.

### 12.3 Fallback бодлого

Идэвхтэй provider `PROVIDER_ERROR_THRESHOLD` удаа дараалан унавал:
- Тохируулсан fallback байвал түүн рүү шилжинэ (audit-д бичигдэнэ).
- Fallback нь `read_only: true` бол → **шинэ санал гарахгүй**, систем
  зөвхөн ажиглана. Risk/Monitoring нь LLM-ээс хамааралгүй ажилласаар байна.
- ХЭЗЭЭ Ч: Risk-ийг алгасах, кэшлэгдсэн саналыг гүйцэтгэх, auto-approve.

### 12.4 Системийн төлөвийг agent-т хүргэх (AC-34, T-48)

`system_state` нь **tool result бүрийн заавал талбар** (`contracts.yaml`
3-р баримт, `result_envelope`). Нэмэлт мэдэгдлийн суваг БАЙХГҮЙ — LLM нь
мэдэгдлийг үл тоомсорлож болох ч, tool result-гүйгээр ажиллаж чадахгүй.

`guidance` мөр нь машинд биш LLM-д зориулагдсан тодорхой заавар. Тиймээс
төлөв солигдсоны дараах **эхний** tool result нь шинэ утгыг агуулна: agent
төлөвийг мэдэлгүй үлдэх цонх байхгүй.

Нэмэлт давхарга: `propose_order` handler нь `winding_down` үед exposure
нэмэгдүүлэх саналыг Risk-д хүрэхээс өмнө татгалзаж, шалтгааныг ил
буцаана — ингэснээр agent дахин оролдож, ХААХ санал гаргаж чадна.
Энэ нь Risk-ийн R2-ыг **ОРЛОХГҮЙ**; R2 нь хоёр дахь, эцсийн давхарга.

---

## 13. Grounding Checker (NFR-1, AC-9)

```python
def check(rationale: str, cited: list[ToolCall]) -> GroundingResult:
    claims = extract_numbers(rationale)      # үнэ, тоо ширхэг, хувь
    haystack = {normalize(n) for tc in cited for n in walk_numbers(tc.response)}
    unverified = [c for c in claims if normalize(c) not in haystack]
    return GroundingResult(passed=not unverified, unverified_claims=unverified)
```

**Тоон мэдэгдэл олох:** `rationale`-аас тоо шиг token-уудыг regex-ээр
(`-?\d[\d,]*\.?\d*%?`) гаргана. Ердийн үг доторх дугаар (жишээ «20-day MA»-ийн
20) нь худал эерэг үүсгэх тул **цагаан жагсаалт**: `WINDOW_TOKENS` (moving
average window, RSI period г.м.) нь мэдэгдэл гэж тооцогдохгүй.

**Нормчлол:** таслал арилгах, `%` тусад нь, Decimal болгож `quantize(1e-6)`.
Цитат payload дотроос тоог рекурсив (`walk_numbers`) цуглуулна — дотоод
бүтэц гүн байж болно.

**Хатуу байдлын тохируулга:** `GROUNDING_TOLERANCE` (анхдагчгүй config) нь
хувийн зөрүүг зөвшөөрөх эсэхийг заана. v1-ийн санал: `0` — яг таарна.
Тэвчээртэй горим нь «ойролцоо тоо» гэсэн цонх нээх тул ил config, чимээгүй
зөөлрөлт биш.

**Унавал:** Risk хүртэл ОЧИХГҮЙ. `agent_decisions(outcome=grounding_failed,
grounding.unverified_claims=[...])`. `unverified_claims` нь LLM рүү
буцна — засаж дахин оролдох боломжтой. Энэ нь харилцан яриа, чимээгүй
хаялт биш.

**Adversarial suite (T-24):** delisted symbol, өгөгдөлгүй огнооны муж,
зохиосон үнэ, зөв тоо + буруу tool_call_id, хоосон `grounded_in`.
Бүгд «байхгүйг мэдээлэх» ёстой, таамаглах биш.

---

## 14. Audit log — hash chain

### 14.1 Hash-ийн ЯГ тодорхойлолт

```python
payload_bytes = json.dumps(redact(payload), sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False).encode()
digest = sha256(prev_hash + seq.to_bytes(8,"big")
                + ts.isoformat().encode() + event_type.encode()
                + actor.encode() + payload_bytes).digest()
```

`prev_hash` нь эхний мөрөнд 32 тэг байт. `sort_keys` + `separators` нь
канон хэлбэрийг тогтооно — өөр серилизациар ижил мөрөөс өөр hash гарвал
verifier худал сэрэмжлүүлэг өгнө.

### 14.2 Verifier (T-23)

`seq` дарааллаар бүх мөрийг уншиж hash-ийг дахин тооцно. Эхний зөрүүтэй
`seq`-ийг мэдээлж зогсоно. CI-д ажиллах жижиг fixture + prod-д өдөр тутмын
job. Мөн `verify --from <seq>` горим — томорсон лог дээр бүтнээр биш,
сүүлийн хэсгийг шалгах.

### 14.3 Redaction (T-05, NFR-3)

`redact()` нь **allow-list** биш, **pattern + key** хосолсон:
- Түлхүүрийн нэрээр: `api_key`, `secret`, `token`, `authorization`,
  `password`, `key_ref`-ийн утга (`key_ref` өөрөө лавлагаа тул үлдэнэ,
  утга нь ХЭЗЭЭ Ч энд орохгүй).
- Утгын хэв маягаар: Alpaca key-ийн формат, `Bearer …`, JWT.
- CI-ийн тест (T-05): мэдэгдэж буй secret хэв маягуудыг лог руу дамжуулж,
  гаралтад нэг ч тохиолдол үлдээгүйг батална.

Redaction нь `tool_calls.response`-д МӨН хамаарна — гэхдээ зөвхөн secret.
Зах зээлийн өгөгдөл өөрчлөгдөхгүй (AC-8: түүхий payload харагдана).

### 14.4 Зөвхөн логоос сэргээх скрипт (AC-18, T-25)

`python -m app.audit.replay --from <ts> --to <ts>` нь `audit_log`-оос
(DB-ийн бусад хүснэгтэд ХҮРЭЛГҮЙ) арилжааны дарааллыг сэргээнэ: ямар санал,
ямар өгөгдлөөр үндэслэгдсэн, Risk юу шийдсэн, хэн зөвшөөрсөн, юу илгээгдсэн,
юу биелсэн. Гаралтыг `orders`/`fills`-тэй тулгах тест нь скриптийн бүрэн
эсэхийг батална.

---

## 15. Kill switch, circuit breaker, approval TTL

### 15.1 Kill switch (AC-14)
`POST /kill-switch` → `transition(HALTED, by=operator)`. 1 секундын төсөв:
DB commit (~10ms) + Redis publish (~1ms) + WS fan-out (~5ms). Үлдсэн нь
нөөц. Хэмжилтийн тест нь дуудалтаас WS хүлээн авалт хүртэлх хугацааг барина.

Байгаа order цуцлагдахгүй, позиц хаагдахгүй (A-2). Шинэ submit-ийн бүх зам
(agent, manual, approval approve) нь `halted`-д хаагдана.

### 15.2 Circuit breaker (AC-15, AC-16)
`MonitoringAgent` нь 5 секунд тутам дөрвөн метрик хэмжинэ:

| Метрик | Эх сурвалж | Config |
|---|---|---|
| `daily_loss` | `account.equity` vs өдрийн нээлтийн equity | `DAILY_LOSS_LIMIT` |
| `api_error_rate` | сүүлийн `BREAKER_WINDOW` дахь Alpaca алдаа / нийт | `ERROR_RATE_LIMIT` |
| `order_reject_rate` | сүүлийн цонх дахь reject / нийт submit | `REJECT_RATE_LIMIT` |
| `ws_disconnects` | тасалдлын тоо / цонх | `WS_DISCONNECT_LIMIT` |

Аль нэг нь босго давбал `transition(HALTED, by=circuit_breaker,
reason=<metric>)`. **Автоматаар сэргэхгүй** — `activate` нь метрикийг ДАХИН
хэмжиж шийднэ (§6.1). Энэ нь «цэвэрлэсэн» тугийг гараар асаах замыг хаана:
хадгалагдсан төлөв биш, бодит хэмжилт.

**`api_error_rate`-ийн эх сурвалж нь `AlpacaAdapter` ӨӨРӨӨ.**
`bind_api_reporter` нь REST дуудалт БҮРИЙН (уншилт, `submit_order`,
`cancel_order`) үр дүнг `breaker_events(kind='api_error')`-д бичнэ — нэг
логик дуудалт = нэг мөр (retry-ийн оролдлогууд БИШ). Тоолуургүй метрик нь
`daily_loss`-ийн «broker унавал api_error_rate барина» гэсэн үндэслэлийг
хоосон болгоно: Alpaca бүрэн унасан үед дөрвүүлээ чимээгүй үлдэнэ.

**Хэмжигдээгүй нь `0` БИШ.** Цонхонд нэг ч үйл явдал байхгүй (эсвэл broker
хүрэхгүй) бол метрикийн утга нь `unmeasured` гэж ил гарна — `tripped` нь
ҮРГЭЛЖ `false`, гэхдээ UI нь түүнийг «хэвийн» гэж БИШ, «ХЭМЖИГДЭЭГҮЙ» гэж
харуулна (хавсралт 10-ийн «мэдэхгүйг мэднэ болгохгүй»).

### 15.3 Approval TTL reaper (AC-6)
30 секунд тутам: `UPDATE approvals SET state='expired', version=version+1,
resolution_reason='expired' WHERE state='pending' AND expires_at <= now()`.
`approve` нь мөрийг `SELECT ... FOR UPDATE`-ээр уншаад `expected_version`
шалгана (§6.2-ийн төлөвийн машинтай ИЖИЛ хэв маяг) тул reaper эсвэл хоёр
дахь `approve`-тэй уралдах нөхцөлд 409 буцна — шалгалт ба бичилт хоёрын
хооронд өөр tranзакц мөрийг өөрчлөх цонх БАЙХГҮЙ.

---

## 16. Frontend-ийн загвар

### 16.1 Бүтэц ба төлөвийн эх сурвалж

```
AppShell
 ├─ ModeBanner       ← useSystemState().source   (PAPER / LIVE / BACKTEST)
 ├─ StateBar         ← useSystemState().state    (ACTIVE / WINDING_DOWN / HALTED)
 ├─ StalenessBanner  ← useStaleness()            (WS чимээгүй > 5s)
 └─ <Outlet/>  ← 8 route
```

- **REST** = үнэний эх (TanStack Query). **WS** = зөвхөн invalidation +
  шууд харагдах tick. WS мессежээс UI-ийн төлөвийг ШУУД угсрахгүй —
  тасалдлын дараа зөрүү үүсэхээс сэргийлнэ.
- `lib/api.ts` нь `contracts.yaml`-ийн 1-р баримтаас **үүсгэгдэнэ**
  (`openapi-typescript`). Гараар бичсэн төрөл БАЙХГҮЙ — гэрээ зөрвөл build
  унана.
- Мөнгө: `lib/money.ts` нь тэмдэгт мөрөөр л ажиллана. `Number(...)` нь
  мөнгөн талбарт ESLint-ээр хоригдоно (AC-25-ийн frontend тал).

### 16.2 Горим ба төлөвийн байнгын заалт (AC-20, AC-38)

`ModeBanner` — дэлгэцийн дээд ирмэгт наалдсан, бүх route дээр:

| Горим | Өнгө | Текст |
|---|---|---|
| `alpaca_paper` | цэнхэр | `PAPER — хуурамч мөнгө` |
| `alpaca_live` | улаан | `LIVE — БОДИТ МӨНГӨ` |
| `backtest` | саарал | `BACKTEST — түүхэн өгөгдөл` |

Backtest өгөгдөл нь live/paper-тэй **нэг хүснэгтэд ХЭЗЭЭ Ч** харагдахгүй
(AC-21) — тусдаа дэлгэц, тусдаа хүсэлт. Хольсон харагдац нь эрсдэлтэй
хэсэг тул ТЕСТЭЭР хоригдоно: Playwright нь нэг хүснэгтэд хоёр `source`
шошго зэрэг байвал унана.

`StateBar` — ModeBanner-ийн доор, мөн бүх route дээр:
- `ACTIVE` — ногоон цэг, `Зогсоо` ба `Унтраах бэлтгэл` товч идэвхтэй,
  `Идэвхжүүл` ИДЭВХГҮЙ.
- `WINDING_DOWN` — шар, `Позиц хаах цонх · үлдсэн 12:34` тоолуур,
  `Зогсоо` ба `Идэвхжүүл` идэвхтэй.
- `HALTED` — улаан, шалтгаан ил (`Өдрийн алдагдлын хязгаар давсан`),
  `Идэвхжүүл` идэвхтэй.

### 16.3 Гурван товчийг андуурахгүй болгох (AC-38)

| Товч | Өнгө / байрлал | Баталгаажуулалтын асуулт |
|---|---|---|
| **Зогсоо** | улаан, зүүн | Асуулт БАЙХГҮЙ — тэр дор нь ажиллана |
| **Унтраах бэлтгэл** | шар, төв | Асуулт БАЙХГҮЙ — эрсдэл БУУРУУЛАХ үйлдэл (§8.4-ийн баталгаажуулалт шаардах гурван үйлдэлд ороогүй). Буруу дарвал «Идэвхжүүл»-ээр, түүний баталгаажуулалтаар буцна. |
| **Идэвхжүүл** | ногоон, баруун | «Арилжааг дахин эхлүүлэх үү? Систем `HALTED`-аас `ACTIVE` болно.» + breaker-ийн одоогийн метрикүүд |

Товч бүр ӨӨР үг, өөр өнгө, өөр байрлал. Үлдсэн ганц асуулт («Идэвхжүүл»)-ын
текстийг backend `confirmation.prompt`-оор өгнө (§8.4) — UI-д хатуу кодлохгүй,
ингэснээр хоёр эх үүсэхгүй.

### 16.4 «Хэн юунд арилжаа хийж байна» (OP-11, AC-30)

`GET /attribution`-ийн бүлгээр — origin тус бүр нэг карт:

```
┌─ Research Agent · claude-sonnet-5 ────────────────────────┐
│  AAPL   позиц 12 ш · $2,340.00   нээлттэй order 1         │
│         сүүлийн шийдвэр 14:02:11Z          [яагаад →]      │
│  MSFT   позицгүй                 нээлттэй order 2         │
└───────────────────────────────────────────────────────────┘
┌─ Гараар (operator) ───────────────────────────────────────┐
│  TSLA   позиц 5 ш · $1,205.00    нээлттэй order 0         │
└───────────────────────────────────────────────────────────┘
┌─ Системээс гадуур ────────────────────────────────────────┐
│  NVDA   позиц 3 ш · $2,900.00    (локал бичлэггүй)        │
└───────────────────────────────────────────────────────────┘
```

- `[яагаад →]` нь Decision Log руу шүүлттэй холбоно — «AI юунд арилжаа
  хийж байна»-аас «яагаад» руу нэг даралт.
- §11.1-ийн холимог тохиолдолд symbol нь `холимог origin` тэмдэгтэй, бүх
  холбогдох origin-ийн картад харагдана — далдлахгүй. Гэрээний талбар нь
  `Position.origin_mixed` ба `/attribution`-ийн мөрийн `origin_mixed`;
  ийм symbol нь олон бүлэгт ДАВХАР гарна (задаргаа биш, оролцоо).
- Position/Orders хүснэгтийн мөр бүрд ч origin багана (AC-29).

### 16.5 Гарын арилжааны ticket (OP-12)

Маягт: symbol · тал · тоо ширхэг · order төрөл · үнэ. Илгээхээс өмнө:
- **Тооцоолсон notional.** Лавлах үнэ нь Risk-ийн `reference_price`-тай ЯГ
  ИЖИЛ дараалалтай: limit үнэ бичигдсэн бол ТЭР, эс бөгөөс `GET
  /market/quote/{symbol}`-ийн сүүлийн үнэ (`stale` бол ил тэмдэгтэй).
  Ингэснээр market/stop order дээр ч дүн харагдана, limit order дээр
  дэлгэцийн дүн нь R9-ийн шалгах дүнтэй ЗӨРӨХГҮЙ. Хэрэглэсэн үнийн эх
  сурвалж («limit үнэ» / «сүүлийн үнэ») нь дэлгэцэд нэрлэгдэнэ. Хоёулаа
  байхгүй бол дүн ЗОХИОХГҮЙ, «quote байхгүй» гэж бичнэ.
- **Risk-ийн урьдчилсан үнэлгээ** — `POST /orders/manual`-ийн эхний
  дуудалтын `checks[]`-ээс (409 эсвэл 422 хариу нь өөрөө урьдчилсан
  үнэлгээ болно; тусдаа «dry-run» endpoint нэмэхгүй).
- Босгоос дээш бол баталгаажуулалтын алхам (§8.4-ийн token урсгал).
  `Idempotency-Key` = бие + илгээх ОРОЛДЛОГО: баталгаажуулалтын хоёр дахь
  дуудалт ижил key-тэй, харин ижил маягтыг ДАХИН илгээвэл шинэ key —
  §9.2-ийн дедуп хуучин order-ыг «шинэ» мэт буцаахгүй.
- `HALTED` үед илгээх товч ИДЭВХГҮЙ + шалтгаан харагдана.
- `WINDING_DOWN` үед зөвхөн позиц БАГАСГАХ чиглэл сонгогдоно (нөгөө
  чиглэл идэвхгүй + тайлбар).

**Зориудаар БАЙХГҮЙ:** one-click order, chart-аас чирж тавих, «дахин
худалдан ав» товч. Спек §8-ийн dark-pattern хориг (`plan.md` P-8).

### 16.6 Бусад дэлгэц

| Дэлгэц | Гол агуулга | AC |
|---|---|---|
| Dashboard | equity curve, позиц, нээлттэй order, өдрийн P&L, staleness banner | AC-2 |
| Approval Queue | хүлээгдэж буй санал + agent-ийн үндэслэл + цитат өгөгдөл + TTL тоолуур | AC-5, AC-6 |
| Decision Log | он дарааллын feed, agent/symbol/outcome/provider-оор шүүх, мөр бүр **түүхий tool call payload** задарна | AC-7, AC-8 |
| Provider Switcher | role тус бүрийн идэвхтэй provider, health, унших/бичих эрх, dropdown | AC-10 |
| Auto-Tuning Panel | параметр, муж, одоогийн утга, түүх, walk-forward үр дүн, `promote` (баталгаажуулалттай) | AC-22…24 |
| Settings | хязгаарууд (ЗӨВХӨН УНШИХ — өөрчлөх нь deploy), API key-ийн төлөв (масктай), горим | AC-24 |

> Settings дээр хязгаар засах талбар БАЙХГҮЙ нь зориуд: §7-ийн тоо бол
> бодлого (P-2). UI-аас засах боломж нь SPEC_APPROVE-ийн хаалгыг тойрно.

### 16.7 Staleness илрүүлэлт (AC-2)

```ts
// useStaleness.ts
// Сервер HEARTBEAT_SECONDS тутам heartbeat илгээнэ.
// Клиент сүүлийн мессежээс 5s өнгөрвөл stale=true → banner.
// WS салсныг WebSocket.onclose ХҮЛЭЭХГҮЙ — чимээгүй тасалдал (сүлжээ
// унтарсан ч onclose ирэхгүй тохиолдол) нь хамгийн аюултай хэлбэр.
```

Banner дээр сүүлийн шинэчлэлтийн UTC хугацаа. Хуучин өгөгдөл live мэт
шошгогүй ХЭЗЭЭ Ч харагдахгүй.

---

## 17. Config, горим, live-ийн хаалт

### 17.1 `Settings` (pydantic-settings)

§7-ийн 10 хязгаар нь **анхдагч утгагүй** талбарууд. Дутуу бол
`ValidationError` → app эхлэхгүй (P-2). «Унтаа анхдагч руу унах» зам БАЙХГҮЙ.

Үүнээс гадна анхдагчгүй: `WIND_DOWN_GRACE`, `CONFIRMATION_TTL`,
`STALE_AFTER_SECONDS`, `GROUNDING_TOLERANCE`, `BREAKER_WINDOW`,
`PROVIDER_ERROR_THRESHOLD`, `RECONCILE_DRIFT_LIMIT`.

### 17.2 `resolve_mode()` — live болох гурван ил дохио (P-3, AC-12)

```python
def resolve_mode(env) -> TradingMode:
    if env.ALPACA_ENV != "live":                 return PAPER
    if not env.LIVE_TRADING_ACKNOWLEDGED:        raise ConfigError(...)
    if env.LIVE_CHECKLIST_SIGNATURE is None:     raise ConfigError(...)
    return LIVE
```

Гурвуулаа заавал. Нэг нь дутвал `paper` руу **унахгүй** — алдаа гаргаж
зогсоно. Чимээгүй доошлолт нь «live гэж бодсон, paper байсан» гэсэн эсрэг
төөрөгдлийг үүсгэнэ.

### 17.3 `LiveEgressGuard` (AC-12)

Тестийн үед `httpx` transport нь `api.alpaca.markets` руу гарах ямар ч
дуудалтыг **шууд AssertionError** болгоно. Энэ нь pytest fixture-ээр
автоматаар идэвхжинэ (`conftest.py`, opt-out БАЙХГҮЙ). «Тестийн явцад live
руу 0 дуудалт» нь итгэл биш, хэмжигдсэн баримт болно.

---

## 18. Тестийн бэхэлгээ (загварын зүгээс)

### 18.1 Загвар нь тестийг ХЭРХЭН боломжтой болгож байна

| Загварын шийдвэр | Ямар тестийг боломжтой болгож байна |
|---|---|
| `evaluate()` цэвэр функц, I/O-гүй | Hypothesis ≥10 000 кейс, DB-гүй, секундын дотор (AC-4, AC-35) |
| `ValidatedOrder` frozen + Risk-ээс л үүснэ | Execution нь Risk-ийн зөвшөөрснийг өөрчилж чадахгүйг төрлөөр батлах |
| `RiskContext` бүх оролтыг агуулна | Mutation testing утга учиртай — далд төлөв алга |
| `system_state` нь DB-д, Redis-д биш | Restart-ийн E2E (T-52) бодитоор ажиллана |
| Envelope нь `source`-той заавал | Холимог хоригийн тест нь schema түвшинд |
| `submit_order`-ийн дуудагч нэг package | Import-graph статик тест (§18.2) |

### 18.2 Статик хаалтууд (CI)

| ID | Дүрэм | Хэрэгжүүлэлт |
|---|---|---|
| R-1 | `BrokerPort.submit_order`-ийг зөвхөн `app.execution` дуудна | AST скан: `submit_order` дуудалтын модулийн prefix шалгах. Зөрчил = тест унана (AC-3, AC-31). |
| R-2 | `app.risk` нь `app.api`, `app.agents`, `app.broker`-ийг import хийхгүй | import-graph шалгалт |
| R-3 | Мөнгөн замд `float(` БАЙХГҮЙ | AST скан `app/risk`, `app/execution`, `app/broker` дээр (AC-25) |
| R-4 | `datetime.now()` / naive datetime БАЙХГҮЙ | AST скан (AC-26) |
| R-5 | `NETOS_GATES_SKIP` төстэй coverage тойрох тохиргоо БАЙХГҮЙ | CI config-ийн diff шалгалт (AC-27) |

Эдгээр нь `backend/tests/static/`-д энгийн pytest тест — тусдаа хэрэгсэл
нэмэхгүй (`plan.md`-ийн «хоёр дахь эх үүсгэхгүй» зарчим).

### 18.3 Coverage gate (AC-27)
`app/risk/**` — 100% line + branch. Order илгээх зам (`app/execution`,
`app/api/orders.py`, `app/approvals`) — ≥90%. CI-д босго; тойрох тохиргоо
нэмэх нь R-5-аар унана.

---

## 19. Хяналтад шалгах цэгүүд (CODE_REVIEW-д зориулав)

Энэ загварыг дагасан эсэхийг дараах жагсаалтаар л шалгана. Энд байхгүй
зүйлээр код буруутгахгүй.

1. `submit_order`-ийн дуудагч зөвхөн `app/execution` (§7, R-1).
2. `ValidatedOrder` нь `risk.evaluate()`-ийн APPROVE салаанаас л үүсдэг (§8.1).
3. `orders.origin` нь `NOT NULL`, migration-д анхдагч утга БАЙХГҮЙ (§5.2).
4. `system_state` нь Postgres-д, startup нь УНШИНА, эхлүүлэхгүй (§6.3).
5. `halted → winding_down` шилжилт кодод БАЙХГҮЙ (§6.1).
6. `activate` нь breaker метрикийг ДАХИН хэмжинэ, туг уншихгүй (§15.2).
7. Гарын order нь `agent_decisions`-д мөр үүсгэхгүй (§9.3).
8. Position-ийн origin нь локал fill олдохгүй бол `external`, «хамгийн
   ойрын» order-т наагдахгүй (§11.1).
9. `tool_calls` бичилт нь LLM-д хариу буцахаас ӨМНӨ (§12.1).
10. Tool result бүрд `system_state` талбар байна, schema-д `required` (§12.4).
11. Grounding унавал Risk хүртэл ОЧИХГҮЙ (§13).
12. `audit_log` дээр `UPDATE`/`DELETE` татгалзах trigger байна (§5.7).
13. §7-ийн 10 хязгаарын аль нэг нь кодод анхдагч утгатай БИШ (§17.1).
14. Frontend-ийн нэг хүснэгтэд хоёр `source` зэрэг харагдахгүй (§16.2).
15. Settings дэлгэцэд хязгаар засах талбар БАЙХГҮЙ (§16.6).

---

## 20. AC → загварын элемент хучилт (урвуу шалгалт)

| AC | Загварын элемент |
|---|---|
| AC-1 | §7 adapter-ийн «буулгана, тооцохгүй» дүрэм |
| AC-2 | §16.7 staleness, §16.6 Dashboard |
| AC-3 | §7 `ValidatedOrder` төрөл, §18.2 R-1 |
| AC-4 | §8.1 дүрмийн engine, §18.1 цэвэр функц |
| AC-5, AC-6 | §9.4 ESCALATE салаа, §15.3 TTL reaper, §5.9 optimistic lock |
| AC-7, AC-8 | §5.5 `tool_calls`, §16.6 Decision Log, §14.3 зөвхөн secret redaction |
| AC-9 | §13 Grounding checker |
| AC-10, AC-11 | §12.2 Router hot-swap, §12.3 fallback |
| AC-12, AC-13 | §17.2 `resolve_mode`, §17.3 `LiveEgressGuard` |
| AC-14, AC-15, AC-16 | §15.1 kill switch, §15.2 breaker, §6.1 шилжилт |
| AC-17, AC-18, AC-19 | §14.1 hash chain, §14.2 verifier, §14.4 replay |
| AC-20, AC-21 | §4 `Envelope`, §16.2 ModeBanner + холимог хориг |
| AC-22, AC-23, AC-24 | §21 auto-tuning, §16.6 Settings-д засвар байхгүй |
| AC-25, AC-26 | §4 Money/Instant хилийн дүрэм, §18.2 R-3/R-4 |
| AC-27, AC-28 | §18.3 coverage gate, §3 lockfile |
| **AC-29** | §5.2 `origin NOT NULL`, §11.1 resolver |
| **AC-30** | §11.2 `GET /attribution`, §16.4 харагдац |
| **AC-31** | §9.3 гарын урсгал (ижил Risk → Execution) |
| **AC-32** | §9.3 `agent_decisions`-д мөр үүсгэхгүй, §14 audit |
| **AC-33** | §9.3 төлөвийн шалгалт, §8.2 wind-down чиглэл |
| **AC-34** | §6.2 commit→publish, §12.4 tool result-ийн `system_state` |
| **AC-35** | §8.2 `increases_exposure()` |
| **AC-36** | §6.4 grace scheduler, §15.1 (позиц автоматаар хаагдахгүй) |
| **AC-37** | §6.3 startup нь УНШИНА, §15.2 breaker дахин хэмжилт |
| **AC-38** | §16.2 StateBar, §16.3 гурван товчийн ялгаа |

Хучигдаагүй AC БАЙХГҮЙ.

---

## 21. Auto-tuning (хязгаартай)

- **Whitelist ба bounds нь config** (`tuning_whitelist.yaml`), API-аар
  засах endpoint БАЙХГҮЙ (T-26). Муж өөрчлөх = deploy = code review.
- **Bounded search:** муж дотор grid эсвэл Bayesian, `step`-ээр хязгаарлагдсан.
- **Walk-forward validation:** `WF_FOLDS` тооны дараалсан fold; in-sample
  болон out-of-sample метрикийг ХОЁУЛАНГ нь `tuning_history`-д бичнэ.
  Out-of-sample сайжралгүй бол санал үүсэхгүй — curve-fitting-ийн хаалт.
- **Хуваарь:** долоо хоног тутам (A-4), тасралтгүй биш — өөрчлөлт бүр
  тусдаа, хянах боломжтой үйл явдал.
- **`applies_to` анхдагч нь `paper`.** `live` болох ЦОРЫН ГАНЦ зам =
  `POST /tuning/promote` + хоёр шаттай баталгаажуулалт + walk-forward
  нотолгоо байх ёстой. Ямар ч модель үүнийг хийж чадахгүй.

---

## 22. Алдаа ба доройтлын матриц

| Нөхцөл | Системийн зан төлөв | Хаана |
|---|---|---|
| Alpaca REST хүрэхгүй | 503 + `stale: true`; кэшээс хуучин утга буцаахгүй; шинэ submit зогсоно | §7 |
| Market data WS тасарсан | **v1-д market-data WS БАЙХГҮЙ** — quote нь `GET /market/quote/{symbol}` (REST)-ээс, хуучирсныг `stale` тугаар ил хэлнэ. `ticks` суваг нь гэрээнд НӨӨЦЛӨГДСӨН, нийтлэгддэггүй. Staleness banner нь `system` сувгийн heartbeat дээр тогтоно | §16.7 |
| Trade-update WS тасарсан | Reconciler нь дараагийн polling дээр нөхнө; зөрүү `audit_log`-д | §7 |
| Redis унасан | Төлөв алдагдахгүй (Postgres); WS fan-out зогсоно; REST ажиллана | §6.3 |
| Postgres унасан | Шинэ submit БОЛОМЖГҮЙ (бичилт нь submit-ээс өмнө) — аюулгүй тал руу унана | §10 |
| LLM provider унасан | Fallback эсвэл «шинэ санал гарахгүй»; Risk/Monitoring ажилласаар | §12.3 |
| Бүх provider унасан | Санал гарахгүй; байгаа позиц хөндөгдөхгүй; breaker ажилласаар | §12.3 |
| Хэсэгчилсэн биелэлт | `fills`-д ил; позиц нь Alpaca-ийн мэдээлснээр, локал тооцоогүй | §5.3 |
| Grace дуусахад процесс унтарсан байсан | Сэрэхдээ `halted` | §6.3 |
| Kill switch, submit хоёр уралдсан | Execution нь submit-ийн ӨМНӨ төлөвийг дахин шалгана | §10 |

---

## 23. Энэ шатны ил таамаглалууд

Эдгээр нь SPEC-ийн A-1…A-9-ийг **өргөтгөсөн, зөрчөөгүй** загварын шийдвэрүүд.
Эсэргүүцвэл LLD_APPROVE дээр өөрчилнө.

| # | Таамаг | Шалтгаан |
|---|---|---|
| D-1 | Position-ийн origin = тухайн symbol дээрх ХАМГИЙН СҮҮЛИЙН filled локал order (§11.1). Олон origin-ийн жинлэсэн задаргаа v1-д БАЙХГҮЙ. | Alpaca position-д client_order_id өгдөггүй. Жинлэсэн задаргаа нь `fills`-ийн бүрэн түүх шаардана — үнэ цэнэ нь v1-д хязгаарлагдмал. UI нь холимог тохиолдлыг ил тэмдэглэнэ. |
| D-2 | Provider солилт нь **дараагийн** session-д хүчинтэй; идэвхтэй харилцан яриа хуучнаар дуусна. | «Нэг шийдвэр хоёр модель» нь `agent_decisions.provider`-ыг утгагүй болгоно. |
| D-3 | Гарын order-ийн «Risk-ийн урьдчилсан үнэлгээ» нь тусдаа dry-run endpoint биш, 409/422 хариунаас гарна. | Хоёр дахь үнэлгээний зам нь хоёр эх үүсгэнэ — урьдчилсан үнэлгээ ба бодит шийдвэр зөрж болно. |
| D-4 | `GROUNDING_TOLERANCE`-ийн v1 санал = `0` (яг таарна). | Тэвчээр нь «ойролцоо тоо»-ны цонх. Config тул operator сулруулж чадна, гэхдээ ИЛ. |
| D-5 | WS нь нэг холболт, олон logical суваг. Суваг тус бүрийн тусдаа socket БАЙХГҮЙ. | Нэг холболтын staleness илрүүлэлт нэг газар. Backpressure бодлого (§AsyncAPI) нь `system`-ийг хамгаална. |
| D-6 | Frontend-ийн API төрөл нь `contracts.yaml`-ээс **үүсгэгдэнэ**, гараар бичигдэхгүй. | Гэрээ зөрвөл build унана — «баримт хуучирсан» гэсэн чимээгүй зөрүү үүсэхгүй. |
| D-7 | `Idempotency-Key` нь клиентээс ЗААВАЛ (header `required`). | Сервер үүсгэвэл давхар илгээлтийг илрүүлэх боломж алга болно. |
| D-8 | Grace-ийн scheduler нь `date` job + 10 секундын `interval` job ХОЁУЛАА. | `date` нь нарийвчлал, `interval` нь restart-ийн дараах нөхөлт. Давхардал идемпотент. |

---

## 24. Нээлттэй асуулт — энэ шатны байдал

SPEC-ийн OQ-1…OQ-8 нь нээлттэй хэвээр, бүгд SPEC_APPROVE-ийн гарц. Энэ
загвар тэдгээрийг **блоклогчгүй** болгосон: тус бүрд нь суудал бэлэн.

| OQ | Энэ загвар дахь суудал | Хариу өөрчлөх зүйл |
|---|---|---|
| OQ-1 (kill switch позиц хаах уу) | §15.1 — хаахгүй (A-2) | Хаах бол §15.1-д шинэ алхам, §22-т шинэ мөр. Бусад бүлэг хэвээр. |
| OQ-2 (10 config-ийн тоо) | §17.1 — анхдагчгүй талбар | Тоо нь `.env`-д. Загвар өөрчлөгдөхгүй. |
| OQ-3 (хэдэн provider adapter) | §12 — router нь N adapter-т нээлттэй | Adapter-ийн тоо нь `tasks.md` T-19…T-21-ийн хамрах хүрээ. |
| OQ-4 (netos template үү) | §3 — netos БИШ гэж үзэв | «Тийм» бол §3, §18 дахин бичигдэнэ; §4–§17 хэвээр. |
| OQ-5 (аль secrets manager) | §5.1 `key_ref` нь лавлагаа, брэнд-агностик | Тодорхой manager нь deploy-ийн нарийн ширийн. |
| OQ-6 (`HALTED` үед яаралтай гарц) | §6.1 — БАЙХГҮЙ (A-9) | Хэрэгтэй бол шинэ шилжилт биш, `halted`-д «зөвхөн хаах» онцгой зам — загварт ил нэмэгдэнэ. |
| OQ-7 (grace дууссаны дараа позиц) | §6.1 — нээлттэй үлдэнэ (A-7) | «Бүгдийг хаах» товч нь тусдаа, ил үйлдэл болж backlog-т. |
| OQ-8 (`WIND_DOWN_GRACE`-ийн утга, хуанли/арилжааны цаг) | §6.3 — хуанлийн цаг | Арилжааны цаг бол §6.4-ийн scheduler-т зах зээлийн хуанли нэмэгдэнэ. |

**Энэ шатнаас гарсан БЛОКЛОГЧ асуулт БАЙХГҮЙ.** Дээрх бүгд нь загварыг
өөрчлөхгүйгээр config эсвэл нэмэлт бүлгээр шийдэгдэнэ.

---

## 25. Хамрах хүрээнээс гадуур (энэ загварт ЗОРИУДААР байхгүй)

| Байхгүй зүйл | Шалтгаан |
|---|---|
| Multi-user, role/permission модель | Ганц operator (A-6). Одоо нэмэх нь ашиглагдахгүй абстракц. |
| Хоёр дахь broker adapter (FX г.м.) | `BrokerPort` нь нэмэлтийг БОЛОМЖТОЙ болгоно, гэхдээ v1-д нэг л хэрэгжүүлэлт. |
| Мессеж дараалал (Kafka/RabbitMQ) | Redis pub/sub нь ганц process, ганц operator-т хангалттай. |
| Kubernetes / микросервис задаргаа | Нэг deployable, нэг release tag. |
| Strategy DSL / plugin систем | Стратеги нь Research Agent-ийн prompt + whitelist параметр. Шинэ стратеги нэмэх нь код өөрчлөлт — зориуд. |
| Жинлэсэн origin задаргаа | D-1. Backlog. |
