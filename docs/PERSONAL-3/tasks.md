<!-- PERSONAL-3 · tasks · PLAN_TASK · 2026-09-16 -->

# PERSONAL-3 — Ажлын задаргаа (T-01…T-41)

**Ажил:** PERSONAL-3 · **Салбар:** `issue/personal-3` · **Шат:** PLAN_TASK
**Эрх бүхий оролт:** `spec.md` (AC-1…AC-28) · **Хамт:** `plan.md` (M1…M6, P-1…P-5)

---

## 0. Хэрхэн унших

Task бүр дараах талбартай:

- **Хэмжээ** — S ≈ 1 хүн-өдөр, M ≈ 2–3, L ≈ 4–5 (`plan.md` P-4)
- **Хамаарал** — эхлэхээс өмнө дуусах ёстой task
- **AC** — спекийн аль хүлээн авах шалгуурт хувь нэмэр оруулах
- **Дуусгах шалгуур (DoD)** — шалгаж болохуйц. «Бэлэн болов» гэдэг нь эдгээр
  шалгалт CI-д ногоон болсныг л хэлнэ. Хүний үзэмж энд байхгүй.

⚠ **AC-гүй task байхгүй.** Ажил дундаа AC-т холбогдохгүй task үүсвэл тэр нь
хамрах хүрээнээс гадуур — backlog руу, спекийг өөрчлөхгүйгээр нэмэхгүй.

⚠ §7-ийн тоон хязгаар (`MAX_POSITION_PCT` гэх мэт) нь **кодод анхдагчаар
суухгүй**. Task-ууд тэднийг зөвхөн *нэрээр* иш татна. Тохиргоо дутуу бол
систем эхлэхгүй — анхдагч руу унахгүй (`plan.md` §2 зарчим 2).

---

## Эпик A — Суурь (M1)

### T-01 · Репо суурь, CI, secret scanner, lockfile pin
**Хэмжээ:** M · **Хамаарал:** — · **AC:** AC-19, AC-28
- `backend/` (Python 3.12, uv/poetry lockfile) ба `frontend/` (Vite, `package-lock.json`)
  гадаргуу; root дээр нэгтгэсэн build script ҮҮСГЭХГҮЙ.
- `.github/workflows/ci.yml` — matrix: `backend`, `frontend`; job бүр өөрийн
  гадаргууны дотор lint + test + build.
- pre-commit secret scanner (`gitleaks` эсвэл `detect-secrets`) — hook ба CI job
  хоёуланд.
- **DoD:** (а) хуурамч API key агуулсан commit оролдлого pre-commit дээр унана;
  (б) CI хоёр гадаргуунд ногоон; (в) lockfile-гүй хамаарал байхгүй — `--frozen`
  / `npm ci` тохиргоогоор build хийгдэнэ.

### T-02 · DB schema migration (7 хүснэгт)
**Хэмжээ:** M · **Хамаарал:** T-01 · **AC:** AC-7, AC-25, AC-26
- Alembic migration: `accounts`, `orders`, `fills`, `agent_decisions`,
  `tool_calls`, `tuning_history`, `audit_log`.
- Мөнгөн багана бүр `NUMERIC(…)`; timestamp багана бүр `timestamptz`.
- `agent_decisions.grounded_in` нь хоосон биш (`CHECK cardinality > 0`) ба
  `tool_calls(tool_call_id)`-д FK-аар холбогдоно.
- **DoD:** (а) `information_schema`-аар мөнгөн багана `double precision`
  БАЙХГҮЙг батлах тест; (б) бүсгүй timestamp INSERT хийх оролдлого унана;
  (в) хоосон `grounded_in`-тай мөр, байхгүй `tool_call_id`-тай мөр DB-д
  татгалзана (хоёр тус тусын тест).

### T-03 · Config, mode resolution, live-egress хаалт
**Хэмжээ:** M · **Хамаарал:** T-01 · **AC:** AC-12, AC-20
- Pydantic Settings: Alpaca endpoint (paper анхдагч), `LIVE_TRADING_ENABLED`
  (анхдагч `false`), §7-ийн 9 хязгаарын нэр — **анхдагч утгагүй, дутуу бол
  startup унана**.
- Одоогийн горим (`alpaca_live` | `alpaca_paper` | `backtest`) нь нэг эх
  функцээс тодорхойлогдоно; хариу угсрах давхарга үүнийг `source` талбарт тавина.
- Тестийн туршид live host руу гарах трафикийг барих network guard (pytest
  fixture: DNS/socket hook эсвэл allowlist proxy).
- **DoD:** (а) `LIVE_TRADING_ENABLED` тохируулаагүй үед `api.alpaca.markets`
  руу гарсан дуудалт = 0 (бүх suite-д тоологдоно); (б) live host руу дуудалт
  гаргах санаатай тест нь guard-аар унана; (в) `MAX_ORDER_NOTIONAL` гэх мэт
  хязгаар тохируулаагүй үед app эхлэхгүй.

### T-04 · Redis pub/sub + WebSocket fan-out суурь
**Хэмжээ:** S · **Хамаарал:** T-01 · **AC:** AC-2, AC-14
- Сувгууд: `ticks:{symbol}`, `orders`, `agent-decisions`, `system`.
- `system` суваг нь backpressure дор ч хүргэгдэнэ (тусдаа өндөр эрэмбийн
  дараалал; бусад сувгийн мессеж хаягдаж болно, `system` хаягдахгүй).
- **DoD:** (а) 10 000 `ticks` мессежээр дүүргэсэн үед илгээсэн `system`
  мессеж холбогдсон клиент бүрт хүрснийг батлах тест; (б) клиент салж
  дахин холбогдоход төлөв дахин илгээгдэнэ.

### T-05 · Лог redaction + CI-ийн secret pattern тест
**Хэмжээ:** S · **Хамаарал:** T-01 · **AC:** AC-19
- Logging filter: Alpaca key/secret, LLM provider token, DB DSN-ийн password
  хэсгийг маскална. Filter нь global (root logger + uvicorn + SQL echo).
- **DoD:** (а) key-г санаатай логлох оролдлого хийсэн тест: гаралтад key
  pattern 0 удаа олдоно; (б) тест CI-д заавал ажиллана (skip marker байхгүй);
  (в) exception traceback дотор ч key гарахгүй (traceback-тай тест кейс).

---

## Эпик B — Broker integration (M1, submit хэсэг M2)

### T-06 · `BrokerPort` protocol + `AlpacaAdapter` (унших)
**Хэмжээ:** M · **Хамаарал:** T-02, T-03 · **AC:** AC-1
- `BrokerPort` protocol (хавсралт 02 §2.1-ийн 7 метод).
- `AlpacaAdapter`-ийн унших метод: `get_account`, `get_positions`,
  `get_open_orders` — Alpaca-ийн буцаасан талбарыг **verbatim** дамжуулна,
  локал тооцоолол нэмэхгүй.
- Түүхий хариу нь агент харахаас ӨМНӨ `tool_calls`-д хадгалагдана (хавсралт 10 §2.1).
- **DoD:** (а) paper дансны мэдэгдэж буй position дээр `qty`,
  `avg_entry_price`, `equity` нь Alpaca REST-ийн түүхий хариутай тэмдэгт
  тэмдэгтээр тэнцүү; (б) adapter дотор арифметик оператор байхгүйг батлах
  review checklist + тест (derived утга буцаавал унана).

### T-07 · Унших REST endpoint + `source` талбар + холимог хориг
**Хэмжээ:** M · **Хамаарал:** T-06 · **AC:** AC-1, AC-20, AC-21
- `GET /api/v1/account`, `/positions`, `/orders?status=`, `/health`.
- Өгөгдөл агуулсан хариу бүрийн schema-д `source` нь `required`, enum =
  `alpaca_live` | `alpaca_paper` | `backtest`.
- Хариу угсрагч нь өөр `source`-той бичлэгийг НЭГ жагсаалт / НЭГ хариунд
  нийлүүлэхийг татгалзана (exception).
- Мөнгөн талбар бүр тогтмол таслалтай тэмдэгт мөр (`"10234.56"`).
- **DoD:** (а) бүх endpoint дээр schema validation тест — `source`-гүй хариу
  үүсгэх оролдлого алдаа өгнө; (б) enum-аас гадуур утга татгалзана;
  (в) холимог `source`-той хариу угсрах тест **унах ёстой**; (г) мөнгөн
  талбарт float төрөл буцаах оролдлогыг барих тест.

### T-08 · Order илгээх зам + idempotency
**Хэмжээ:** M · **Хамаарал:** T-13 · **AC:** AC-3, AC-27
- `AlpacaAdapter.submit_order`: `market`, `limit`, `stop`, `stop_limit`,
  `bracket`. `client_order_id`-аар dedupe — retry хоёр дахин илгээхгүй.
- Энэ зам зөвхөн Execution модулиас нэвтрэнэ (T-14-ийн статик хаалт үүнийг барина).
- **DoD:** (а) ижил `client_order_id`-тай хоёр дахин илгээхэд Alpaca mock
  дээр дуудалт = 1; (б) order төрөл тус бүрийн payload mapping тест;
  (в) сүлжээний timeout дараа retry хийхэд давхар order үүсэхгүйг батлах тест;
  (г) order замын coverage ≥ 90% (T-36-ийн gate-д тоологдоно).

### T-09 · Trade-update / market-data WS ingestion + staleness
**Хэмжээ:** M · **Хамаарал:** T-04, T-06 · **AC:** AC-2
- Alpaca WS → Redis → frontend fan-out. Reconnect нь exponential backoff-той.
- Сүүлд шинэчилсэн UTC timestamp суваг тутам хадгалагдана; 5 секундээс хойш
  шинэчлэлт байхгүй бол `stale` төлөв `system` сувгаар мэдэгдэнэ.
- Redis дээр rate-limit тоолуур (Alpaca-ийн хязгаарыг давахгүй).
- **DoD:** (а) WS-ийг албадан салгаад 5 секунд дотор stale төлөв гарсныг
  батлах integration тест; (б) reconnect-ийн дараа өгөгдөл дахин live гэж
  шошгогдоно; (в) салсан үед хуучин өгөгдөл `stale` шошгогүйгээр
  тархахгүйг батлах тест.

### T-10 · EOD reconciliation job
**Хэмжээ:** S · **Хамаарал:** T-06, T-02 · **AC:** AC-13
- APScheduler job: локал `orders`/`fills`/position төлөв ↔ Alpaca-ийн
  тайлагнасан төлөв. Зөрүү бүр `audit_log`-д бичигдэж, метрик тоолуур ахина.
- Зөрүүг локал тооцооллоор «засахгүй» — Alpaca нь эх сурвалж (хавсралт 02 §6).
- **DoD:** (а) зөрүүг санаатай үүсгэсэн тест: тоолуур ахина, лог бичигдэнэ;
  (б) зөрүү = 0 үед тоолуур ахихгүй; (в) job нь reconciliation mismatch
  метрикийг T-39-ийн тайланд гаргана.

---

## Эпик C — Risk & Execution (M2, хамгийн өндөр хяналттай)

### T-11 · Risk Agent — хатуу хязгаарын engine
**Хэмжээ:** L · **Хамаарал:** T-02, T-03 · **AC:** AC-4, AC-5
- Детерминистик Python. Оролт: саналын өгөгдөл + дансны төлөв + config.
  Гаралт: `APPROVE` | `REJECT(reason)` | `ESCALATE_TO_HUMAN(reason)`.
- Шалгалтууд (хавсралт 04 §2, 06 §1): `MAX_POSITION_PCT`,
  `MAX_TOTAL_EXPOSURE_PCT`, `DAILY_LOSS_LIMIT`, `MAX_DAY_TRADES` (PDT, equity
  < $25k), `MAX_ORDER_NOTIONAL` (дээш = escalate), `RESTRICTED_SYMBOLS`,
  fat-finger (limit price нь сүүлийн quote-оос хэт зөрөх).
- Prompt, model call, random, одоогийн цаг дээр шууд хамаарал БАЙХГҮЙ — цаг
  нь инжектлэгдэнэ (тест дээр хөлдөөх боломжтой).
- **DoD:** (а) хязгаар бүрт босгын доор / яг дээр / дээш гурван кейс;
  (б) config дутуу бол engine эхлэхгүй; (в) ижил оролт → ижил гаралт
  (детерминизмын тест, 100 дахин гүйлгэнэ).

### T-12 · Risk Agent-ийн property-based + mutation тест
**Хэмжээ:** M · **Хамаарал:** T-11 · **AC:** AC-4, AC-27
- Hypothesis: ≥ 10 000 кейс — order size, price, дансны төлөвийн хослол.
  Invariant: хатуу хязгаар зөрчсөн оролт ХЭЗЭЭ Ч `APPROVE` гаргахгүй.
- `mutmut` Risk модуль дээр; амьд mutant = хүлээн авахгүй.
- **DoD:** (а) 10 000 кейст зөрчсөн `APPROVE` 0; (б) mutation survivor = 0;
  (в) Risk модулийн line + branch хучилт = 100%, CI-ийн gate нь босгоос
  доош бол build унана.

### T-13 · Execution Agent
**Хэмжээ:** S · **Хамаарал:** T-11 · **AC:** AC-3
- Зөвхөн Risk-ийн `APPROVE` (эсвэл operator-ийн approve хийсэн escalation)-аас
  order үүсгэнэ. Risk батласан параметрийг өөрчлөх боломжгүй (frozen dataclass).
- Alpaca-ийн буцаасан order id-г `orders`-д хадгална.
- **DoD:** (а) `REJECT` / `ESCALATE` төлөвтэй саналаар submit хийх оролдлого
  exception өгнө; (б) параметр өөрчлөх оролдлого type-level дээр унана;
  (в) Risk-ийг REJECT болгосон integration тест дээр Alpaca mock-ийн
  submit дуудалт = 0.

### T-14 · Статик хаалт — `submit_order`-ийн дуудагчийн хязгаарлалт
**Хэмжээ:** S · **Хамаарал:** T-08, T-13 · **AC:** AC-3
- AST дээр ажиллах тест: `BrokerPort.submit_order` / `AlpacaAdapter.submit_order`-ийн
  дуудалт зөвхөн `execution` package-аас гарна.
- Agent Gateway-ийн tool handler-ууд нь submit модульд import хамааралгүй байхыг
  шалгана.
- **DoD:** (а) Gateway модулиас submit дуудалт нэмсэн санаатай diff дээр тест
  унана; (б) тест CI-ийн заавал job, skip боломжгүй; (в) шалгалт нь шинэ
  package нэмэгдэхэд автоматаар хамрах (allowlist-ийг эсрэгээр — deny by default).

### T-15 · Kill switch (гараар)
**Хэмжээ:** M · **Хамаарал:** T-04, T-13 · **AC:** AC-14, AC-16
- `POST /api/v1/kill-switch` → halt төлөв (Redis + DB) → order илгээх бүх зам
  1 секунд дотор хаагдана. Төлөв `system` сувгаар түгээгдэнэ.
- Байгаа position-ыг АВТОМАТААР ХААХГҮЙ (спек A-2 таамаг, AC-16).
- **DoD:** (а) тасралтгүй order урсгал дунд kill switch дарахад, дарснаас
  хойш 1 секундээс хойш гарсан submit = 0; (б) halt-ийн дараа position тоо,
  `qty` өөрчлөгдөөгүй; (в) холбогдсон бүх WS клиент halt мэдэгдэл авсан.

### T-16 · Circuit breaker (автомат)
**Хэмжээ:** M · **Хамаарал:** T-15, T-10 · **AC:** AC-15
- Monitoring: өдрийн алдагдал > `DAILY_LOSS_LIMIT`, API алдааны түвшин >
  `ERROR_RATE_LIMIT`, order татгалзлын түвшин > `REJECT_RATE_LIMIT` — тус бүр
  дангаараа kill switch-тэй ИЖИЛ halt үүсгэнэ.
- Автомат сэргэх зам БАЙХГҮЙ: хүн ил үйлдлээр цэвэрлэнэ.
- LLM-ээс хамаарахгүй (хавсралт 04 §6).
- **DoD:** (а) метрик тус бүрийг дангаар босгоос давуулахад halt болно
  (3 тусдаа тест); (б) босгын дараа хүлээхэд өөрөө сэргээгүй;
  (в) халт болсны дараа шинэ order = 0; (г) бүх LLM provider унасан үед ч
  breaker ажиллана.

### T-17 · Approval queue (backend)
**Хэмжээ:** M · **Хамаарал:** T-11 · **AC:** AC-5, AC-6
- `ESCALATE_TO_HUMAN` шийдвэр → `approvals` мөр. `GET /approvals`,
  `POST /approvals/{id}/approve`, `/reject`.
- Approve хүртэл Alpaca руу 0 дуудалт; reject бол ХЭЗЭЭ Ч илгээхгүй, шалтгаан
  бүртгэгдэнэ.
- `APPROVAL_TTL` дуусахад автоматаар reject, шалтгаан = `expired`.
- **DoD:** (а) approve / reject хоёр замын E2E — approve-оос өмнө Alpaca
  дуудалт = 0; (б) reject-ийн дараа дуудалт = 0; (в) цагийг хөлдөөж TTL
  давуулахад мөр `expired` болно; (г) TTL дууссан мөрийг approve хийх
  оролдлого татгалзана.

---

## Эпик D — Agent Gateway & Tool Contract (M3)

### T-18 · Tool Contract v1 — хувилбарласан JSON Schema + handler
**Хэмжээ:** M · **Хамаарал:** T-07, T-17 · **AC:** AC-3, AC-11
- Хавсралт 03 §3-ийн 6 tool: `get_account`, `get_positions`, `get_quote`,
  `get_backtest_result`, `propose_order`, `get_tuning_bounds`,
  `propose_tuning_change` — нэг эх schema файл, `v1` тэмдэгтэй.
- `propose_order` нь ЗӨВХӨН санал үүсгэнэ — Risk-ийн орох цэг руу дамжуулна.
- Tool result бүр өөрийн `tool_call_id` + timestamp-тай, `tool_calls`-д
  хадгалагдсаны дараа буцна.
- `get_quote` нь `stale: true` эсвэл `error: "no_data"`-г **ил** буцаана
  (талбар алгасахгүй).
- **DoD:** (а) LLM-д нээлттэй write-шинжтэй tool нь зөвхөн `propose_order`,
  `propose_tuning_change` хоёр — route/tool жагсаалтыг шалгах тест;
  (б) `propose_order` нь submit хийхгүйг батлах тест (Alpaca mock дуудалт = 0);
  (в) `grounded_in` / `backtest_evidence`-гүй дуудалт schema дээр унана;
  (г) өгөгдөлгүй symbol-д `no_data` буцна, тоо зохиохгүй.

### T-19 · Claude adapter (MCP)
**Хэмжээ:** M · **Хамаарал:** T-18 · **AC:** AC-10, AC-11
- Tool Contract-ыг MCP server болгож экспортлоно; `tool_use` / `tool_result`
  блок зохицуулна.
- Adapter нь key, DSN-г модельд хэзээ ч дамжуулахгүй.
- **DoD:** (а) adapter-ийн орчуулсан schema нь эх `v1` schema-тай validate
  болно; (б) tool result бүр `tool_call_id`-тай; (в) prompt payload дотор
  secret pattern 0 (T-05-ийн тесттэй нийлж ажиллана).

### T-20 · OpenAI / ChatGPT adapter (function calling)
**Хэмжээ:** M · **Хамаарал:** T-18 · **AC:** AC-10, AC-11
- Tool Contract → OpenAI function-calling формат 1:1; `tool_calls` хариу
  зохицуулна.
- **DoD:** T-19-тэй ижил гурван шалгалт + орчуулгын ямар ч талбар
  алдагдаагүйг батлах round-trip тест.

### T-21 · Provider Router + hot-swap endpoint
**Хэмжээ:** M · **Хамаарал:** T-19, T-20 · **AC:** AC-10
- `GET /providers`, `POST /providers/{role}/switch`. Router нь идэвхтэй
  adapter-ийн reference-ийг хадгална; солих нь reference-ийг л дахин онооно —
  process restart БАЙХГҮЙ.
- Нислэгт байсан tool call нь хуучин provider-ээр тэмдэглэгдэн дуусна
  (session-д bind).
- Provider унавал fallback нь **зөвхөн Research role**-д; Risk-ийг
  алгасах, авто-батлах зам БАЙХГҮЙ. Бүгд унавал шинэ санал гарахаа болино.
- `agent_decisions.provider` талбарт provider/model бүртгэгдэнэ.
- **DoD:** (а) солихын өмнө / дараа process start time тэнцүү;
  (б) солих агшинд идэвхтэй байсан дуудлагын attribution хуучин provider;
  (в) солих үед алдаа гарахгүй, дараагийн санал шинэ provider-ээр тэмдэглэгдэнэ;
  (г) бүх provider унасан үед санал = 0, байгаа position / order хөндөгдөхгүй.

### T-22 · Contract тест + multi-provider scenario replay
**Хэмжээ:** S · **Хамаарал:** T-21 · **AC:** AC-11
- Adapter бүрийн орчуулсан schema-г эх `v1` schema-тай validate.
- Нэг бэлдсэн сценарио (ижил оролт, ижил tool result) хоёр provider дээр
  тоглуулж Risk Agent-ийн шийдвэрийг харьцуулна.
- **DoD:** (а) schema зөрвөл тест унана; (б) provider-ээс хамааран Risk
  шийдвэр өөр гарвал тест унана; (в) suite нь UAT_TEST-ийн заавал гүйцэтгэх
  хэсэг, үр дүн sign-off-д хавсаргагдана.

---

## Эпик E — Compliance / Audit (M2-д бичигдэж, M4-д баталгаажна)

### T-23 · Hash-chained `audit_log` writer + verifier
**Хэмжээ:** M · **Хамаарал:** T-02 · **AC:** AC-17
- Мөр бүр өмнөх мөрийн hash агуулна (append-only; UPDATE / DELETE-ийг DB
  түвшинд хориглоно).
- Шийдвэр бүрийн provenance: аль agent, аль provider/model, ямар өгөгдөл
  иш татсан, Risk юу шийдсэн, юу биелсэн (хавсралт 06 §3 — хүний шийдвэр
  мэт харуулахгүй).
- `verify-chain` CLI.
- **DoD:** (а) мөрийг гараар засаад verifier алдаа буцаана; (б) мөр устгаад
  verifier алдаа буцаана; (в) chain-гүй бичих зам байхгүйг батлах тест
  (writer-ээс гадуур INSERT татгалзана).

### T-24 · Grounding checker + adversarial suite
**Хэмжээ:** L · **Хамаарал:** T-18, T-02 · **AC:** AC-7, AC-8
- Саналын `rationale` дотрх тоон утга бүр (үнэ, тоо ширхэг, хувь) нь иш
  татсан `tool_calls`-ийн бодит payload дотор байхыг механикаар шалгана.
- Унавал санал Risk-д ХҮРЭХГҮЙ; `grounding_failure` болж бүртгэгдэнэ.
- Adversarial suite: quote байхгүй symbol, өгөгдөлгүй огнооны муж, delisted
  symbol — систем `no_data` мэдээлэх ёстой.
- **DoD:** (а) payload-д байхгүй тоо агуулсан санал Risk-д хүрэхгүй
  (mock дээр Risk дуудалт = 0); (б) хоосон / байхгүй `grounded_in` татгалзана;
  (в) adversarial кейс бүрт тоо зохиосон гаралт = 0; (г) checker-ийн suite нь
  Research prompt, Tool Contract schema, adapter-ийг хөндсөн PR бүрт CI-д
  ажиллана (хавсралт 10 §4).

### T-25 · Арилжааг зөвхөн лог дээрээс сэргээх скрипт
**Хэмжээ:** M · **Хамаарал:** T-23 · **AC:** AC-18
- `reconstruct --date YYYY-MM-DD`: `audit_log` → тэр өдрийн арилжааны
  жагсаалт. Alpaca-ийн activity тайлантай харьцуулж diff гаргана.
- **DoD:** (а) сонгосон өдрийн арилжаа 100% тэнцүү (дутуу / илүү / утгын
  зөрүү = 0); (б) диff гарвал скрипт nonzero exit; (в) live-д гарахаас өмнө
  дор хаяж нэг удаа бүтнээр гүйцэтгэсэн тайлан RELEASE_APPROVAL-д хавсаргагдана.

---

## Эпик F — Auto-tuning (M5)

### T-26 · Whitelist + bounds config, өөрчлөх endpoint БАЙХГҮЙ
**Хэмжээ:** S · **Хамаарал:** T-03 · **AC:** AC-22
- Tunable параметрийн whitelist ба тоон bounds нь config-д (жишээ:
  trailing-stop %, position-size multiplier, signal confidence threshold).
- Whitelist / bounds-ыг ажиллаж байхад өөрчлөх API endpoint үүсгэхГҮЙ.
- **DoD:** (а) bounds-ийн ирмэг / гадна талын утгуудаар unit тест —
  гадуур утга татгалзаж `tuning_rejected` болно; (б) whitelist-д байхгүй
  параметр татгалзана; (в) route жагсаалтыг шалгаж whitelist / bounds
  засах endpoint байхгүйг батлах тест.

### T-27 · Bounded search + walk-forward validation
**Хэмжээ:** M · **Хамаарал:** T-26 · **AC:** AC-23
- Bounds дотор жижиг grid search; A цонхон дээр тохируулж B цонхон дээр
  out-of-sample батална (хавсралт 07 §4).
- Backtest нь зөвхөн Alpaca-ийн бодит историк bar дээр — синтетик мөр
  ХЭЗЭЭ Ч биш, гаралт `source: backtest` шошготой.
- Параметр bounds-ийнхаа ирмэг дээр давтан очвол хүний хяналтад тэмдэглэнэ —
  bounds-ыг ӨӨРӨӨ тэлэхгүй.
- Хуваарь: долоо хоног тутам (спек A-4), тасралтгүй биш.
- **DoD:** (а) зөвхөн in-sample сайжирсан өөрчлөлт CI-д **унах ёстой**;
  (б) bounds автоматаар тэлэгдэх зам байхгүйг батлах тест; (в) ирмэг дээр
  давтан хүрсэн тохиолдол хүний хяналтын тэмдэглэгээ үүсгэнэ.

### T-28 · `tuning_history` + human-gated promote
**Хэмжээ:** S · **Хамаарал:** T-27 · **AC:** AC-24
- `tuning_history`: параметр, өмнөх утга, шинэ утга, bounds, backtest цонх,
  батласан actor.
- `POST /tuning/promote` — хүний confirmation token шаардана. Token-гүй
  дуудалт татгалзана. Live config автоматаар хэзээ ч өөрчлөгдөхгүй.
- **DoD:** (а) paper дээр tuning батлагдсаны дараа live config
  өөрчлөгдөөгүйг батлах E2E; (б) token-гүй promote татгалзана;
  (в) `tuning_history`-ийн 6 талбар бүрэн бөглөгдсөн эсэхийг шалгах тест.

---

## Эпик G — Frontend (M1 → M5)

### T-29 · App shell + горимын байнгын заалт
**Хэмжээ:** M · **Хамаарал:** T-07 · **AC:** AC-21
- Layout, routing, TanStack Query, WS клиент. Горимын заалт (live / paper /
  backtest) нь бүх дэлгэц дээр байнга харагдана; live үед нүдэнд ил ялгарна.
- Backtest өгөгдөл live / paper-тай нэг жагсаалт, нэг график, нэг мөрөнд
  ХЭЗЭЭ Ч нийлэхгүй (backend-ийн T-07-ийн хоригийг UI дээр давхарлана).
- Dark pattern БАЙХГҮЙ: streak, gamification, түлхэц мэдэгдлийн спам
  хийхгүй (хавсралт 06 §3).
- **DoD:** (а) Playwright: дэлгэц бүр дээр горимын заалт байгааг шалгана;
  (б) холимог `source`-той өгөгдлийг нэг график дээр зурах оролдлого
  тест дээр унана.

### T-30 · Dashboard
**Хэмжээ:** M · **Хамаарал:** T-29, T-09 · **AC:** AC-2, AC-16
- Equity curve, нээлттэй position, нээлттэй order, өдрийн P&L, kill switch
  товч — НЭГ дэлгэц. Сүүлд шинэчилсэн UTC timestamp.
- WS тасарсны дараа 5 секунд дотор «stale» banner.
- Halt идэвхтэй үед тодорхой, байнгын анхааруулга.
- **DoD:** (а) Playwright: WS-ийг албадан салгаж 5 секунд хүлээхэд banner
  гарна; (б) halt төлөвт анхааруулга харагдана; (в) хуучин өгөгдөл
  шошгогүйгээр live мэт харагдвал тест унана.

### T-31 · Approval Queue UI
**Хэмжээ:** M · **Хамаарал:** T-29, T-17 · **AC:** AC-5, AC-6
- Хүлээгдэж буй саналын жагсаалт: agent-ийн бүрэн үндэслэлийн trace + иш
  татсан өгөгдөл. Approve / reject үйлдэл. TTL хугацаа харагдана.
- **DoD:** (а) E2E: босгоос дээш санал → queue-д мөр → approve → order;
  (б) reject → order 0; (в) TTL дууссан мөрийн approve товч боломжгүй.

### T-32 · Agent Activity Log UI (түүхий payload-той)
**Хэмжээ:** M · **Хамаарал:** T-29, T-24 · **AC:** AC-9
- Шийдвэрийн хронологи feed; agent, symbol, outcome-оор шүүнэ.
- Мөр нээхэд иш татсан `tool_calls`-ийн **түүхий payload** харагдана.
- **DoD:** (а) Playwright: нээсэн мөрийн харагдаж буй өгөгдөл нь
  `tool_calls`-ийн хадгалсан payload-тай тэнцүү; (б) дүгнэлт харагдаад эх
  өгөгдөл байхгүй мөр байвал тест унана.

### T-33 · Provider Switcher UI
**Хэмжээ:** S · **Хамаарал:** T-29, T-21 · **AC:** AC-10
- Research role-ийн одоогийн provider/model; dropdown-оор hot-swap.
- Шийдвэрийн feed дээр provider тэмдэглэгээ харагдана.
- **DoD:** (а) UI-аас солиход дараагийн санал шинэ provider-ээр тэмдэглэгдэнэ;
  (б) солих үед дэлгэц reload / restart шаардахгүй.

### T-34 · Auto-Tuning Panel
**Хэмжээ:** S · **Хамаарал:** T-29, T-28 · **AC:** AC-24
- Одоогийн параметр, bounds, `tuning_history`. Promote товч нь ил
  confirmation шаардана (token урсгал).
- Whitelist / bounds нь **зөвхөн уншихаар** харагдана — UI-аас засах зам байхгүй.
- **DoD:** (а) confirmation-гүй promote хийх зам UI-д байхгүй;
  (б) bounds засах input элемент байхгүйг батлах тест.

### T-35 · Settings дэлгэц
**Хэмжээ:** S · **Хамаарал:** T-29 · **AC:** AC-22
- Эрсдэлийн хязгаарын одоогийн утга (зөвхөн унших — өөрчлөлт нь SPEC →
  SPEC_APPROVE-ийн зам), орчин (paper / live), API key-ийн төлөв (маскласан).
- **DoD:** (а) дэлгэц дээр хязгаар засах input БАЙХГҮЙ;
  (б) key нь маскласан хэлбэрээр л харагдана (бүтэн утга network payload-д
  ч байхгүйг батлах тест).

---

## Эпик H — Тест / QA (M1 → M6)

### T-36 · Тестийн суурь + coverage gate
**Хэмжээ:** M · **Хамаарал:** T-01 · **AC:** AC-27
- pytest + testcontainers (Postgres, Redis); Playwright суурь.
- CI-ийн coverage gate: order илгээх зам ≥ 90%; Risk модуль 100% line + branch.
- **DoD:** (а) босгоос доош бол build унана; (б) gate-ийг тойрох тохиргоо
  (`# pragma: no cover` массаар, omit pattern) нэмсэн diff нь review
  checklist-д баригдана — gate-ийн тохиргооны файл нь codeowner-тэй.

### T-37 · E2E сценарио harness
**Хэмжээ:** M · **Хамаарал:** T-31, T-32 · **AC:** AC-2, AC-5, AC-9
- Бүрэн урсгал: Research санал → Risk хаалт → (approval) → Execution submit
  (paper) → Compliance лог → dashboard тусгагдана.
- **DoD:** (а) урсгал бүтнээр ногоон; (б) approve / reject / escalate гурван
  салаа тус тусдаа; (в) UI дээр иш татсан өгөгдөл харагдана.

### T-38 · Chaos тест
**Хэмжээ:** M · **Хамаарал:** T-15, T-16, T-21 · **AC:** AC-14, AC-15
- Fault injection: Alpaca холболтыг order дундуур таслах, Redis унагах,
  идэвхтэй LLM provider-ыг санал дундуур унагах.
- Хүлээлт: аюулгүй доройтол — чимээгүй уналт БИШ.
- **DoD:** (а) кейс бүрт шинэ order илгээх нь зогсоно, төлөв UI-д
  харагдана; (б) Alpaca унасан үед систем position-ыг таамаглахгүй
  (локал тооцоолол 0); (в) provider унасан үед хуучин cache-ийн санал
  биелэхгүй; (г) үр дүн UAT sign-off-д хавсаргагдана.

### T-39 · Paper proving window monitoring (30+ хоног)
**Хэмжээ:** M · **Хамаарал:** T-10, T-16, T-24 · **AC:** AC-13
- 4 метрикийн автомат тоолуур ба тайлан: эрсдэлийн хязгаар зөрчсөн тоо,
  order замын барьцаагүй exception, локал ↔ Alpaca төлөвийн зөрүү,
  grounding алдаа. Бүгд = 0 байх ёстой.
- Аль нэг > 0 бол тоолуур **0-ээс дахин** эхэлнэ.
- **DoD:** (а) reset логикийн unit тест — метрик > 0 болгоход тоолуур 0
  болно; (б) метрик > 0 байхад window үргэлжилсэн хэвээр тоологдвол тест
  унана; (в) тайлан нь RELEASE_APPROVAL-ийн нотолгоо болж гаргагдана.

### T-40 · Давтагдах build-ийн нотолгоо
**Хэмжээ:** S · **Хамаарал:** T-01 · **AC:** AC-28
- Нэг tag-аас хоёр удаа build хийж артефактын агуулгыг харьцуулна.
- **DoD:** (а) хоёр build-ийн агуулга тэнцүү; (б) pin хийгээгүй / lockfile-гүй
  хамаарал олдвол унана; (в) шалгалт release job-ийн хэсэг.

---

## Эпик I — Ажиллагааны баримт

### T-41 · Runbook
**Хэмжээ:** S · **Хамаарал:** T-16, T-25 · **AC:** AC-15, AC-18
- Circuit breaker унасан үед хэрхэн хариу үйлдэл хийх (шалтгааныг
  тодорхойлох, halt-ийг цэвэрлэх ил алхмууд) — AC-15-ийн «хүн гараар
  цэвэрлэх» нь бичигдсэн журамгүйгээр биелэхгүй.
- Live рүү promote хийх алхмууд (хавсралт 06 §5-ийн 5 нөхцөлийн checklist).
- Rollback журам.
- Audit reconstruction-ийг гүйцэтгэх алхмууд (AC-18-ийн RELEASE_APPROVAL нотолгоо).
- **DoD:** (а) halt-ийг цэвэрлэх журмыг UAT дээр өөр хүн зөвхөн runbook
  уншаад гүйцэтгэж чадна; (б) reconstruction-ийг runbook-оор гүйцэтгэсэн
  тайлан хавсаргагдсан.

---

## Backlog — v1 биш (SPEC_APPROVE-ийн хариунаас хамаарна)

| # | Task | Нөхцөл |
|---|---|---|
| T-19a | Grok adapter (OpenAI-нийцтэй, base URL / auth өөр) | OQ-3-ийн хариу «4 бүгд» бол |
| T-19b | opencode adapter (өөрийн tool-call протокол) | OQ-3-ийн хариу «4 бүгд» бол |
| T-19c | Local model adapter — fallback үед зөвхөн read-only tool | Offline fallback шаардлага гарвал |
| T-42 | Kill switch-ийн position хаах хувилбар | OQ-1-ийн хариу «хаана» бол — спек §9 A-2 ба AC-16 дахин бичигдэнэ |
| T-43 | Хоёр дахь broker adapter (FX) | Спек §3.2 — шинэ спек шаардана |

---

## 11. AC → task хучилтын матриц (урвуу шалгалт)

| AC | Task |
|---|---|
| AC-1 | T-06, T-07 |
| AC-2 | T-04, T-09, T-30, T-37 |
| AC-3 | T-08, T-13, T-14, T-18 |
| AC-4 | T-11, T-12 |
| AC-5 | T-11, T-17, T-31, T-37 |
| AC-6 | T-17, T-31 |
| AC-7 | T-02, T-24 |
| AC-8 | T-24 |
| AC-9 | T-32, T-37 |
| AC-10 | T-19, T-20, T-21, T-33 |
| AC-11 | T-18, T-19, T-20, T-22 |
| AC-12 | T-03 |
| AC-13 | T-10, T-39 |
| AC-14 | T-04, T-15, T-38 |
| AC-15 | T-16, T-38, T-41 |
| AC-16 | T-15, T-30 |
| AC-17 | T-23 |
| AC-18 | T-25, T-41 |
| AC-19 | T-01, T-05 |
| AC-20 | T-03, T-07 |
| AC-21 | T-07, T-29 |
| AC-22 | T-26, T-35 |
| AC-23 | T-27 |
| AC-24 | T-28, T-34 |
| AC-25 | T-02, T-07 |
| AC-26 | T-02 |
| AC-27 | T-08, T-12, T-36 |
| AC-28 | T-01, T-40 |

**Task-гүй AC:** байхгүй (28/28). **AC-гүй task:** байхгүй (41/41).
