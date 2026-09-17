<!-- PERSONAL-3 · code-review · CODE_REVIEW · 2026-09-17 -->

# PERSONAL-3 — Кодын хяналт, 3-р тойрог (CODE_REVIEW)

**Ажил:** PERSONAL-3 · **Салбар:** `issue/personal-3` · **Хянасан commit:** `b7f28a0`
**Хяналтын суурь:** `docs/PERSONAL-3/lld.md` (LLD v1.0) — §19-ийн 15 шалгах цэг
болон LLD-д ил бичигдсэн бусад механизмууд. Гэрээ: `contracts/openapi.yaml`,
`contracts/asyncapi.yaml`, `contracts/tool-contract.v1.yaml`.
**Хамрах хүрээ:** 2-р тойргийн B-1…B-3, N-1…N-4 засварыг баталгаажуулах;
§19-ийн 15 цэгийг дахин шалгах; хянагчийн буцаасан гурван гадаргуу
(attribution, гарын арилжаа, wind-down/activate) ба LLD §15-ийн автомат
зогсоолтын механизмыг кодтой тулгах.

**Дүгнэлт: УЛААН (өнгөрөхгүй).** 2-р тойргийн бүх засвар баталгаажив, §19-ийн
15 цэг хангагдсан, гурван гадаргуугийн тест ногоон. Гэвч LLD §15.2-ийн дөрвөн
breaker метрикийн НЭГ нь — `api_error_rate` — үйлдвэрлэлийн кодод ЭХ СУРВАЛЖГҮЙ
бөгөөд `GET /system/state` болон «Идэвхжүүл»-ийн цонхонд «0.0000 · унаагүй»
гэж НОГООН харагдаж байна. Хэмжигдээгүй хамгаалалтыг хэмжигдсэн мэт харуулах
нь энэ шатны цорын ганц зогсоох шалтгаан.

---

## 1. Хэмжилт (энэ тойрогт өөрөө ажиллуулсан)

| Гадаргуу | Команд | Үр дүн |
|---|---|---|
| backend | `pytest -q --cov` (Python 3.12.13, `requirements.lock`) | **349 passed**, coverage gate ногоон, `app/risk/**` = 100% |
| frontend | `npm ci && npm test` (`check:api` + `lint` + `typecheck` + `vitest`) | **60 passed** (5 файл) |
| contracts | `npm ci && npm test` (`redocly lint` + `check:bundle` + `verify:mock`) | OK — 10 зам, 5 үл хөдлөх дүрэм |

`docs/PERSONAL-3/*` ба `artifacts/PERSONAL-3/*` хоёрын агуулга ИЖИЛ
(мөрийн төгсгөлөөс бусад ялгаагүй) — баримтын хоёр хуулбар зөрөөгүй.

---

## 2. Баталгаажуулсан засварууд (2-р тойрог)

| # | Шалгуур | Үр дүн | Нотолгоо |
|---|---|---|---|
| B-1 | Холимог origin | ✅ | `api/attribution.py::Attribution.pairs` + `build_groups()` нь холимог symbol-ыг БҮХ бүлэгт гаргана; `position_json` → `origin_mixed`; UI-д `MixedOriginBadge` (attribution мөр + dashboard позиц); гэрээнд `Position.origin_mixed` ба attribution мөрийн `origin_mixed` нь `required` |
| B-2 | Quote-оос notional | ✅ | `GET /market/quote/{symbol}` (`routes_read.get_quote`) — quote байхгүй бол 503, хуучирсныг `stale` тугаар ил; `ManualTicketPage` нь `qty × quote.last`, `quote-stale` badge-тай |
| B-3 | Оролдлого тутмын idempotency | ✅ | `idempotencyKeyFor(body, attempt)` — баталгаажуулалтын хоёр дахь дуудалт ижил key, шинэ илгээлт шинэ key; backend тал `_existing_for_key` + `request_hash` → 409 `idempotency_conflict` |
| N-1 | LLD §16.3-ийн хуучин асуулт | ✅ | LLD §16.3 «Унтраах бэлтгэл — Асуулт БАЙХГҮЙ»; `StateBar` нь wind-down дээр modal нээхгүй |
| N-2 | TOCTOU кэш | ✅ | `StateMachine.current(fresh=True)` нь кэш тойрно; `ExecutionAgent.submit` submit-ийн ӨМНӨ `fresh=True`-ээр уншина |
| N-3 | Ажиллаагүй grounding | ✅ | `tools._rejected()` → `{passed: false, not_run: true, checked_claims: 0}`; `DecisionsPage` нь «ажиллаагүй»-г саарлаар, «УНАСАН»-аас ТУСАД НЬ харуулна |
| N-4 | Python муж | ✅ | `pyproject.toml` → `requires-python = ">=3.12,<3.13"`; 3.12.13 дээр тест ногоон |

---

## 3. §19-ийн 15 шалгах цэг

| # | Шалгуур | Үр дүн | Нотолгоо |
|---|---|---|---|
| 1 | `submit_order`-ийн дуудагч зөвхөн `app/execution` | ✅ | `tests/static/test_import_gates.py::test_r1_...`; бодит дуудалт зөвхөн `execution/agent.py:88` |
| 2 | `ValidatedOrder` нь `evaluate()`-ээс л үүснэ | ✅ | `ValidatedOrder(` бүтэц зөвхөн `risk/agent.py:127`; escalate-ийн салаа ч `evaluate(..., escalation_confirmed=True)`-ээр дахин үнэлүүлнэ |
| 3 | `orders.origin` `NOT NULL`, анхдагчгүй | ✅ | `models.Order.origin` + `ck_orders_origin` |
| 4 | `system_state` Postgres-д, startup УНШИНА | ✅ | `main.py` lifespan → `ensure_initialised()`; мөргүй бол `halted/initial_deploy` |
| 5 | `halted → winding_down` БАЙХГҮЙ | ✅ | `StateMachine._validate` → `InvalidTransition("already_halted")` |
| 6 | `activate` нь breaker метрикийг ДАХИН хэмжинэ | ⚠ | `routes_system.post_activate` → `CircuitBreaker.tripped()` (туг уншихгүй) — **гэхдээ дөрвөн метрикийн нэг нь хоосон хэмжилт, B-1-ийг үз** |
| 7 | Гарын order `agent_decisions`-д мөр үүсгэхгүй | ✅ | `routes_orders.py`-д `AgentDecision` огт хэрэглэгдээгүй |
| 8 | Локал fill байхгүй бол `external` | ✅ | `attribution.EXTERNAL`; «ойрын order»-т наах логик БАЙХГҮЙ |
| 9 | `tool_calls` бичилт нь хариунаас ӨМНӨ | ✅ | `gateway.dispatch` — `call.response` + `commit()` нь `envelope()`-ээс өмнө |
| 10 | Tool result бүрд `system_state`, schema-д `required` | ✅ | `gateway.envelope()` + `tool-contract.v1.yaml:35` |
| 11 | Grounding унавал Risk хүртэл ОЧИХГҮЙ | ✅ | `tools.propose_order` — `grounding_failed` салаа `evaluate()`-д хүрэхгүй |
| 12 | `audit_log`-д UPDATE/DELETE/TRUNCATE татгалзах trigger | ✅ (статик) | `migrations/postgres_append_only.sql` — `RAISE EXCEPTION`. Бодит Postgres дээр ажиллуулж БАТЛААГҮЙ (§6-ийг үз) |
| 13 | §7-ийн 10 хязгаар анхдагчгүй | ✅ | `settings.py` + `REQUIRED_LIMIT_FIELDS` |
| 14 | Нэг хүснэгтэд хоёр `source` харагдахгүй | ✅ | Backend `MixedSourceError`, frontend `lib/source.ts` + `DecisionsPage` |
| 15 | Settings дэлгэцэд хязгаар засах талбар байхгүй | ✅ | `SettingsPage.tsx` — ганц ч `Input`/`onChange`/`Button` байхгүй |

---

## 4. ЗОГСООХ ЗӨРЧИЛ

### B-1 · `api_error_rate` breaker метрик нь ЭХ СУРВАЛЖГҮЙ, гэхдээ ногоон харагдана (LLD §15.2, AC-15, AC-16)

**Юу байгаа.** `app/risk/breaker.py` нь дөрвөн метрик хэмжиж, `GET
/system/state`-ийн `breaker_metrics[]`-д (мөн «Идэвхжүүл»-ийн modal-ийн
`BreakerMetrics`-д) гаргана. `api_error_rate` нь `breaker_events` хүснэгтээс
`kind='api_error'` мөрүүдийг уншина.

**Юу байхгүй.** Тэр мөрийг бичдэг үйлдвэрлэлийн код БАЙХГҮЙ.
`breaker.record(...)` нь бүх репо дээр ХОЁР л газраас дуудагдана —
`app/stream/ingest.py:139/141` (`order_reject`) ба `:215` (`ws_disconnect`).
`kind='api_error'` нь ЗӨВХӨН тестэд (`tests/integration/test_system_routes.py`)
гараар нэмэгддэг. `app/broker/alpaca.py`-ийн `httpx.HTTPError` салаанууд
(`:125`, `:210`, `:221`, `:234`) нь `BrokerUnavailable` raise хийгээд өнгөрдөг —
тоолуур ахихгүй.

**Яагаад энэ нь зогсоолт.** Гурван үр дагавар давхарлана:

1. `_rate()` нь хоосон цонхонд `total = 0` тул `tripped = total > 0 and ...`
   → **ХЭЗЭЭ Ч үнэн болохгүй**. LLD §15.2-ийн «дөрвөн метрик, тус бүр
   ДАНГААРАА halt үүсгэнэ» гэсэн заалтын нэг дөрөвний нэг нь ажиллахгүй.
2. Хэмжилт нь хэмжигдээгүй атлаа `value: "0.0000"`, `tripped: false` гэж
   буцна. `_daily_loss()` нь broker хүрэхгүй үед `"unmeasured"` гэдэг ИЛ
   утгыг мэддэг — `_rate()`-д тэр ойлголт байхгүй. Operator «Идэвхжүүл»-ийн
   өмнө «api_error_rate 0.0000 — хэвийн» гэж уншина. Энэ бол ЯГ «мэдэхгүйг
   мэднэ болгох» (хавсралт 10) хэлбэр.
3. `breaker.py:78-80`-ийн тайлбар нь `daily_loss`-ийн «unmeasured» гаралтыг
   «Broker-ийн уналт нь өөрийн метрикээр (api_error_rate) баригдана» гэж
   ҮНДЭСЛЭДЭГ. Тэр нөөц зам байхгүй тул **Alpaca бүрэн унасан үед дөрвөн
   метрикийн аль нь ч унахгүй**: `daily_loss` = unmeasured, `api_error_rate`
   = 0/0, `order_reject_rate` ба `ws_disconnects` нь trade-update урсгал
   зогссон тул шинэ мөр авахгүй. Систем `active` хэвээр, самбар бүрэн ногоон.

**Хаана засах.** `AlpacaAdapter`-ийн REST давхарга (уншилт ба `submit_order`
хоёул) дуудалт бүрийн үр дүнг `breaker.record(session, "api_error", ok=...)`-
оор бүртгэх — тоолуурыг НЭГ газраас ахиулах (`record()`-ийн docstring аль
хэдийн тэгж амлаж байгаа). Мөн `_rate()` нь `total == 0` үед `"unmeasured"`
буцааж, `MetricReading`-д хэмжигдсэн эсэхийг ил гаргах. Хоёр дахь нь чухал:
эх сурвалж холбогдсон ч цонхонд дуудалт байхгүй үед 0% гэж хэлэх нь ижил
худал ногоон.

---

## 5. Ажиглалт (зогсоолт БИШ, гэхдээ бүртгэгдэв)

| # | Ажиглалт | Байршил |
|---|---|---|
| N-1 | **Ticket-ийн notional ба R9-ийн лавлах үнэ зөрнө.** LLD §16.5 «Risk-ийн R9-тэй нэг лавлах үнэ болно» гэж бичсэн ба `ManualTicketPage`-ийн тайлбар үүнийг давтана. Гэвч `rules.reference_price()` нь `limit_price` байвал ТҮҮНИЙГ авна, UI нь ҮРГЭЛЖ `quote.last`-ыг авна. Limit order дээр дэлгэц дэх дүн ба R9-ийн шалгах дүн өөр (зөрүү нь R4 `PRICE_SANITY_PCT`-ээр хязгаарлагдана). Аль нэгийг сонгоод LLD-д нь буцааж бичих ёстой. | `app/risk/rules.py:31-37`, `frontend/.../ManualTicketPage.tsx:83-98`, LLD §16.5 |
| N-2 | **Heartbeat нь query invalidation өдөөнө.** `useLiveSocket` нь `channel === 'system'` бүх мессежид `system-state` + `providers`-ыг invalidate хийнэ; `ws.py`-ийн heartbeat нь ЯГ тэр сувгаар `HEARTBEAT_SECONDS` (анхдагч 2s) тутам ирнэ. Тиймээс сул зогсож буй таб бүр 30 удаа/мин `GET /system/state` татна — тэр бүр нь `CircuitBreaker.measure()` → `broker.get_account()` (бодит Alpaca REST). Scheduler-ийн 5s `enforce_breaker`-ийн дээр нэмэгдэнэ. Засвар: `payload.event === 'heartbeat'` бол invalidate хийхгүй. | `frontend/src/hooks/useSystemState.ts:47-62`, `app/api/ws.py:56-61` |
| N-3 | **Market-data урсгал үйлдвэрлэлд холбогдоогүй.** `BrokerPort.stream_market_data` нь зөвхөн тодорхойлогдсон; `_start_background` нь trade-update ingestor-ыг л асаана. AsyncAPI-ийн `ticks` суваг рүү юу ч нийтлэгддэггүй, frontend түүнийг сонсдоггүй. LLD §22-ийн «Market data WS тасарсан → banner 5s дотор» мөр нь бодит замгүй; staleness нь ЗӨВХӨН `system` heartbeat дээр тогтоно. v1-д quote нь REST-ээс ирдэг тул operator-т нүх үүсэхгүй ч LLD-ийн мөр нь кодтой зөрж байна. | `app/main.py:121-138`, `contracts/asyncapi.yaml` `ticks` |
| N-4 | **`checked_claims` UI-д гарахгүй.** 2-р тойрогт гэрээнд нэмэгдсэн талбар нь `DecisionsPage`-д харагддаггүй; тоогүй үндэслэл (`checked_claims = 0`) нь «дамжсан» гэж НОГООН гарна. `not_run` ялгагдсан нь зөв, гэхдээ «0 тоо шалгав» ба «12 тоо шалгав» хоёр ижилхэн харагдана. | `frontend/.../DecisionsPage.tsx:160-180` |
| N-5 | **`approvals`-ийн optimistic lock нь атом биш.** `_locked()` нь `session.get` + версь харьцуулалт хийгээд дараа нь бичнэ (`SELECT ... FOR UPDATE` эсвэл `UPDATE ... WHERE version = :expected` БИШ). Зэрэгцээ хоёр `approve` хоёулаа шалгалтыг давж болно. Давхар order илгээгдэхгүй (client_order_id нь `approval.id`-аас гардаг тул `ExecutionAgent` дедуп хийнэ) — тиймээс зогсоолт биш, гэхдээ LLD §15.3-ийн «optimistic lock тул 409 буцна» гэсэн амлалт зэрэгцээ тохиолдолд баталгаагүй. | `app/api/routes_approvals.py:73-97` |

---

## 6. Энэ хяналтад ШАЛГААГҮЙ зүйлс (хамрах хүрээний ил заалт)

Дараах зүйлсийг энэ орчинд шалгах боломжгүй байсан — «ногоон» гэж
ойлгож БОЛОХГҮЙ:

- **Бодит Postgres DDL.** `migrations/postgres_append_only.sql`-ийн trigger-ууд
  зөвхөн уншиж шалгагдав; тест SQLite дээр ажилласан тул `RAISE EXCEPTION`
  бодитоор ажилласан эсэх нь батлагдаагүй.
- **Бодит Alpaca (paper эсвэл live).** Бүх broker харилцаа fake adapter дээр.
  §7-ийн буулгалт (`market_value` нь Alpaca-аас) кодоор шалгагдсан, сүлжээгээр биш.
- **Browser түвшний assert (Playwright).** LLD §16.2 нь холимог `source`-ийн
  хоригийг Playwright-аар барихыг заасан; репод Playwright БАЙХГҮЙ, хориг нь
  vitest + `lib/source.ts` түвшинд.
- **Backtest зам.** `get_backtest_result` нь runner тохируулаагүй тул
  `no_data` буцаана; `source: backtest`-ийн бүх урсгал ажиллаагүй.
- **30 хоногийн paper proving window.** `app/system/proving.py` нь логик
  түвшинд тесттэй; бодит 30 хоног өнгөрөөгүй.

---

## 7. Дүгнэлт

§19-ийн 15 цэг ба хянагчийн гурван гадаргуу (хэн юунд арилжаа хийж байна ·
гарын арилжаа · wind-down/activate) нь LLD-тэй тохирч байна. Зогсоолт нь
тэдгээрийн гадна, гэхдээ тэдгээрийн аюулгүй байдал түшдэг давхарга дээр:
автомат зогсоолтын дөрвөн метрикийн нэг нь хоосон бөгөөд хоосон байдал нь
ногоон өнгөөр харагдана. Үүнийг засаад (эсвэл метрикийг ил «unmeasured»
болгоод LLD §15.2-ыг үнэнд нь нийцүүлээд) дахин хянуулна.
