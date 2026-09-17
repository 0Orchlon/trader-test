<!-- PERSONAL-3 · code-review · CODE_REVIEW (4-р тойрог) · 2026-09-17 -->

# PERSONAL-3 — Кодын хяналт, 4-р тойрог

**Ажил:** PERSONAL-3 · **Салбар:** `issue/personal-3` · **Хянасан commit:** `d17cd8c`
**Хэмжүүр:** `docs/PERSONAL-3/lld.md` (LLD v1.0) — ялангуяа §19-ийн «шалгах
боломжтой 15 цэг», `contracts.yaml`, `spec.md`-ийн AC-29…AC-38.
**Өмнөх тойрог:** `code-review-round3.md` (B-1 + N-1…N-5) ба түүний засвар
`code-review-round3-fixes.md`.

> **Хамрах хүрээний гэрээ (LLD §0):** энэ загварт бичигдсэн зүйлийг шалгав.
> Загварт байхгүй зүйлээр кодыг буруутгаагүй; загварт байгаа зүйлийг
> алгассан эсэхийг тусад нь шалгав.

---

## 1. Хэмжилт (энэ тойрогт өөрөө ажиллуулсан)

| Гадаргуу | Команд | Үр дүн |
|---|---|---|
| backend | `python -m pytest -q` (Python 3.12.13, шинэ venv, `requirements.lock`) | **356 passed**, 0 failed |
| backend | `python -m pytest -q --cov=app --cov-branch` | **356 passed** · `coverage gate: ногоон (LLD §18.3)` |
| frontend | `npm ci && npm test` | `check:api` (гэрээтэй тэнцүү) · `eslint` цэвэр · `tsc --noEmit` цэвэр · **66 passed / 6 файл** |
| contracts | `npm ci && npm test` | OpenAPI/AsyncAPI valid · `bundle шалгалт OK` · `дуурайлтын шалгалт OK — 10 зам, 5 үл хөдлөх дүрэм` |

`backend/coverage.json` нь хяналтын дараа устгагдсан — репод үлдээгүй.

---

## 2. 3-р тойргийн засварын баталгаажуулалт

| # | Байсан зөрчил | Одоогийн байдал |
|---|---|---|
| B-1 | `api_error_rate` эх сурвалжгүй атлаа `0.0000` гэж ногоон харагдана | **Хаагдав.** `AlpacaAdapter._report()` нь REST дуудалт бүрийн үр дүнг мэдэгдэнэ (`app/broker/alpaca.py:107-115`, `_read` дотор `await self._report(True/False)`); `create_app` нь түүнийг хүсэлтийн session-ээс ТУСДАА session дээр `breaker_events(kind='api_error')` руу утаслав (`app/main.py:84-94`). `_rate()` нь хоосон цонхыг `unmeasured` гэж ил гаргана (`app/risk/breaker.py:90-96`), UI нь «ХЭМЖИГДЭЭГҮЙ» гэж улбар шараар (`StateBar.tsx` `BreakerMetrics`). |
| N-1 | Ticket-ийн notional ба R9-ийн лавлах үнэ зөрнө | **Хаагдав.** `ManualTicketPage` дэх `reference` нь `rules.reference_price()`-тай ижил дараалалтай (limit үнэ давуу, эс бөгөөс сүүлийн quote), хэрэглэсэн үнийн эх сурвалж дэлгэцэд нэрлэгдэнэ. |
| N-2 | Heartbeat нь query invalidation өдөөнө | **Хаагдав.** `useSystemState.ts` дотор `message.payload?.event !== 'heartbeat'` шалгалт нэмэгдэв. |
| N-3 | Market-data WS үйлдвэрлэлд холбогдоогүй | **Баримтаар хаагдав.** LLD §22 нь «v1-д market-data WS БАЙХГҮЙ, `ticks` суваг НӨӨЦЛӨГДСӨН» гэж ил бичсэн — код ба загвар нийцэв. |
| N-4 | `checked_claims` UI-д харагдахгүй | **Хаагдав.** `DecisionsPage.tsx:176-180` — «N тоо шалгав» мөр, `not_run` тусад нь. |
| N-5 | Approval-ийн optimistic lock атом биш | **Хаагдав.** `routes_approvals.py:73-81` — `locked_approval_stmt()` нь `SELECT … FOR UPDATE`. |

---

## 3. LLD §19-ийн 15 шалгах цэг

| # | Цэг | Байдал | Нотолгоо |
|---|---|---|---|
| 1 | `submit_order`-ийн дуудагч зөвхөн `app/execution` | ✅ | Ганц дуудалт `app/execution/agent.py:88`. Статик хаалга `tests/static/test_import_gates.py::test_r1_...` ногоон. |
| 2 | `ValidatedOrder` нь `evaluate()`-ээс л үүснэ | ✅ | Байгуулалт ганц газар: `app/risk/agent.py:127`. `routes_orders.py:199` нь гараар байгуулахын оронд `escalation_confirmed=True`-тэй ДАХИН үнэлдэг. |
| 3 | `orders.origin` нь `NOT NULL`, анхдагчгүй | ✅ | `app/models.py:67` (`nullable=False`, `default` байхгүй) + `ck_orders_origin` check. |
| 4 | Төлөв Postgres-д; startup УНШИНА | ✅ | `app/main.py:46 → state.py:117 ensure_initialised()`; мөр байхгүй бол `halted`/`initial_deploy`. |
| 5 | `halted → winding_down` шилжилт БАЙХГҮЙ | ✅ | `state.py:186` — `InvalidTransition("already_halted")`; route нь 409 болгоно. |
| 6 | `activate` нь метрикийг ДАХИН хэмжинэ | ✅ | `routes_system.py:116` — `breaker.tripped()` нь шинэ хэмжилт; хадгалагдсан «цэвэрлэсэн» туг кодод байхгүй. |
| 7 | Гарын order `agent_decisions` мөр үүсгэхгүй | ✅ | `routes_orders.py` дотор `AgentDecision` огт хэрэглэгдээгүй; `decision_id=None`. |
| 8 | Локал fill байхгүй бол `external` | ✅ | `attribution.py:34` `EXTERNAL`, `attribute()` нь `origins.get(symbol, EXTERNAL)` — «хамгийн ойрын» тааруулга байхгүй. |
| 9 | `tool_calls` бичилт нь LLM-д буцахаас ӨМНӨ | ✅ | `gateway.py:161-166` — `call.response` бичигдэж `commit` хийсний ДАРАА `envelope(...)` буцна. |
| 10 | Tool result бүрд `system_state`, schema-д `required` | ✅ | `gateway.envelope()` талбарыг үргэлж бичнэ; `contracts/tool-contract.v1.yaml:35` `required: [tool_call_id, timestamp, source, system_state, ok]`. |
| 11 | Grounding унавал Risk хүртэл ОЧИХГҮЙ | ✅ | `tools.py` — `grounding_json["passed"]` худал бол `_record_decision(...)` хийгээд буцна; `build_risk_context`/`evaluate` дараа нь дуудагдана. |
| 12 | `audit_log` дээр UPDATE/DELETE татгалзах trigger | ✅ | `migrations/postgres_append_only.sql` — `p3_refuse_mutation()` + UPDATE/DELETE/TRUNCATE trigger, `system_state` дээр мөн адил. `tests/static/test_append_only_sql.py` ногоон. |
| 13 | §7-ийн 10 хязгаар кодод анхдагчгүй | ✅ | `config/settings.py` — `REQUIRED_LIMIT_FIELDS` 10 талбар, бүгд төрлийн зарлалт, анхдагчгүй; `tests/unit/test_config_mode.py:39` тест. |
| 14 | Нэг хүснэгтэд хоёр `source` харагдахгүй | ✅ | `DecisionsPage.tsx:203-208` — холимог бол хүснэгт ОГТ гарахгүй, улаан `mixed-source` мэдэгдэл орно. Backend талд `MixedSourceError` → 500. |
| 15 | Settings дэлгэцэд хязгаар засах талбар БАЙХГҮЙ | ✅ | `SettingsPage.tsx` — form/input элемент байхгүй, `settings-readonly` мэдэгдэлтэй (N-1 ажиглалтыг үз). |

---

## 4. Хянагчийн буцаасан гурван гадаргуу (OP-11 · OP-12 · OP-13)

| Шаардлага | Байдал | Нотолгоо |
|---|---|---|
| «AI/алгоритм юунд арилжаа хийж байгааг frontend дээр харах» | ✅ | `AttributionPage` — origin тус бүр нэг карт, `холимог origin` тэмдэг, «яагаад →» холбоос; Dashboard-ийн позиц ба order хүснэгт бүрд `Гарал (origin)` багана (AC-29). Backend `build_groups()` нь `orders ∪ positions`-ийн бодит мөрөөс угсарна, кэшгүй. |
| «Frontend-ээс өөрөө гараар арилжаа хийх» | ✅ | `ManualTicketPage` → `POST /orders/manual` → ижил Risk → `ExecutionAgent`. `HALTED` үед товч идэвхгүй + шалтгаан; `WINDING_DOWN` үед зөвхөн багасгах чиглэл; босгоос дээш үед `confirmation.prompt`-той token урсгал; `Idempotency-Key` = бие + оролдлого. |
| «Унтраах мэдэгдэл → ашгаа түргэн авч зогсоно → идэвхжүүл товч дартал зогссон» | ✅ | `POST /system/wind-down` → `WINDING_DOWN` + grace; agent-т `GUIDANCE[WINDING_DOWN]` нь tool result бүрээр очиж «эхлээд нээлттэй позицоо хаа» гэж заана; R2 нь exposure нэмэгдүүлэхийг хоёр давхаргаар хаана; grace дуусахад `HALTED`; restart-д `HALTED` хэвээр; `activate` нь баталгаажуулалт + breaker дахин хэмжилт шаардана. `tests/integration/test_e2e_state_machine.py` бүтэн мөчлөгийг барина. |

---

## 5. ЗОГСООХ ЗӨРЧИЛ

**БАЙХГҮЙ.** Энэ тойрогт §19-ийн 15 цэг, хянагчийн гурван гадаргуу,
дөрвөн гадаргууны тест бүгд ногоон.

---

## 6. Ажиглалт (зогсоолт БИШ, гэхдээ бүртгэгдэв)

| # | Ажиглалт | Байршил |
|---|---|---|
| N-1 | **Settings дэлгэц хязгааруудыг ОГТ харуулахгүй.** LLD §16.6-ийн хүснэгт Settings-ийн агуулгыг «хязгаарууд (ЗӨВХӨН УНШИХ), API key-ийн төлөв, горим» гэж заасан. Код нь эхний зүйлийг алгассан: `contracts.yaml`-д хязгаарыг унших зам ч байхгүй тул frontend-д эх сурвалж байхгүй. Үр дагавар: operator `MAX_ORDER_NOTIONAL` зэрэг тоог зөвхөн `.env`-ээс л мэднэ, UI-д хаана ч харагдахгүй. Ямар ч AC үүнийг шаардаагүй тул зогсоолт биш, гэхдээ LLD §16.6 ↔ `contracts.yaml` хоёрын аль нэгийг нь засах хэрэгтэй (эсвэл GET `/settings/limits` нэмэх, эсвэл LLD-ийн мөрийг богиносгох). | `frontend/src/features/settings/SettingsPage.tsx`, LLD §16.6, `contracts.yaml` (`paths`) |
| N-2 | **Ticket-ийн wind-down чиглэлийн шалгалт `qty`-ийн ТЭМДГЭЭР шийднэ, `side`-аар биш.** `allowedSides()` нь `positionQty.startsWith('-')` гэж short-ыг таана. Backend-ийн R2 (`increases_exposure`) нь `pos.side` (`long`/`short`) ашигладаг бөгөөд `GET /positions` нь `side` талбарыг аль хэдийн буцаадаг. Alpaca нь short позицид сөрөг `qty` буцаадаг тул бодит байдалд таарна; гэхдээ `side='short'` атлаа эерэг `qty` ирвэл UI нь ХААХ чиглэлийг (buy) идэвхгүй болгож, НЭМЭГДҮҮЛЭХ чиглэлийг (sell) санал болгоно. Backend R2 нь эцсийн хаалга хэвээр тул аюулгүй тал руу унана — зогсоолт биш, харин хоёр өөр алгоритм нэг дүрмийг илэрхийлж байна. | `frontend/src/features/manualTicket/ManualTicketPage.tsx` (`allowedSides`), `backend/app/risk/rules.py:42-51` |
| N-3 | **Agent Gateway нь үйлдвэрлэлийн урсгалд ХОЛБОГДООГҮЙ.** `Gateway` ба `ToolContext` нь зөвхөн тестээс байгуулагддаг (`grep -rn "Gateway(" backend/app` = 0). `contracts.yaml`-д LLM-ийн орох зам (tool dispatch endpoint эсвэл MCP server) БАЙХГҮЙ; `provider_router` нь зөвхөн `GET /providers` ба `POST /providers/{role}/switch`-д л хэрэглэгддэг, `bind()`-ийг үйлдвэрлэлийн код дуудахгүй. Тиймээс v1-ийн ажиллаж буй систем дээр AI санал гаргах бодит зам байхгүй, provider солих нь юу ч хэрэглэдэггүй лавлагааг солино. **Энэ нь код ↔ загварын зөрүү БИШ:** LLD §3, §12 ба `contracts.yaml` нь LLM-ийн процесс хэрхэн холбогдохыг огт заагаагүй (adapter-ууд §2-ийн зурагт системийн хайрцгаас ГАДНА). Тиймээс энэ нь дараагийн загварын шийдвэр шаардах НҮХ — кодын алдаа биш. `tasks.md` T-19-ийн «MCP server болгож экспортлоно» гэсэн DoD мөр нь хэрэгжээгүй хэвээр. | `backend/app/agents/gateway.py`, `backend/app/agents/router.py`, `contracts.yaml` |
| N-4 | **Модулийн байрлал LLD §3-ийн бүтцээс зөрнө.** §3 нь `system/killswitch.py`, `system/breaker.py`, `system/confirmation.py`, `stream/fanout.py`, `stream/hub.py`, `api/account.py|orders.py|…`, `hooks/useLiveSocket.ts`, `hooks/useStaleness.ts` гэж жагсаасан. Кодод эдгээр нь `risk/breaker.py`, `api/confirm.py`, `stream/bus.py`+`ingest.py`, `api/routes_*.py`, `hooks/useSystemState.ts` (`useLiveSocket` дотор нь) болж нэгтгэгдсэн. Функциональ агуулга бүрэн байгаа, зан төлөв зөрөөгүй — зөвхөн нэр/байрлал. Санаа зовоох цорын ганц зүйл: `risk/breaker.py` нь `app.system.state`-ийг (функцийн дотор) import хийдэг тул «risk давхарга доош л хардаг» гэсэн §2-ийн заалтын ирмэг дээр байна; статик хаалга R-2 нь `app.system`-ийг хориглодоггүй тул тест барихгүй. | `backend/app/risk/breaker.py:132-146`, LLD §3 |
| N-5 | **`audit_log.seq` нь аппликейшнээс оноогдоно** (`last_seq + 1`), LLD §5.7-ийн `bigserial` биш. Зэрэгцээ хоёр `append` нэг `seq` тооцоод PK мөргөлдөнө — нэг транзакц унана (аюулгүй тал), гэхдээ «зөв гинж» нь DB-ийн дараалал биш, дуудагчийн цуваанаас хамаарна. Одоогийн системд бичилтүүд хүсэлтийн session дотор цуваа явдаг тул илрээгүй. | `backend/app/audit/chain.py:68-86`, `backend/app/models.py:176` |

**Мэдээллийн тэмдэглэл (зөрчил биш):** §19-ийн 2-р цэг («`ValidatedOrder` нь
APPROVE салаанаас л үүснэ») нь баталгаажсан `ESCALATE_TO_HUMAN` салаанд ч
объект үүсэх байдлаар хэрэгжсэн (`risk/agent.py:118-143`). Энэ нь LLD §9.3-ийн
«token-той дахин ирвэл үргэлжилнэ» шаардлагын шууд үр дүн бөгөөд объект
үүсгэх газар ганц хэвээр байна; `orders.risk_evaluation` нь шийдвэрийг
`ESCALATE_TO_HUMAN` гэж үнэнээр бүртгэнэ.

---

## 7. Энэ хяналтад ШАЛГААГҮЙ зүйлс (ил заалт — «ногоон» гэж ойлгож БОЛОХГҮЙ)

- **Бодит Postgres.** Тест SQLite дээр ажилласан. `postgres_append_only.sql`-ийн
  trigger, `SELECT … FOR UPDATE`-ийн мөрийн lock (төлөвийн машин ба approvals)
  зөвхөн уншиж шалгагдав, бодит DB дээр биш.
- **Бодит Alpaca (paper эсвэл live).** Бүх broker харилцаа fake adapter дээр;
  сүлжээгээр нэг ч дуудалт хийгээгүй.
- **Browser түвшний assert (Playwright).** LLD §16.2/§16.3 нь Playwright-аар
  барихыг заасан; репод Playwright байхгүй, хориг нь vitest түвшинд.
- **Backtest зам.** `get_backtest_result` нь runner тохируулаагүй тул `no_data`
  буцаана; `source: backtest`-ийн урсгал ажиллаагүй.
- **30 хоногийн paper proving window** ба **mutation тест (`mutmut`)** —
  хугацаа/нөөцийн шалтгаанаар ажиллуулаагүй.
- **N-3-ийн үр дагавар:** AI-ийн санал гаргах бодит гүйцэтгэл (LLM ↔ Gateway)
  энэ орчинд ажиллуулах боломжгүй — tool замын зан төлөв зөвхөн тестээр
  батлагдсан.

---

## 8. Дүгнэлт

**ӨНГӨРӨВ (ногоон).** LLD §19-ийн 15 шалгах цэг бүгд биелэв; 3-р тойргийн
зогсоох зөрчил B-1 ба таван ажиглалт бодитоор хаагдсаныг кодоос баталлаа;
хянагчийн буцаасан гурван гадаргуу (хэн юунд арилжаа хийж байна · гарын
арилжаа · унтраах бэлтгэл/идэвхжүүл) нь LLD §11, §16.4, §16.5, §6, §8.2-той
тохирч байна. Дөрвөн гадаргууны шалгалт (backend 356 + coverage gate,
frontend 66 + lint/typecheck/generated-check, contracts) өөрөө ажиллуулахад
ногоон.

Үлдсэн таван ажиглалтын аль нь ч гүйцэтгэлийн аюулгүй байдлын хаалгыг
сулруулаагүй. Тэдгээрээс **N-3** нь хамгийн жинтэй: AI санал гаргах зам нь
үйлдвэрлэлд холбогдоогүй бөгөөд энэ нүх нь кодод биш, ЗАГВАРТ байна —
дараагийн загварын тойрогт LLM-ийн орох замыг (MCP server эсвэл tool dispatch
endpoint) ил тодорхойлох шийдвэр шаардлагатай. §7-ийн шалгаагүй жагсаалт нь
хамрах хүрээний ил заалт бөгөөд «ногоон» гэж тооцогдохгүй.
