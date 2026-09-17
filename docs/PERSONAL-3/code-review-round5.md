<!-- PERSONAL-3 · code-review · CODE_REVIEW (5-р тойрог) · 2026-09-17 -->

# PERSONAL-3 — Кодын хяналт, 5-р тойрог

**Ажил:** PERSONAL-3 · **Салбар:** `issue/personal-3` · **Хянасан commit:** `2e6e825`
**Хэмжүүр:** `docs/PERSONAL-3/lld.md` (LLD v1.0) — ялангуяа §19-ийн «шалгах
боломжтой 15 цэг», `docs/PERSONAL-3/contracts.yaml` (v1.1.0), `spec.md`-ийн AC.
**Өмнөх тойрог:** `code-review-round4.md` (commit `d17cd8c`, ногоон).
**Энэ тойргийн хамрах хүрээ:** `d17cd8c..2e6e825` дэлгэрэнгүй (UAT 4/5-р
тойргийн засварууд) + §19-ийн 15 цэгийн бүрэн дахин шалгалт.

> **Хамрах хүрээний гэрээ (LLD §0):** загварт бичигдсэн зүйлийг шалгав.
> Загварт байхгүй зүйлээр кодыг буруутгаагүй; загварт байгаа зүйлийг
> алгассан эсэхийг тусад нь шалгав.

---

## 1. Хэмжилт (энэ тойрогт өөрөө ажиллуулсан)

| Гадаргуу | Команд | Үр дүн |
|---|---|---|
| backend | `pytest -q --cov` (Python 3.12.13, шинэ venv, `requirements.lock`) | **377 passed**, 0 failed, exit 0 · TOTAL 90% · `app/risk/**` 100% line+branch |
| backend | `pytest -q -rw` (сэрэмжлүүлгийн жагсаалттай) | **377 passed, 1 warning** — цорын ганц warning нь гуравдагч талынх: `starlette/testclient.py:40 … anyio.abc.BlockingPortal alias is deprecated`. `coroutine … never awaited` warning БАЙХГҮЙ. |
| backend | Coverage gate-ийн бодит үйлчлэл | Тусад нь шалгав: ганц файлаар (`tests/unit/test_alpaca_stream.py --cov`, нийт 7%) ажиллуулахад **exit=1** — босго үнэхээр хаадаг, гоёл биш. |
| contracts | `npm ci && npm test` | `redocly lint` valid · `bundle шалгалт OK` (⇒ `docs/PERSONAL-3/contracts.yaml` нь эх файлуудтай тэнцүү) · `дуурайлтын шалгалт OK — 10 зам, 5 үл хөдлөх дүрэм` |
| frontend | `npm ci && npm test` | `check:api` — `src/lib/api.generated.ts` гэрээтэй ТЭНЦҮҮ · `eslint` цэвэр · `tsc --noEmit` цэвэр · **66 passed / 6 файл** |

---

## 2. Хянагчийн буцаасан хоёр зүйл — баталгаажуулалт

| # | Хянагчийн үг | Байдал | Нотолгоо |
|---|---|---|---|
| R-1 | `build()` нь `settings.REDIS_URL`-ийг EventBus-руу дамжуулдаггүй тул health доторх `redis.reachable=false` | **Хаагдав** (commit `03b49ba`) | `app/main.py:205` — `bus = EventBus(redis=_make_redis(settings.REDIS_URL))`; `_make_redis()` нь URL хоосон бол `None`. `app/main.py:174-175` — redis тохируулагдсан үед `bus.bridge()` (Redis → локал fan-in) task болж асна, ингэснээр олон instance үед нэг instance-ийн `system` мессеж нөгөөгийн WS клиентэд хүрнэ (AC-14). `app/api/routes_read.py:46-53` — health нь «тохируулсан» гэдгийг «хүрэх боломжтой» гэж ТААМАГЛАХГҮЙ, үнэхээр `ping()` хийнэ. `tests/unit/test_bus.py:136-160` — хоёр bus нэг Redis дээр, өөрийн мессежийг давхардуулахгүй. |
| R-2 | `app/stream/ingest.py:211` — `stream_trade_updates() coroutine never awaited` | **Хаагдав** (commit `03b49ba`) | `app/stream/ingest.py:45-59` — `_close()` нь `aclose` (async generator) ба `close` (coroutine) хоёуланг нь хаана; `run_forever()`-ийн `finally` (`ingest.py:236-240`) мөчлөг ямар ч замаар дуусахад дуудагдана, `stream = None` эхлэлтэй тул `stream_trade_updates()` нь дуудагдаж чадаагүй тохиолдолд ч аюулгүй. Бүтэн багц дээр `-rw`-ээр шалгахад `never awaited` warning гараагүй (§1). `tests/unit/test_alpaca_stream.py:86,96` — урсгал хэвийн ба алдаатай дуусахад `socket.closed is True`. |

Хоёулаа DEVELOPMENT дээр засагдаж, HEAD (`2e6e825`) дээр хүчинтэй.

---

## 3. 5-р тойргийн өөрчлөлт ↔ LLD тулгалт

| Өөрчлөлт | LLD-ийн заалт | Дүгнэлт |
|---|---|---|
| `AlpacaAdapter.stream_trade_updates()` бодит WS болов (`app/broker/alpaca.py:344-402`) | §7-ийн `BrokerPort` нь `stream_trade_updates()`-ийг гэрээний хэсэг болгон шаардана; §7 «буулгана, тооцохгүй» (AC-1); §17.3 live egress | **Нийцэв.** `auth → authorization → listen → trade_updates` дараалал бүтэн; `authorization` нь `authorized` биш бол `BrokerUnavailable` (чимээгүй хүлээх холболт байхгүй); `check_egress(url)` нь WS замд ч дайрна (`test_live_stream_host_is_blocked_inside_tests`); `map_trade_update` нь Alpaca-ийн `filled_avg_price`-ыг буулгана, `qty × price` тооцохгүй. `stream_market_data` нь `NotImplementedError` хэвээр — LLD §22 «v1-д market-data WS БАЙХГҮЙ, `ticks` суваг НӨӨЦЛӨГДСӨН» гэсэнтэй нийцнэ. |
| 422 нь Problem гэрээг хангана (`app/main.py:129-150`) | §4 — алдааны нэгдсэн хэлбэр; `contracts.yaml`-ийн `Problem` | **Нийцэв.** `RequestValidationError` → `code=invalid_request` + `errors[] {loc,msg}`; гэрээний enum-д `invalid_request` нэмэгдсэн (нэмэлт өөрчлөлт, v1.1.0); контрактын статик тест (`tests/static/test_contract_coverage.py`) ба `tests/integration/test_problem_contract.py` ногоон. |
| Broker-ийн татгалзал ≠ уналт (`app/broker/models.py:203-216`, `alpaca.py:277-289`, `execution/agent.py:90-98`) | §15.2 — `api_error_rate` нь Alpaca-ийн **алдаа**-ны метрик, `order_reject_rate` нь reject-ийн метрик (хоёр тусдаа мөр) | **Нийцэв.** 400/403/409/422 → `BrokerRejected` → 422 `broker_rejected` + `broker_code`; 401/429/5xx/сүлжээ → `BrokerUnavailable` → 503. Татгалзал `api_error`-д `ok=True` гэж бичигдэнэ (broker амьд), харин `ExecutionAgent` `order_reject`-д `ok=False` бичээд `_fail()`-ээр **commit хийнэ** — хүсэлтийн rollback тоолуурыг арчихгүй. WS зам синхрон татгалзлыг давхар тоолохгүй (trade-update үүсэхгүй). |
| `migrate.py` нь `postgres_append_only.sql`-ийг asyncpg-ийн simple query protocol-оор ажиллуулна | §5.7 — append-only trigger-ууд Postgres дээр | **Нийцэв** (зан төлөв өөрчлөгдөөгүй; `engine.url.get_backend_name() != "postgresql"` хамгаалалт хэвээр). Ажиглалт N-4-ийг үз. |
| `docker-compose.dev.yml` нэмэгдэв | Загварт байхгүй (DEV дэд бүтэц) | Зөрчил биш — runbook-ийн дагалдах хэрэгсэл, ажиллах кодод нөлөөгүй. |

---

## 4. LLD §19-ийн 15 шалгах цэг (бүрэн дахин шалгалт)

| # | Цэг | Байдал | Нотолгоо |
|---|---|---|---|
| 1 | `submit_order`-ийн дуудагч зөвхөн `app/execution` | ✅ | Ганц дуудалт `app/execution/agent.py:89`; бусад бүх дурдагдал нь тайлбар. Статик хаалга `tests/static/test_import_gates.py::test_r1_...` ногоон. |
| 2 | `ValidatedOrder` нь `risk.evaluate()`-ээс л үүснэ | ✅ | Байгуулалт ганц газар: `app/risk/agent.py:127`. |
| 3 | `orders.origin` `NOT NULL`, анхдагчгүй | ✅ | `app/models.py:67` (`nullable=False`, `default`/`server_default` байхгүй) + `ck_orders_origin`. |
| 4 | Төлөв Postgres-д; startup УНШИНА | ✅ | `app/main.py:40-47` → `app/system/state.py:117` `ensure_initialised()`; мөр байхгүй бол `halted`/`initial_deploy`, grace унтарсан үед дууссан бол `halted`. |
| 5 | `halted → winding_down` шилжилт БАЙХГҮЙ | ✅ | `app/system/state.py:184-187` — `WINDING_DOWN` руу зөвхөн `ACTIVE`-аас; эс бөгөөс `InvalidTransition`. |
| 6 | `activate` нь метрикийг ДАХИН хэмжинэ | ✅ | `app/api/routes_system.py:110-122` — `CircuitBreaker(...).tripped()` шинэ хэмжилт; «цэвэрлэсэн» туг кодод байхгүй. |
| 7 | Гарын order `agent_decisions` мөр үүсгэхгүй | ✅ | `app/api/routes_orders.py` дотор `AgentDecision` огт хэрэглэгдээгүй (grep 0). |
| 8 | Локал fill байхгүй бол `external` | ✅ | `app/api/attribution.py:34,68` — `origins.get(symbol, EXTERNAL)`; «хамгийн ойрын» тааруулга байхгүй. |
| 9 | `tool_calls` бичилт нь LLM-д буцахаас ӨМНӨ | ✅ | `app/agents/gateway.py:160-167` — `call.response` + `commit()` хийсний ДАРАА `envelope(...)` буцна. |
| 10 | Tool result бүрд `system_state`, schema-д `required` | ✅ | `gateway.py:94` талбарыг үргэлж бичнэ; `docs/PERSONAL-3/contracts.yaml:2107` `required: [tool_call_id, timestamp, source, system_state, ok]`. |
| 11 | Grounding унавал Risk хүртэл ОЧИХГҮЙ | ✅ | `app/agents/tools.py` — `STAGE_GROUNDING_FAILED` салаа нь шийдвэрийг бичээд буцна; `build_risk_context`/`evaluate` дараа нь дуудагдана. |
| 12 | `audit_log` дээр UPDATE/DELETE татгалзах trigger | ✅ | `backend/migrations/postgres_append_only.sql` — `p3_refuse_mutation()` + UPDATE/DELETE/TRUNCATE trigger (`audit_log`, `system_state`); `tests/static/test_append_only_sql.py` ногоон. |
| 13 | §7-ийн 10 хязгаар кодод анхдагчгүй | ✅ | `app/config/settings.py:19-31` (`REQUIRED_LIMIT_FIELDS` 10 талбар) ба `:46-56` — бүгд зарлалт төдий, анхдагчгүй. |
| 14 | Нэг хүснэгтэд хоёр `source` харагдахгүй | ✅ | Backend: `app/api/envelope.py:32-38` `single_source()` → `MixedSourceError` → 500. Frontend: `DecisionsPage.tsx` холимог үед хүснэгтийг ОГТ гаргахгүй. |
| 15 | Settings дэлгэцэд хязгаар засах талбар БАЙХГҮЙ | ✅ | `frontend/src/features/settings/SettingsPage.tsx` — `input`/`form` элемент байхгүй, `settings-readonly` мэдэгдэлтэй. |

---

## 5. ЗОГСООХ ЗӨРЧИЛ

**БАЙХГҮЙ.** §19-ийн 15 цэг, хянагчийн буцаасан хоёр зүйл, 5-р тойргийн
гурван засвар бүгд шалгагдаж ногоон; дөрвөн шалгалтын багц (backend 377 +
coverage gate, frontend 66 + lint/typecheck/generated-check, contracts
lint/bundle/mock) өөрөө ажиллуулахад ногоон.

---

## 6. Ажиглалт (зогсоолт БИШ, бүртгэгдэв)

| # | Ажиглалт | Байршил |
|---|---|---|
| N-1 | **Coverage gate чимээгүй.** `pytest_sessionfinish`-ийн `reporter.write_line(...)` мессеж энэ орчинд ХЭВЛЭГДЭХГҮЙ (`coverage gate: ногоон` ч, `coverage gate УНАВ — …` ч). Gate өөрөө ажиллаж байгаа нь батлагдсан (7% coverage дээр exit=1), тиймээс аюулгүй тал руу унана, гэхдээ унасан тохиолдолд CI-ийн log нь «бүх тест тэнцсэн, exit 1» гэсэн оньсого харуулна — унасан шалтгаан нь log-д харагдахгүй. | `backend/tests/conftest.py:175-205` |
| N-2 | **422-ийн redaction тестгүй.** `_validation_handler` нь оролтын утгыг зориуд буцаахгүй (зөвхөн `loc`, `msg`), гэхдээ `test_problem_contract.py` нь «утга алга» гэдгийг assert хийхгүй. Pydantic-ийн ирээдүйн мессеж утгыг агуулбал чимээгүй алдагдана. | `backend/app/main.py:141-150`, `backend/tests/integration/test_problem_contract.py:62-76` |
| N-3 | **`broker_code` UI-д харагдахгүй.** Гэрээ v1.1.0-д талбар нэмэгдсэн ч `ManualTicketPage` нь зөвхөн `detail`-ыг харуулна. LLD §16.5 үүнийг шаардаагүй тул зөрчил биш; гэхдээ «яагаад татгалзав» гэдгийн хамгийн тодорхой нотолгоо (ж: `42210000` wash trade) operator-т хүрэхгүй. | `frontend/src/features/manualTicket/ManualTicketPage.tsx:150-157,284` |
| N-4 | **`migrate.py` нь asyncpg-д хатуу холбогдов.** `raw.driver_connection.execute(sql)` нь asyncpg-ийн API. Driver солих (psycopg) нь миграцийг чимээгүй бус — шууд унагаана, тиймээс аюулгүй; хамаарал нь `requirements.lock`-д `asyncpg==0.30.0` гэж pin хийгдсэн. | `backend/app/migrate.py:28-36` |
| N-5 | **WS frame нь JSON гэж таамаглагдсан.** `json.loads(frame)` нь bytes-ийг ч уншина, гэхдээ Alpaca msgpack тохиролцвол задрахгүй → `BrokerUnavailable` → `ws_disconnect` мөчлөг. Alpaca-ийн анхдагч нь JSON тул хүлээгдэж буй байдал зөв; бодит холболтоор баталгаажаагүй (§7-ийг үз). | `backend/app/broker/alpaca.py:373-374` |
| N-6 | **4-р тойргийн ажиглалтууд нээлттэй хэвээр:** Agent Gateway нь үйлдвэрлэлийн урсгалд холбогдоогүй (загварын нүх, кодын алдаа биш), Settings дэлгэц хязгааруудыг харуулахгүй, `audit_log.seq` аппликейшнээс оноогдоно, модулийн нэрлэл §3-аас зөрүүтэй. Аль нь ч энэ тойрогт өөрчлөгдөөгүй. | `code-review-round4.md` §6 |

---

## 7. Энэ хяналтад ШАЛГААГҮЙ зүйлс (ил заалт — «ногоон» гэж ойлгож БОЛОХГҮЙ)

- **Бодит Postgres.** Тест SQLite дээр ажилласан; `postgres_append_only.sql`-ийн
  trigger болон `SELECT … FOR UPDATE`-ийн мөрийн lock зөвхөн уншиж шалгагдав.
- **Бодит Alpaca (paper/live).** WS handshake нь хуурамч socket дээр Alpaca-ийн
  баримтын payload-оор шалгагдсан; сүлжээгээр нэг ч дуудалт хийгээгүй
  (`LiveEgressGuard` нь live руу гарахыг тестэд хориглоно). Бодит `/stream`
  холболт DEV_TEST/UAT-д батлагдана.
- **Бодит Redis дээрх олон instance fan-out.** `bridge()` нь хуурамч Redis-ээр
  шалгагдсан; хоёр процессын бодит pub/sub ажиллуулаагүй.
- **Browser түвшний assert (Playwright).** Репод байхгүй; хориг vitest түвшинд.
- **Backtest зам, 30 хоногийн paper proving window, mutation тест (`mutmut`).**
  Энэ тойрогт ажиллуулаагүй.
- **LLM ↔ Gateway-ийн бодит гүйцэтгэл** (N-6-ийн үр дагавар).

---

## 8. Дүгнэлт

**ӨНГӨРӨВ (ногоон).** Хянагчийн буцаасан хоёр зүйл (REDIS_URL → EventBus,
урсгалын цэвэрлэгээ) кодод бодитоор хаагдсаныг баталлаа; 5-р тойргийн гурван
засвар (бодит trade-update WS, Problem-ийн 422, broker-ийн татгалзлыг уналтаас
салгасан) нь LLD §7, §15.2, §4-тэй нийцэж байна; §19-ийн 15 шалгах цэг бүгд
биелэв; дөрвөн гадаргууны шалгалт өөрөө ажиллуулахад ногоон (backend 377 +
coverage gate exit-оор батлагдсан, frontend 66, contracts).

Үлдсэн зургаан ажиглалтын аль нь ч аюулгүй байдлын хаалгыг сулруулаагүй.
§7-ийн шалгаагүй жагсаалт нь хамрах хүрээний ил заалт бөгөөд «ногоон» гэж
тооцогдохгүй — ялангуяа бодит Alpaca WS холболт ба бодит Postgres/Redis нь
DEV_TEST шатны хариуцлага.
