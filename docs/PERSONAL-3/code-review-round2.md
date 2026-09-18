<!-- PERSONAL-3 · code-review · CODE_REVIEW · 2026-09-17 -->

# PERSONAL-3 — Кодын хяналт, 2-р тойрог (CODE_REVIEW)

**Ажил:** PERSONAL-3 · **Салбар:** `issue/personal-3` · **Хянасан commit:** `e467e8e`
**Хяналтын суурь:** `docs/PERSONAL-3/lld.md` (LLD v1.0) — §19-ийн 15 шалгах цэг
болон LLD-д ил бичигдсэн бусад механизмууд. Гэрээ: `contracts/openapi.yaml`,
`contracts/asyncapi.yaml`, `contracts/tool-contract.v1.yaml`.
**Хамрах хүрээ:** 1-р тойргийн B-1…B-3, N-1…N-7 засварыг баталгаажуулах +
хянагчийн буцаасан дөрвөн шаардлагын гадаргуу (attribution, гарын арилжаа,
wind-down/activate товч) LLD-тэй тулгах.

**Дүгнэлт: УЛААН (өнгөрөхгүй).** 1-р тойргийн бүх засвар баталгаажив, гурван
гадаргуу ногоон. Гэвч LLD §16.4 ба §16.5-д ил бичигдсэн хоёр элемент кодод
БАЙХГҮЙ, гарын арилжааны idempotency нь давтсан order-ыг чимээгүй залгиж
«амжилттай» гэж мэдээлж байна. Гурвуулаа хянагчийн ЯГ энэ удаа нэмсэн
гадаргуун дээр тул зогсоов.

---

## 1. Баталгаажуулсан засварууд (1-р тойрог)

| # | Шалгуур | Үр дүн | Нотолгоо |
|---|---|---|---|
| B-1 | Төлөвийн шилжилтэд мөрийн lock | ✅ | `app/system/state.py::locked_state_stmt()` → `with_for_update()`; `transition()` нь кэшийг ТОЙРЧ түгжигдсэн мөрийг уншина |
| B-2 | WS payload ↔ asyncapi | ✅ | `EventBus.stamp()` (`seq`+`ts` нэг газраас), `serializers.order_event()` дээд түвшний талбарууд, `DecisionEvent`-д `agent`/`model`/`grounded_in`, ESCALATE үед `approval_created`. Хаалга: `tests/asyncapi_schema.py::ValidatingEventBus` нь `conftest`-ийн `bus` fixture тул БҮХ нийтлэл шалгагдана; bus-гүй хоёр frame (snapshot, heartbeat) нь `test_ws_contract.py`-д |
| B-3 | Coverage gate `app/risk/**` | ✅ | `tests/coverage_gate.py` нь prefix-ээр (`app/risk/`); хэмжсэн: `agent.py`/`breaker.py`/`limits.py`/`rules.py` бүгд **100%**, gate ногоон |
| N-1 | TRUNCATE хаалт | ✅ | `migrations/postgres_append_only.sql` — RULE устав, `BEFORE UPDATE/DELETE/TRUNCATE` trigger нь `RAISE EXCEPTION` |
| N-2 | Wind-down `date` job | ✅ | `scheduler.schedule_wind_down_deadline()` (`DateTrigger`) нь `routes_system.post_wind_down`-оос дуудагдана; 10s `interval` нөөц хэвээр |
| N-3 | `DAILY_LOSS_LIMIT` сөрөг validator | ✅ | `config/settings.py::_negative_loss_limit` |
| N-4 | `orders`-ийн FK | ✅ | `decision_id` → `agent_decisions.id`, `approval_id` → `approvals.id` |
| N-5 | Frontend-ийн «нэг хүснэгт = нэг source» | ✅ | `lib/source.ts` + `DecisionsPage.test.tsx`-ийн хоёр кейс |
| N-6 | Wind-down-ийн баталгаажуулалт | ⚠ | Шийдвэр гаргасан (доорх N-1) — гэхдээ LLD-д буцааж бичигдээгүй |
| N-7 | CRLF-ийн худал улаан | ✅ | `npm test` Windows checkout дээр ногоон |

## 2. §19-ийн 15 шалгах цэг

| # | Шалгуур | Үр дүн | Нотолгоо |
|---|---|---|---|
| 1 | `submit_order`-ийн дуудагч зөвхөн `app/execution` | ✅ | `tests/static/test_import_gates.py::test_r1_...` (AST скан) |
| 2 | `ValidatedOrder` нь `risk.evaluate()`-ээс л үүснэ | ✅ | Үүсгэлт зөвхөн `app/risk/agent.py`; escalate-ийн салаа ч `evaluate(..., escalation_confirmed=True)`-ээр дахин үнэлүүлнэ |
| 3 | `orders.origin` `NOT NULL`, анхдагчгүй | ✅ | `app/models.py` + check constraint |
| 4 | `system_state` Postgres-д, startup УНШИНА | ✅ | `main.py` lifespan → `ensure_initialised()`; мөр байхгүй бол `halted` |
| 5 | `halted → winding_down` БАЙХГҮЙ | ✅ | `_validate()` → `InvalidTransition("already_halted")` |
| 6 | `activate` нь breaker метрикийг ДАХИН хэмжинэ | ✅ | `routes_system.post_activate` → `CircuitBreaker.tripped()`, туг уншихгүй |
| 7 | Гарын order `agent_decisions`-д мөр үүсгэхгүй | ✅ | `routes_orders.py`-д `AgentDecision` огт хэрэглэгдээгүй |
| 8 | Origin олдохгүй бол `external` | ✅ | `attribution.position_origins()` → `EXTERNAL`, «ойрын order»-т наахгүй |
| 9 | `tool_calls` бичилт нь хариунаас ӨМНӨ | ✅ | `gateway.dispatch` — `call.response` + `commit()` нь `envelope()`-ээс өмнө |
| 10 | Tool result бүрд `system_state`, schema-д `required` | ✅ | `gateway.envelope()` + `tool-contract.v1.yaml` |
| 11 | Grounding унавал Risk хүртэл ОЧИХГҮЙ | ✅ | `agents/tools.py::propose_order` — `grounding_failed` салаа `evaluate()`-д хүрэхгүй |
| 12 | `audit_log`-д UPDATE/DELETE татгалзах trigger | ✅ | N-1-ийн засвар (TRUNCATE ч хамрагдав) |
| 13 | §7-ийн 10 хязгаар анхдагчгүй | ✅ | `settings.py` + `REQUIRED_LIMIT_FIELDS` |
| 14 | Нэг хүснэгтэд хоёр `source` харагдахгүй | ✅ | Backend `MixedSourceError`, frontend `distinctSources` + тест |
| 15 | Settings дэлгэцэд хязгаар засах талбар байхгүй | ✅ | `SettingsPage.tsx` — ганц ч input/onChange байхгүй |

**§19 бүрэн хангагдсан.** Доорх зогсоолтууд нь §19-ээс ГАДУУР, гэхдээ LLD-д
ил бичигдсэн элементүүд (1-р тойргийн B-1…B-3-тай ижил үндэслэл).

---

## 3. Зогсоох шаардлагатай зөрчил (B)

### B-1 · «Холимог origin» нь UI-д огт гарахгүй (LLD §16.4, §11.1)

LLD §11.1 нь «нэг symbol дээр олон origin» тохиолдлыг **бүрэн бус оноолт**
гэж ил хүлээн зөвшөөрөөд, түүний НӨХӨН ТӨЛБӨРИЙГ UI дээр тавьсан:

> §16.4 — «§11.1-ийн холимог тохиолдолд symbol нь `холимог origin` тэмдэгтэй,
> **бүх холбогдох origin-ийн картад харагдана — далдлахгүй**.»

Кодод:

1. `app/api/attribution.py::Attribution.mixed` тооцоологддог, гэвч
   `build_groups()` (= `GET /attribution`-ийн бие) түүнийг ОРХИНО:
   `SymbolRow`-д ийм талбар байхгүй. Symbol нь ЗӨВХӨН хамгийн сүүлийн
   fill-ийн origin-ийн картад ордог — «бүх холбогдох картад» гэдэг биелэхгүй.
2. `serializers.position_json()` нь `origin_mixed`-ийг илгээдэг ч энэ талбар
   `contracts/openapi.yaml`-ийн `Position` schema-д **байхгүй**. Frontend-ийн
   төрөл нь гэрээнээс үүсдэг (LLD D-6) тул UI түүнийг харах боломжгүй;
   `origin_mixed` нь репо даяар хэрэглэгддэггүй (зөвхөн serializer-т).
3. `AttributionPage.tsx`, `DashboardPage.tsx`-д «холимог» тэмдэг БАЙХГҮЙ.

**Бодит унах хувилбар.** AAPL-ийг Research Agent 10 ширхэг авсан, дараа нь
operator гараар 5 ширхэг нэмсэн. `/attribution` нь AAPL-ийг ЗӨВХӨН
«Гараар (operator)» картад харуулна; AI-ийн картад AAPL огт байхгүй. Хянагчийн
шаардсан «AI юунд арилжаа хийж байгааг харах» нь яг энэ тохиолдолд ХУДАЛ
хариу өгнө — далдлахгүй гэсэн загварын заалтын эсрэг.

**Юуг зөрчиж байна:** LLD §16.4 (3-р тэмдэглэл), §11.1-ийн нөхөн төлбөр, OP-11.
**Засвар:** `SymbolRow`/`AttributionEnvelope`-д `origin_mixed` (эсвэл
`mixed_origins`) нэмэх, холимог symbol-ыг холбогдох БҮХ бүлэгт гаргах,
`Position` schema-д `origin_mixed` бүртгэх, UI-д тэмдэг + тест.

### B-2 · Гарын ticket дээр notional нь quote-оос тооцогдохгүй, `stale` тэмдэг байхгүй (LLD §16.5)

LLD §16.5 «Илгээхээс өмнө» гэсэн эхний шаардлага:

> «**Тооцоолсон notional** (сүүлийн quote-оор, `stale` бол ил тэмдэгтэй).»

Кодод `ManualTicketPage.tsx`:

```ts
const notional = useMemo(() => {
  if (!qty || !limitPrice) return null;
  return multiply(qty, limitPrice);
}, [qty, limitPrice]);
```

- Эх сурвалж нь quote БИШ, гараар бичсэн `limit_price`.
- `market` ба `stop` order-т `limitPrice` талбар нь `disabled` тул notional
  нь ҮРГЭЛЖ `null` → дэлгэцэд `—`. Баталгаажуулалтын modal-д ч дүн гарахгүй
  (`{notional ? ... : ''}`).
- `stale` тэмдэг хаана ч байхгүй; `contracts/openapi.yaml`-д quote унших
  endpoint огт байхгүй тул энэ шаардлагыг одоогийн гэрээгээр хэрэгжүүлэх
  боломж ч алга.

**Бодит унах хувилбар.** Operator `market` төрлөөр 1000 ширхэг AAPL бичээд
«Илгээх» дарна. Илгээхээс өмнө ямар ч мөнгөн дүн харагдахгүй; R9 хэтэрсэн
тохиолдолд гарах баталгаажуулалтын цонхонд ч дүн байхгүй («Авах 1000 ш AAPL»
гэхээс өөр мэдээлэлгүй). §16.5-ийн «илгээхээс өмнө хэмжээгээ харах» хаалга
market order дээр бүрэн ажиллахгүй байна — энэ нь `plan.md` P-8-ийн
dark-pattern хоригийн эсрэг тал.

**Юуг зөрчиж байна:** LLD §16.5-ийн 1-р шаардлага.
**Засвар:** гэрээнд quote унших endpoint нэмж (эсвэл `/positions`-той адил
нэг дуудлагаар) сүүлийн quote-оор notional бодох, `stale` тугийг ил гаргах;
market/stop order-т ч дүн харагдах тест.

### B-3 · Давтсан гарын order чимээгүй залгигдаж, UI «Хүлээн авав» гэж мэдээлнэ

`ManualTicketPage.tsx::idempotencyKeyFor(body)` нь `Idempotency-Key`-ийг
ЗӨВХӨН биеийн агуулгаас гаргана. LLD §9.2-ийн дедупликацийн дүрэм:

> «Ижил key + ижил талбар → ижил `client_order_id` → байгаа order-ыг
> буцаана (шинэ submit БАЙХГҮЙ).»

Хоёуланг нийлүүлбэл: **ижил бие = мөнхөд ижил key**. Тиймээс operator ижил
параметртэй order-ыг ХЭЗЭЭ Ч хоёр дахь удаа илгээж чадахгүй. `routes_orders`
нь 202 + ХУУЧИН order-ыг буцаана, UI нь `setSubmitted(...)`-аар ногоон
«Хүлээн авав — `client_order_id` …» гэж харуулна.

**Бодит унах хувилбар.** Operator AAPL-ийг 221.50 limit-ээр 10 ширхэг авав.
Хэдэн минутын дараа ижил үнээр дахин 10 ширхэг нэмэхээр ижил маягтыг дахин
илгээв. Шинэ order үүсэхгүй, Alpaca руу дуудалт явахгүй, гэтэл дэлгэц
«Хүлээн авав» гэж баталгаажуулна. Operator позицоо 20 ширхэг гэж бодох
боловч 10 хэвээр — худал баталгаажуулалт.

**Юуг зөрчиж байна:** LLD D-7 («`Idempotency-Key` нь клиентээс» — оролдлогыг
таних зорилготой) + §9.2-ийн дедуп семантик. Мөнгө алдагдуулах чиглэл БИШ
ч, «буруу ногоон» хэлбэр.
**Засвар:** key-д оролдлогын nonce нэмэх (баталгаажуулалтын хоёр дахь
дуудлагад ТОГТМОЛ үлдэж, амжилттай илгээлтийн дараа шинэчлэгдэнэ), эсвэл
хариу нь давхардсан гэдгийг ил буцааж UI-д «энэ нь өмнөх order» гэж
харуулах. Тест: ижил маягтыг хоёр удаа илгээхэд хоёр order (эсвэл ил
«давхардсан» мэдэгдэл).

---

## 4. Зогсоолт биш ажиглалт (N)

| # | Ажиглалт | Байршил | Иш |
|---|---|---|---|
| N-1 | Wind-down-ийн баталгаажуулалтыг хасах шийдвэр код ба `code-review-fixes.md`-д л бий; репо доторх `docs/PERSONAL-3/lld.md` §16.3 нь «Унтраах бэлтгэл» товчинд асуултын текстийг ХЭВЭЭР заасан. Дараагийн агент зөвхөн репог хардаг тул баримт ↔ код зөрүүтэй үлдэнэ. | `docs/PERSONAL-3/lld.md:914` | §16.3 |
| N-2 | `ExecutionAgent.submit`-ийн TOCTOU дахин шалгалт нь `machine.current()`-ийн 200ms кэшийг хуваалцана (route нь ижил объект дээр аль хэдийн уншсан). B-1-ийн засвар нь зөвхөн `transition()`-д кэш тойрохыг нэмсэн. Загварын кэш нь ил зөвшөөрөгдсөн тул зөрчил биш, гэхдээ §10-ийн «ДАХИН шалгана» нь тэр цонхонд утгагүй болно. | `app/execution/agent.py`, `app/system/state.py` | §10, §6.2 |
| N-3 | `halted`/`winding_down` дээр эрт татгалзсан санал `grounding={"passed": true, "checked_claims": 0}` гэж бүртгэгдэнэ — grounding огт АЖИЛЛААГҮЙ атлаа «дамжсан» гэж үлдэнэ. Decision Log дээр шалгагдаагүйг шалгагдсан мэт харуулна. | `app/agents/tools.py::_rejected` | §13, хавсралт 10 («мэдэхгүйг мэднэ болгохгүй») |
| N-4 | `pyproject.toml` нь `requires-python = ">=3.12"` гэсэн ч `sqlalchemy==2.0.36` нь Python 3.13/3.14 дээр импортын үед унана (`TypeError: descriptor '__getitem__' requires a 'typing.Union' object`). CI нь 3.12 тул ногоон; локал 3.14 дээр 16 collection error. Дэмжсэн муж нь бодит биш. | `backend/pyproject.toml`, `ci/github-workflow-ci.yml` | §3, lockfile pin |
| N-5 | `origin_mixed` нь backend-ээс гарч байгаа боловч `openapi.yaml`-д бүртгэлгүй. Одоогийн тестүүд хариуны НЭМЭЛТ талбарыг шалгадаггүй тул гэрээнээс гадуур талбар чимээгүй нийтлэгдэж байна (B-1-ийн нэг хэсэг, гэхдээ гэрээний эрүүл ахуйн хувьд тусад нь). | `app/api/serializers.py:41` | D-6 |

---

## 5. Хэмжсэн баримт (энэ тойргийн ажиллуулалт)

| Гадаргуу | Команд | Үр дүн |
|---|---|---|
| contracts | `npm test` | ✅ lint + bundle шалгалт + `verify:mock` (10 зам, 5 үл хөдлөх дүрэм) |
| backend | `pytest -q` (Python 3.12, `requirements.lock`) | ✅ **342 passed** |
| backend | `pytest --cov=app --cov-report=term` | ✅ **coverage gate: ногоон**; `app/risk/*` бүгд **100%**, `app/execution/agent.py` 100%, `routes_orders.py` 95%, `approvals` ≥96% |
| frontend | `npm test` | ✅ `check:api` + eslint + tsc + **52 passed** |

## 6. Шалгаагүй зүйлс (ил хамрах хүрээ)

- **Бодит Postgres.** Append-only trigger-ууд зөвхөн статик тестээр
  (`tests/static/test_append_only_sql.py`) баригдаж байна; бодит DDL
  ажиллуулаагүй. SQLite дээр `FOR UPDATE` хаягддаг тул мөрийн lock-ийн
  бодит цуваалалт ч шалгагдаагүй.
- **Бодит Alpaca** (paper ч, live ч) — `LiveEgressGuard` нь дуудалтыг
  хориглодог; adapter нь зөвхөн fake-ээр шалгагдсан.
- **Browser түвшний assert** (Playwright). Frontend тест нь jsdom дээр;
  §16.2-ийн «бүх route дээр төлөвийн заалт» нь браузерт шалгагдаагүй.
- **Backtest зам** — `get_backtest_result` нь `no_data`; холимог source-ийн
  бодит тохиолдол үүсэхгүй.
- **30 хоногийн paper proving window** — хугацааны шаардлага, энэ тойрогт
  хэмжигдэх боломжгүй.

---

## 7. Дүгнэлт

**УЛААН.** §19-ийн 15 цэг ба 1-р тойргийн 10 засвар бүгд баталгаажив, гурван
гадаргуу ногоон. Гэвч LLD §16.4 (холимог origin-ийг далдлахгүй) ба §16.5
(илгээхээс өмнөх notional) хоёр элемент хэрэгжээгүй, гарын order-ийн
idempotency нь худал баталгаажуулалт үүсгэж байна. Гурвуулаа хянагчийн энэ
удаа нэмсэн гадаргуу (attribution + гарын арилжаа) дээр тул засварыг шаардав.
