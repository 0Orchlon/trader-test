<!-- PERSONAL-3 · code-review · CODE_REVIEW (7-р тойрог) · 2026-09-18 -->

# PERSONAL-3 — Кодын хяналт, 7-р тойрог

**Ажил:** PERSONAL-3 · **Салбар:** `issue/personal-3` · **Хянасан commit:** `12ec488`
**Хэмжүүр:** `docs/PERSONAL-3/lld.md` (LLD v1.0 — §19-ийн 15 шалгах цэг, §20-ийн
AC хучилт), `contracts/*.yaml`, `spec.md`-ийн AC.
**Өмнөх тойрог:** `code-review-round6.md` (commit `b6d29af`, ногоон).
**Энэ тойргийн хамрах хүрээ:** `b6d29af..12ec488` (UAT-ийн байршуулалтын
блоклогчийн засвар: U-2/U-4 Dockerfile+compose, O-1 breaker probe timeout,
O-2 health зам) + §19-ийн шалгах цэгүүдийн бие даасан дахин шалгалт +
хянагчийн буцаасан R-1/R-2 хоёрын бие даасан баталгаа.

> **Хамрах хүрээний гэрээ (LLD §19):** «Энэ загварыг дагасан эсэхийг дараах
> жагсаалтаар л шалгана. Энд байхгүй зүйлээр код буруутгахгүй.» Загварт байгаа
> атлаа кодод алгасагдсан зүйлийг §4-т тусад нь шалгав.

**Тусгаарлалт (ADR-0005 R3):** энэ тойргийн кодыг би бичээгүй — хянасан
өөрчлөлтүүд нь DEVELOPMENT шатны `6cde1aa` / `12ec488` commit-ууд.

---

## 1. Хэмжилт (энэ тойрогт өөрөө ажиллуулсан)

| Гадаргуу | Команд | Үр дүн |
|---|---|---|
| backend | `pytest -q -rw --cov=app --cov-branch` (шинэ venv, Python 3.12.13, `requirements.lock`) | **388 passed**, 0 failed, 1 warning · TOTAL **90%** · `app/risk/**` 100% |
| backend | `pytest tests/integration/test_ingest_reconcile.py -W error::RuntimeWarning` | 18 passed — `coroutine … never awaited` үүсэхгүй (R-2) |
| frontend | `npm ci && npm test` | `check:api` (`api.generated.ts` нь гэрээтэй тэнцүү) ✓ · `eslint` ✓ · `tsc --noEmit` ✓ · **66 passed / 6 файл** |
| contracts | `npm ci && npm test` | `redocly lint` valid · `bundle шалгалт OK` · `дуурайлтын шалгалт OK — 10 зам, 5 үл хөдлөх дүрэм` |
| deploy cfg | `docker compose -f docker-compose.dev.yml config -q` | exit 0 — postgres / redis / backend / frontend дөрвүүлээ зөв тодорхойлогдсон |

Ажлын мод цэвэр, `origin/issue/personal-3` нь `12ec488` дээр.

> **Орчны тэмдэглэл:** host-ийн анхдагч Python нь 3.14 бөгөөд төсөл нь
> `>=3.12,<3.13` — 3.14 дээр SQLAlchemy 2.0.36 нь модель импортлох үед унана
> (`TypeError: descriptor '__getitem__' …`). Энэ нь кодын алдаа БИШ, pin-ийн
> биелэл; хэмжилтийг 3.12.13 venv дээр хийв. `backend/Dockerfile` нь яг үүнийг
> шийдэж байгаа (U-4).

---

## 2. Хянагчийн буцаасан хоёр зүйл — бие даасан баталгаа

| # | Хянагчийн үг | Байдал | Нотолгоо (энэ тойрогт өөрөө уншсан / ажиллуулсан) |
|---|---|---|---|
| R-1 | `build()` нь `settings.REDIS_URL`-ийг EventBus-руу дамжуулдаггүй | **Хаагдсан** | `app/main.py:216` — `bus = EventBus(redis=_make_redis(settings.REDIS_URL))`; `_make_redis` нь URL байвал `redis.asyncio.from_url`. `app/main.py:174-175` — Redis байгаа үед `bus.bridge()` task болж асна (AC-14 «бүх холбогдсон клиент»). `app/api/routes_read.py:45-53` — health нь бодит `ping()` хийнэ, «тохируулсан»-ыг «хүрэх боломжтой» гэж таамаглахгүй. `docker-compose.dev.yml` нь backend-д `REDIS_URL=redis://redis:6379/0` өгнө |
| R-2 | `app/stream/ingest.py` — `stream_trade_updates() coroutine never awaited` | **Хаагдсан** | `run_forever()`-ийн `finally` нь мөчлөг ямар ч замаар дуусахад `_close(stream)` дуудна (`aclose` / `close` хоёуланг барина). `-W error::RuntimeWarning`-тэй ажиллуулахад ingest-ийн 18 тест ногоон; бүтэн багцын цорын ганц warning нь гуравдагч талын starlette deprecation |

---

## 3. §19-ийн 15 шалгах цэг

| # | Цэг | Үр дүн | Нотолгоо |
|---|---|---|---|
| 1 | `submit_order`-ийн дуудагч зөвхөн `app/execution` | ✅ | Эх код дээрх цорын ганц дуудалт: `app/execution/agent.py:89`. `tests/static/test_import_gates.py` хаалга |
| 2 | `ValidatedOrder` нь Risk-ийн APPROVE салаанаас л | ✅ | Цорын ганц үүсгэлт: `app/risk/agent.py:127` |
| 3 | `orders.origin` NOT NULL, анхдагчгүй | ✅ | `app/models.py:67` — `nullable=False`, `default` алга |
| 4 | `system_state` Postgres-д, startup УНШИНА | ✅ | `app/main.py` lifespan → `machine.ensure_initialised()`; эхлүүлэх шилжилт алга |
| 5 | `halted → winding_down` шилжилт кодод байхгүй | ✅ | `app/system/state.py:184-186` — `HALTED`-аас wind-down нь `InvalidTransition("already_halted")` |
| 6 | `activate` нь breaker-ийг ДАХИН хэмжинэ | ✅ | `app/api/routes_system.py:106-121` — `CircuitBreaker(...).tripped()`, хадгалсан «цэвэрлэсэн» туг алга |
| 7 | Гарын order нь `agent_decisions` мөр үүсгэхгүй | ✅ | `app/api/routes_orders.py` гарын зам нь `origin=MANUAL_OPERATOR` л бичнэ |
| 8 | Position-ийн origin — олдохгүй бол `external` | ✅ | `app/api/attribution.py` — `origins.get(symbol, EXTERNAL)`; WS payload-д `known_locally` ил |
| 9 | `tool_calls` бичилт нь LLM-д хариу буцахаас ӨМНӨ | ✅ | `app/agents/gateway.py:138-164` — INSERT → handler → response + latency → commit, дараа нь envelope |
| 10 | Tool result бүрд `system_state`, schema-д `required` | ✅ | `contracts/tool-contract.v1.yaml:34` — `required: [tool_call_id, timestamp, source, system_state, ok]` |
| 11 | Grounding унавал Risk хүртэл очихгүй | ✅ | `app/agents/tools.py` — `passed=false` бол `grounding_failed`-аар эрт буцна |
| 12 | `audit_log` дээр UPDATE/DELETE татгалзах trigger | ✅ | `migrations/postgres_append_only.sql` — `audit_log` ба `system_state` хоёулаа UPDATE / DELETE / TRUNCATE дээр `RAISE EXCEPTION` |
| 13 | §7-ийн хязгаарууд кодод анхдагчгүй | ✅ | `app/config/settings.py` — 10 талбар анхдагчгүй; `DAILY_LOSS_LIMIT` эерэг байвал app эхлэхээсээ өмнө унана |
| 14 | Нэг хүснэгтэд хоёр `source` зэрэг харагдахгүй | ✅ | Backend `MixedSourceError` → 500; `frontend/src/lib/source.ts` нь мөр тус бүрийн source-ыг барина |
| 15 | Settings дэлгэцэд хязгаар засах талбар БАЙХГҮЙ | ✅ | `SettingsPage.tsx`-д `input` / `onChange` ерөөсөө алга |

---

## 4. Загварт байгаа атлаа алгассан зүйл байна уу

| Загварын элемент | Байдал |
|---|---|
| §2.1 `BrokerPort`-ийн 7 метод | Бүгд бий (`app/broker/port.py`); async + `Envelope` болсон нь LLD §7-ийн ил шийдвэр |
| §5-ийн 10 хүснэгт | Бүгд бий; `breaker_events` нь §15.2-ын метрикийн эх сурвалж болж нэмэгдсэн (загварт §15.2-т заасан) |
| §3 Frontend 6 дэлгэц | Dashboard · Approvals · Decisions · Tuning · Providers · Settings — зургаан ч зам бий |
| §4 Agent Gateway-ийн tool жагсаалт | `get_account`, `get_positions`, `get_quote`, `get_bars`, `get_backtest_result`, `get_tuning_bounds`, `propose_order`, `propose_tuning_change` — гэрээнд бүгд |
| §6 уналтын горимууд | Broker хүрэхгүй → `BrokerUnavailable` (кэшнээс хуучин утга буцаах зам алга); WS тасрал → `StalenessBanner`; provider уналт → §12.3 fallback, read-only үед шинэ санал гарахгүй; хэсэгчилсэн биелэлт → `fills` + EOD reconcile |
| §12.2 олон instance дээрх hot-swap | `follow_switches` + `restore_active` (U-3-ийн засвар) |
| §3-ийн `adapters/opencode_stdio.py` | **Байхгүй** — `plan.md` P-2 / `tasks.md` T-19b-ээр OQ-3-ийн хариунаас хамааруулж зориуд хойшлуулсан. Grok нь `openai_fc.XaiFcAdapter`-ээр бий тул AC-11 («≥2 provider») хангагдсан. **Блоклогч биш** — батлагдсан төлөвлөгөөний хамрах хүрээ |
| §3-ийн файлын нэрс (`api/account.py`, `stream/fanout.py`, Alembic, `uv.lock`) | Кодод `routes_*.py`, `stream/bus.py` + `ingest.py`, метадата-migration, `requirements.lock` — баримтжуулсан зориудын хазайлт (шалтгаан нь `app/migrate.py`-ийн толгойд ил). §19-д ороогүй, зан төлөв өөрчлөгдөөгүй |

---

## 5. Энэ тойргийн өөрчлөлтийн үнэлгээ (`b6d29af..12ec488`)

| Өөрчлөлт | Дүгнэлт |
|---|---|
| `backend/Dockerfile` (U-4) | Python 3.12-slim; хамаарал ЗӨВХӨН `requirements.lock`-оос (T-1-ийн pin тойрогдохгүй); `CMD` нь `python -m app.migrate && uvicorn … --factory`. `build()` нь prod-ийн орох цэг тул scheduler + ingestion асна — LLD §2-той нийцнэ |
| `frontend/Dockerfile` (U-2) | Multi-stage: `npm ci && npm run build` нь image дотор, статик нь image-д шатсан. Build context нь репогийн root тул `contracts/openapi.yaml` (`check:api`) ба `ci/nginx.conf` хоёулаа орно. Host хавтаснаас bind mount алга — U-2-ын үндэс хаагдсан |
| `docker-compose.dev.yml` | Postgres + Redis + backend + frontend (LLD §2-ын дэд бүтэц). `ALPACA_ENV` дарж бичигдээгүй тул `paper` хэвээр (LLD §5 — «live анхдагч байх орчин БАЙХГҮЙ»). Түлхүүр зөвхөн орчноос, репод алга |
| `breaker.BROKER_PROBE_TIMEOUT = 2.0` (O-1) | `asyncio.timeout` нь `except Exception`-д баригдаж метрикийг `unmeasured` болгоно — худал ногоон биш, худал халтаас ч биш. 5s job интервал > 2s probe тул ажиллалт хуримтлахгүй |
| `scheduler`-ийн `max_instances=1` / `coalesce` / `misfire_grace_time` | Хоёр дахь давхарга; APScheduler-ийн 1 секундын анхдагч grace-ээс сайжирсан |
| `ci/nginx.conf`-ийн `location = /health` | `proxy_pass http://${BACKEND}/api/v1/health` — яг тааруулалт + URI солилт зөв. Location-ыг устгаагүй нь чухал: устгасан бол SPA-ийн `index.html` `200` буцааж монитор худал ногоон болно |

---

## 6. Зогсоохгүй ажиглалтууд (энэ тойрогт засах шаардлагагүй)

| # | Байршил | Ажиглалт |
|---|---|---|
| N-1 | `app/api/routes_read.py` health | `"database": {"name": "postgres", "reachable": true}` нь хатуу утга. Худал ногоон болох зам харагдахгүй (өмнөх `machine.current()` нь DB-г үнэхээр хөнддөг тул DB унасан үед хариу 500 болно), гэхдээ `DATABASE_URL` sqlite үед нэр буруу харагдана |
| N-2 | `contracts/verify-mock.mjs` | prism-ийг `stdio: 'ignore'`-оор асаадаг тул порт завгүй үед «prism mock 60 секундэд босоогүй» гэсэн ташаа онош гарна. Энэ тойрогт яг ийм ташаа улаан нэг удаа тохиолдсон (зэрэгцээ ажиллалт 4011-ийг эзэлсэн); өөр портоор дахин ажиллуулахад ногоон. Гэрээний асуудал БИШ |
| N-3 | `backend/Dockerfile` | Контейнер root-оор ажиллана; олон instance-тай байршуулалтад эхлэх бүрд `app.migrate` ажиллах нь онолын хувьд зэрэгцээ DDL уралдаан үүсгэж болно (одоогийн compose 1 instance) |

---

## 7. Дүгнэлт

**НОГООН — цааш дамжина.** §19-ийн 15 шалгах цэг бүгд биелсэн, хянагчийн
буцаасан R-1 / R-2 хоёр бие даан баталгаажсан, гурван гадаргуугийн тест бүгд
өөрийн ажиллалтад ногоон (backend 388 / frontend 66 / contracts). Загварт
байгаа атлаа алгассан блоклогч элемент олдсонгүй.

**Шалгаж ЧАДААГҮЙ зүйлс (ил цоорхой):**

1. **Alpaca-ийн түлхүүр алга** — order-ийн бодит зам (submit → fill → WS trade
   update) амьд paper дансанд энэ тойрогт дахин шалгагдаагүй. Энэ тойргийн код
   өөрчлөлт тэр замыг хөндөөгүй; амьд баталгааны бичлэг `uat-test-report.md`-д.
2. **Контейнер стекийг энэ тойрогт асаагаагүй** — зөвхөн `compose config`
   шалгасан. Амьд стекийн баталгаа нь өмнөх шатны `uat-test-report-round2.md`
   (direct / proxy health `200`, 90 секундэд `max instances` 0 удаа).
3. **Mutation тест (mutmut)** дахин ажиллуулаагүй — 6-р тойрогт `adopt`-ын
   гар мутацаар шалгагдсан.
4. **Registry / Harbor push** тодорхойлогдоогүй хэвээр — UAT локал `--build`-аар
   угсарна.
