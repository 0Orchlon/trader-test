<!-- PERSONAL-3 · code-review · CODE_REVIEW · 2026-09-17 -->

# PERSONAL-3 — Кодын хяналтын тайлан (CODE_REVIEW)

**Ажил:** PERSONAL-3 · **Салбар:** `issue/personal-3` · **Хянасан commit:** `b2ad438`
**Хяналтын суурь:** `docs/PERSONAL-3/lld.md` (LLD v1.0) §19-ийн 15 шалгах цэг
+ LLD-д ил бичигдсэн бусад механизмууд · `contracts/openapi.yaml`,
`contracts/asyncapi.yaml`, `contracts/tool-contract.v1.yaml`

**Дүгнэлт: УЛААН (өнгөрөхгүй).** §19-ийн 15 цэг бүгд хангагдсан, гэвч LLD-д
ил бичигдсэн гурван механизм кодод дутуу буюу гэрээтэй зөрчилдсөн (B-1…B-3).
Эдгээр нь зогсоох хаалга (kill switch / circuit breaker), нийтлэгдсэн WS
гэрээ, coverage gate-ийн хамрах хүрээ — гурвуулаа «буруу ногоон» үүсгэх
шинжтэй тул засварыг шаардав.

---

## 1. §19-ийн шалгах цэгүүд

| # | Шалгуур (LLD §19) | Үр дүн | Нотолгоо |
|---|---|---|---|
| 1 | `submit_order`-ийн дуудагч зөвхөн `app/execution` | ✅ | `tests/static/test_import_gates.py::test_r1_...` ажилласан; AST скан зөрчилгүй |
| 2 | `ValidatedOrder` нь `risk.evaluate()`-ээс л үүснэ | ✅ | Үүсгэлт зөвхөн `app/risk/agent.py:127`; `frozen=True, slots=True` (`app/broker/models.py:181`) |
| 3 | `orders.origin` `NOT NULL`, анхдагчгүй | ✅ | `app/models.py` — `nullable=False`, `default` байхгүй, check constraint-тай |
| 4 | `system_state` Postgres-д, startup УНШИНА | ✅ | `app/system/state.py::ensure_initialised` — мөр байхгүй бол `halted`, эхлүүлэхгүй |
| 5 | `halted → winding_down` шилжилт БАЙХГҮЙ | ✅ | `_validate()` → `InvalidTransition("already_halted")` |
| 6 | `activate` нь breaker метрикийг ДАХИН хэмжинэ | ✅ | `app/api/routes_system.py::post_activate` → `CircuitBreaker.tripped()`, туг уншихгүй |
| 7 | Гарын order `agent_decisions`-д мөр үүсгэхгүй | ✅ | `routes_orders.py`-д `AgentDecision` огт хэрэглэгдээгүй |
| 8 | Position-ийн origin олдохгүй бол `external` | ✅ | `app/api/attribution.py::position_origins` → `EXTERNAL`, «ойрын order»-т наахгүй |
| 9 | `tool_calls` бичилт нь LLM-д хариу буцахаас ӨМНӨ | ✅ | `app/agents/gateway.py::dispatch` — `call.response` + `commit()` нь `envelope()`-ээс өмнө |
| 10 | Tool result бүрд `system_state`, schema-д `required` | ✅ | `gateway.envelope()`; `contracts/tool-contract.v1.yaml:35` `required: [... system_state, ok]` |
| 11 | Grounding унавал Risk хүртэл ОЧИХГҮЙ | ✅ | `app/agents/tools.py::propose_order` — `grounding_failed` салаа `evaluate()`-д хүрэхгүй |
| 12 | `audit_log`-д `UPDATE`/`DELETE` татгалзах trigger | ⚠ хэсэгчилсэн | `migrations/postgres_append_only.sql` — UPDATE/DELETE RULE байна; **TRUNCATE-ыг хаасан гурав дахь хамгаалалт байхгүй** (N-1) |
| 13 | §7-ийн 10 хязгаар кодод анхдагч утгагүй | ✅ | `app/config/settings.py` — анхдагчгүй талбарууд + `REQUIRED_LIMIT_FIELDS` тест |
| 14 | Нэг хүснэгтэд хоёр `source` зэрэг харагдахгүй | ⚠ шалгагдаагүй | Backend талд хориг бий (`tests/integration/test_read_api.py`); **frontend талд энэ тестийг олсонгүй** (N-5) |
| 15 | Settings дэлгэцэд хязгаар засах талбар байхгүй | ✅ | `src/features/settings/SettingsPage.tsx` — ганц ч input байхгүй, зөвхөн унших |

---

## 2. Зогсоох шаардлагатай зөрчил (B)

### B-1 · Төлөвийн шилжилтэд LLD §6.2-ийн мөрийн lock байхгүй

`app/system/state.py::transition()` нь LLD §6.2-ийн 1-р алхам
(`SELECT ... FOR UPDATE`)-ыг хийхгүй. Репо даяар `with_for_update` огт
хэрэглэгдээгүй. Шилжилт нь «уншаад шалгаад INSERT» болсон тул зэрэгцээ
дуудагчид хоорондоо цуваагүй.

**Бодит унах хувилбар.** `enforce_breaker` job 5 секунд тутам, API-ийн
`activate` хүсэлттэй нэг event loop дээр ажиллана:

1. `CircuitBreaker.enforce()` метрик хэмжиж `tripped` авна (await цэгүүд).
2. Тэр хооронд `POST /system/activate` шалгалтаа дуусган `active` мөр INSERT.
3. `enforce()` үргэлжилж `machine.current()`-ээр **хуучин** `halted`-ыг уншина
   (эсвэл шинэ `active`-ыг уншаад transition хийх боловч дараалал нь
   баталгаагүй) → унасан метриктэй атлаа систем `active` хэвээр үлдэх цонх
   үүснэ.

Мөн `StateMachine.current()`-ийн 200ms кэш нь `_validate()`-ийн оролт болдог
тул нэг хүсэлтийн дотор kill switch-ийн дараах төлөвийг хожимдуулж уншиж
болно (`ExecutionAgent.submit`-ийн TOCTOU дахин шалгалт үүнтэй нэг
`StateMachine` объект хуваалцана).

**Юуг зөрчиж байна:** LLD §6.2 (транзакцийн 5 алхмын 1 дэх нь), AC-14/AC-15.
**Засвар:** `transition()`-ийн эхэнд `system_state`-ийн хамгийн их `seq`-тэй
мөрийг `with_for_update()`-ээр уншиж, кэшийг тойрох; зэрэгцээ `activate` ↔
`breaker` уралдааны тест нэмэх.

### B-2 · WS-ийн бодит payload нь `contracts/asyncapi.yaml`-тай зөрчилдөж байна

Нийтлэгдсэн AsyncAPI гэрээ ба хэрэгжүүлэлт гурван суваг дээр зөрөв. Аль ч
тест AsyncAPI-г шалгахгүй (`contracts/verify-mock.mjs` нь зөвхөн OpenAPI-ийн
prism дуурайлт, `tests/static/test_contract_coverage.py` нь зөвхөн REST зам).

| Гэрээ | Шаардсан | Код юу илгээж байна |
|---|---|---|
| `SystemEvent` `required: [seq, event, ts]` | `event`, `ts` | `app/system/state.py` нь `"type": "state_changed"` (талбарын нэр ӨӨР), `ts` байхгүй; `app/api/ws.py` heartbeat-д `ts` байхгүй |
| `SystemEvent.event` enum | `state_changed … heartbeat` | `app/stream/ingest.py` нь enum-д байхгүй `stream_stale` / `stream_live` илгээнэ |
| `OrderEvent` `required: [seq, order_id, status, origin, ts, source]` | дээрх талбарууд дээд түвшинд | `routes_orders.py` / `routes_approvals.py` нь `{event, order:{...}}`, `ingest.py` нь `{event, client_order_id, ...}` — `origin`, `source`, `order_id` дээд түвшинд алга |
| `DecisionEvent` `required: [... agent, model, grounded_in, ts]` | дээрх талбарууд | `agents/tools.py` нь `{event, decision_id, symbol, outcome, provider}` — `agent`, `model`, `grounded_in`, `ts` алга |
| LLD §9.4 «→ WS system: `approval_created`» | ESCALATE үед нийтлэх | Репо даяар `approval_created` нийтлэгддэггүй (зөвхөн asyncapi-д тодорхойлогдсон) |

Өнөөдөр UI нь зөвхөн `channel`-аар invalidate хийдэг тул дэлгэц эвдрэхгүй —
**гэхдээ гэрээгээр бичигдсэн хэрэглэгч эвдэрнэ**, ба гэрээ нь одоо
хэрэгжүүлэлтийн бус баримт болж хоцорч байна (LLD D-6-ийн «чимээгүй зөрүү
үүсэхгүй» зорилгын эсрэг).

**Засвар:** payload-уудыг гэрээнд нийцүүлэх (`type` → `event`, `ts` нэмэх,
захиалгын/шийдвэрийн талбаруудыг дээд түвшинд гаргах, `approval_created`
нийтлэх), эсвэл AsyncAPI-г өөрчлөх шийдвэрийг LLD-д буцааж бичих. Аль ч
тохиолдолд asyncapi-ийн schema-аар payload-ыг шалгах тест нэмэх — одоо
энэ гадаргуу огт хаалгагүй.

### B-3 · Coverage gate нь `app/risk/**`-ийн нэг хэсгийг хэмжихгүй

LLD §18.3: «`app/risk/**` — 100% line + branch». `tests/coverage_gate.py`-ийн
`risk` бүлэг нь зөвхөн `agent.py`, `rules.py`, `limits.py`-г нэрлэсэн тул
`app/risk/breaker.py` gate-ээс гадуур үлдэж, хэмжилтээр **92%** (4 мөр, 2
салаа хамрагдаагүй) байна. Breaker бол автомат `halted` үүсгэдэг бүрэлдэхүүн
— яг энэ бүлэг 100% шаардлагатай гэж загварчлагдсан.

**Засвар:** gate-ийн prefix-ийг `app/risk/` болгож, breaker-ийн хамрагдаагүй
салаануудад тест нэмэх (эсвэл LLD §18.3-ыг өөрчлөх шийдвэрийг ил бичих).

---

## 3. Зогсоолт биш, гэхдээ засах ёстой ажиглалт (N)

| # | Ажиглалт | Байршил | LLD-ийн иш |
|---|---|---|---|
| N-1 | `TRUNCATE` бодитоор хаагдаагүй: RULE нь TRUNCATE-ыг барихгүй, `REVOKE TRUNCATE ... FROM PUBLIC` нь эзэн/superuser-т нөлөөгүй. `BEFORE TRUNCATE` trigger хэрэгтэй. Мөн `DO INSTEAD NOTHING` нь UPDATE-ыг **чимээгүй** залгина, алдаа буцаахгүй. | `migrations/postgres_append_only.sql` | §5.7 «гурван RULE/trigger нь UPDATE, DELETE, TRUNCATE-ыг татгалзана» |
| N-2 | Wind-down-ийн `date` job бүртгэгддэггүй — зөвхөн 10 секундын `interval`. Grace-ийн нарийвчлал ±10s болж доройтов. | `app/system/scheduler.py` (`add_job` ×4, `DateTrigger` алга) | §6.4, D-8 «`date` job + `interval` job ХОЁУЛАА» |
| N-3 | `DAILY_LOSS_LIMIT` нь **сөрөг** байх ёстой гэсэн далд гэрээтэй (`r8`: `pnl > limit`, breaker: `pnl <= limit`). `.env.example`-д `-2000.00` гэж бичсэн ч validator байхгүй — эерэг утга оруулбал бүх order татгалзаж, breaker шууд унана (fail-closed боловч чимээгүй бүтэн түгжээ). | `app/config/settings.py`, `app/risk/rules.py:r8` | §17.1 (хязгаар нь ил бодлого) |
| N-4 | `orders.account_id` нь `nullable`, `decision_id`/`approval_id`-д FK тавигдаагүй; загварт `not null fk accounts`, `fk agent_decisions`, `fk approvals` гэж заасан. Мөн загварт байхгүй `filled_qty`, `idempotency_key`, `request_hash`, `failure_reason` баганууд, `breaker_events` (11 дэх) хүснэгт нэмэгдсэн — хэрэгцээтэй боловч §5-ийн «хамгийн бага хангалттай олонлог»-т буцааж бичигдээгүй. | `app/models.py` | §5.2, §5 толгой |
| N-5 | Нэг хүснэгтэд хоёр `source` шошго гарахыг хориглох frontend тест байхгүй. `DecisionsPage`-ийн tool call хүснэгт нь мөр бүрд `call.source`-ыг хэвлэдэг тул backtest runner холбогдмогц энэ хориг бодитоор шаардагдана (одоо `get_backtest_result` нь `no_data` тул зөрчил ҮҮСЭХГҮЙ). | `frontend/src/features/decisions/DecisionsPage.tsx:194` | §16.2, §19-ийн 14 |
| N-6 | «Унтраах бэлтгэл»-ийн асуултын текст UI-д хатуу кодлогдсон (`WIND_DOWN_PROMPT`). §16.3 «UI-д хатуу кодлохгүй» гэсэн ч §8.4 нь баталгаажуулалтыг зөвхөн гурван үйлдэлд заасан (wind-down тэдний дунд байхгүй) — LLD-ийн дотоод зөрүү. Шийдвэрийг нэг тал руу бичих хэрэгтэй. | `frontend/src/app/StateBar.tsx` | §16.3 vs §8.4 |
| N-7 | `npm test` нь Windows checkout дээр (`core.autocrlf=true`) `check:api` алхам дээр унана: үүсгэсэн файл LF, commit хийгдсэн нь CRLF. Агуулга нь ТЭНЦҮҮ (`tr -d '\r'`-ийн дараа зөрүүгүй), CI (ubuntu) ногоон. `.gitattributes` (`*.ts text eol=lf`) эсвэл харьцуулалтыг нормчлох нь хангалттай. | `frontend/scripts/check-generated.mjs` | §16.1 (codegen) |

---

## 4. Гүйцэтгэсэн шалгалт (эмпирик)

| Гадаргуу | Команд | Үр дүн |
|---|---|---|
| backend | `pytest -q` (Python 3.12.13, uv venv) | **323 passed** |
| backend | `pytest -q --cov=app --cov-report=term` | **323 passed**, coverage gate ногоон; нийт 89%, `app/risk/agent.py` ба `rules.py` 100%, `app/risk/breaker.py` 92% (B-3) |
| frontend | `npm run lint` · `npm run typecheck` · `npx vitest run` | lint ✓ · typecheck ✓ · **50 passed** |
| frontend | `npm test` (бүтэн gate) | **УНАВ** — `check:api` (шалтгаан: CRLF, N-7; агуулгын зөрүү БАЙХГҮЙ) |

---

## 5. Шалгаж ЧАДААГҮЙ зүйлс (ил хамрах хүрээ)

Эдгээр нь «ногоон» биш — **шалгагдаагүй**:

1. **Postgres-ийн DDL хамгаалалт.** Тест SQLite дээр ажилладаг тул
   `migrations/postgres_append_only.sql`-ийн RULE/REVOKE огт ажиллаагүй.
   `audit_log`/`system_state`-ийн append-only байдал бодит Postgres дээр
   батлагдаагүй.
2. **Alpaca-тай бодит харилцаа** (paper ч, live ч). Бүх broker зам fake
   adapter-аар тестлэгдсэн; `LiveEgressGuard` нь дуудалт болоогүйг л
   баталдаг.
3. **Browser түвшний баталгаажуулалт.** Өмнөх шат Playwright-ийн оронд
   vitest + jsdom ашигласныг ил мэдүүлсэн; §16.2-ийн «хоёр source нэг
   хүснэгтэд» хориг browser-т шалгагдаагүй (N-5).
4. **Backtest engine байхгүй** тул `source=backtest`-ийн бүх зам (mode
   заалт, холимог хориг, tool result) бодит өгөгдлөөр шалгагдаагүй.
5. **30+ хоногийн paper proving window** (T-41) ба `ci/reproducible-build.sh`
   энэ хяналтын явцад ажиллуулагдаагүй.
6. **Ачаалал/хугацааны хэмжилт** (AC-14-ийн 1 секундын төсөв) бодит
   Redis + олон клиенттэй орчинд хэмжигдээгүй.

---

## 6. Дараагийн алхамд шаардлагатай

B-1, B-2, B-3-ыг засаад дахин хяналтад оруулах. N-1…N-7 нь тухайн засварын
хамт эсвэл тусдаа task болж бүртгэгдэх боломжтой. §19-ийн 15 цэгийн 13 нь
бүрэн ногоон, 12 ба 14 дугаар цэг нь хэсэгчилсэн (N-1, N-5).
