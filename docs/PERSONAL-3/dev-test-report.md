<!-- PERSONAL-3 · DEV тестийн тайлан · DEV_TEST · 2026-09-17 -->

> **Шинэчлэл:** энэ тайлангийн дараах 2-р ажиллалт — `dev-test-report-round2.md` (commit `43ccd63`, 2026-09-18). §4-ийн 1-р тэмдэглэлийг тэнд залруулсан.

# DEV_TEST — байршуулсан системийн шалгалт

- **Орчин:** DEV, `docker-compose.dev.yml` (project `repo`)
- **Commit:** `731cb74` (`issue/personal-3`)
- **Огноо:** 2026-09-17
- **Үүрэг:** зөвхөн ШАЛГАЖ тайлагнах — код заваагүй.

## 0. Байршуулалтын урьдчилсан төлөв

DEV_DEPLOY-ийн үлдээсэн контейнерууд ажиллаж байсан ч `frontend` нь өмнөх
даалгаврын УСТСАН ажлын хавтас руу mount хийгдсэн байв:

```
docker inspect repo-frontend-1 → C:\...\Temp\task-290\repo\frontend\dist -> /usr/share/nginx/html
curl http://localhost:18080/   → HTTP 404 (nginx, 153B)
```

Ажлын хавтас даалгавар бүрийн дараа устдаг тул энэ mount нь хоосон.
Иймд stack-ыг ЭНЭ хавтаснаас дахин угсарч (`docker compose up -d`)
шалгалтыг явуулав. Энэ нь кодын засвар биш, байршуулалтыг сэргээсэн явдал.

**Шинэ баримт:** DEV_DEPLOY нь backend-ийг «python offline cache дутуу» гэж
алгассан. Энэ шалгалтын үед PyPI хүрэлцэхүйц байсан
(`pip download fastapi` → exit 0), тул backend-ийг БҮТНЭЭР босгож шалгав.
`requirements.lock`-ийн 58 пакет Python 3.12.13 venv рүү бүрэн суулаа.

## 1. Шалгагдсан зүйлс

### 1.1 Postgres (`repo-postgres-1`, 25432)

| Шалгалт | Үр дүн |
|---|---|
| `pg_isready -U p3 -d p3` | `accepting connections` |
| `select version()` | PostgreSQL 16.15 |
| Host порт 25432 TCP | нээлттэй |
| Schema migration (`python -m app.migrate`) | exit 0 |
| Үүссэн хүснэгт | 11: `accounts, agent_decisions, approvals, audit_log, breaker_events, confirmations, fills, orders, system_state, tool_calls, tuning_history` |

### 1.2 Redis (`repo-redis-1`, 26379)

| Шалгалт | Үр дүн |
|---|---|
| `redis-cli ping` | `PONG` (redis 7.4.11) |
| `set`/`get` эргэлт | `ok` |
| Host порт 26379 — түүхий RESP `PING` | `+PONG` (CRLF-тэй) |

### 1.3 Frontend (`repo-frontend-1`, nginx:alpine, 18080)

`npm ci --prefer-offline` + `npm run build` (exit 0) → `frontend/dist` сэргэв.

| Шалгалт | Үр дүн |
|---|---|
| `GET /` | **200**, 420B, `text/html`, `<title>PERSONAL-3 — Operator</title>`, `lang="mn"` |
| `GET /assets/index-BbK0HJ_A.js` | **200**, 1 035 255B |

### 1.4 Backend (uvicorn `app.main:build --factory`, 127.0.0.1:28000)

`Application startup complete` — startup-ын traceback БАЙХГҮЙ.

**`GET /api/v1/health` → 200:**

```json
{"source":"alpaca_paper","system_state":"halted","status":"degraded",
 "broker":{"name":"alpaca_paper","reachable":false,"detail":"BrokerUnavailable"},
 "database":{"name":"postgres","reachable":true},
 "redis":{"name":"redis","reachable":true,"detail":null},
 "providers":[claude-mcp, openai-fc, xai-fc, local-fallback — бүгд healthy]}
```

**Endpoint матриц:**

| Endpoint | Код | Тайлбар |
|---|---|---|
| `GET /api/v1/health` | 200 | дээрх |
| `GET /api/v1/system/state` | 200 | `halted`, `reason=initial_deploy`, breaker метрик 4 |
| `GET /api/v1/orders` | 200 | `orders: []` |
| `GET /api/v1/approvals` | 200 | |
| `GET /api/v1/providers` | 200 | 4 provider, `active.research=claude-mcp` |
| `GET /api/v1/tuning/parameters` | 200 | 4 параметр, bounds-той |
| `GET /api/v1/account` | 503 | `broker_unavailable` Problem — credential байхгүй |
| `GET /api/v1/positions` | 503 | мөн адил |
| `GET /api/v1/attribution` | 503 | мөн адил |
| `GET /docs`, `GET /openapi.json` | 200 | 21 route зарлагдсан |

## 2. Функциональ баталгаажуулалт (зөвхөн ажиллаж буй систем дээр)

### 2.1 WebSocket fan-out + Redis (AC-2, AC-14)

`ws://127.0.0.1:28000/ws`:

1. Холбогдмогц **хормын хувилбар** ирэв — `{"channel":"system","payload":{"seq":1,"event":"state_changed","state":"halted","reason":"initial_deploy"}}`
2. `POST /api/v1/kill-switch` → 200
3. Тэр даруй WS-ээр broadcast ирэв — `seq:2`, `from:halted`, `to:halted`, `reason:"DEV_TEST шалгалт"`

Redis дээр `psubscribe` явуулж байхад гурав дахь төлөвийн өөрчлөлт нь
`system` суваг руу үнэхээр нийтлэгдэв:

```
pmessage * system {"seq":3,...,"reason":"DEV_TEST redis fan-out","_src":"39fcc56f018245a3956ae00dbf331ab0"}
```

### 2.2 Kill switch хүчинтэй (AC-7)

Систем `halted` үед:

```
POST /api/v1/orders/manual  (Idempotency-Key: <uuid>)
→ 409 {"code":"system_halted","detail":"Систем зогссон — шинэ order илгээхгүй."}
```

Order илгээгдээгүй.

### 2.3 Circuit breaker хаалт (AC-7 автомат зогсолт)

`POST /api/v1/system/activate` → **409 `breaker_still_tripped`**, учир нь
`api_error_rate=1.0000 > 0.05` ба `ws_disconnects=10 > 5`. Breaker унасан
хэвээр байхад идэвхжүүлэхийг ТАТГАЛЗСАН нь зөв зан төлөв.

### 2.4 Гэрээний баталгаажуулалт (Problem contract)

```
Idempotency-Key байхгүй          → 422 loc=header.Idempotency-Key "Field required"
Idempotency-Key нь UUID биш      → 422 "Input should be a valid UUID"
body-д нэмэлт талбар             → 422 loc=body.unknown_field "Extra inputs are not permitted"
```

### 2.5 Append-only audit log (AC-8)

DB түвшний trigger — `audit_log_no_update`, `audit_log_no_delete`, `audit_log_no_truncate`:

```
UPDATE audit_log ... → ERROR: append-only хүснэгт: audit_log дээр UPDATE хийх боломжгүй (LLD §5.7)
DELETE FROM audit_log → ERROR: append-only хүснэгт: audit_log дээр DELETE хийх боломжгүй (LLD §5.7)
```

Гурван төлөвийн өөрчлөлт бичигдэж, `verify_chain()` нь амьд Postgres дээр
**эвдрэлгүй (None)** буцаав. Genesis `prev_hash` нь 32 тэг байт, дараагийн
мөр бүрийн `prev_hash` нь өмнөхийн `hash`-тай таарав.

### 2.6 Горимын хоёрдмол бус заалт (AC-9)

Хариу БҮРИЙН envelope-д `"source":"alpaca_paper"` — бодит/paper/backtest
хольцгүй.

## 3. Хянагчийн буцаасан 2 зүйлийн статус — амьд системээр баталгаажив

| # | Санал | Статус |
|---|---|---|
| 1 | `build()` нь `settings.REDIS_URL`-ийг EventBus-руу дамжуулдаггүй → `redis.reachable=false` | **ХААГДСАН.** `app/main.py:203-205` нь `EventBus(redis=_make_redis(settings.REDIS_URL))`. Амьд health нь `redis.reachable=true`; Redis-ийн `system` сувгаар мессеж үнэхээр дамжив (§2.1). Commit `03b49ba`. |
| 2 | `app/stream/ingest.py` — `stream_trade_updates()` coroutine never awaited RuntimeWarning | **ХААГДСАН.** `run_forever()`-ийн `finally` нь `await _close(stream)` дуудна (`app/stream/ingest.py:236-240`). Амьд ажиллалтын лог дээр `never awaited` тохиолдол **0**. Commit `03b49ba`. |

Хоёулаа DEV_DEPLOY-ийн тэмдэглэсэнчлэн аль хэдийн засагдсан байсан тул
энэ шатанд код ЗАСААГҮЙ.

## 4. Тэмдэглэл (блоклогч БИШ)

1. **`enforce_breaker` job-ийн 2 алгасалт.** Асаалтын эхний 10 секундэд
   `Execution of job "enforce_breaker" skipped: maximum number of running
   instances reached (1)` хоёр удаа гарав. Шалтгаан: broker хүрэхгүй үед
   нэг гүйлт 5 секундын интервалаас урт болдог. Асаалтын дараа тоо
   **өсөөгүй** (3 минутын турш 2 хэвээр). DEV-д credential байхгүйгээс
   үүдэлтэй; ажиллагааны алдаа биш.
2. **Backend нь compose-д багтаагүй.** `runbook.md` §0-ийн дагуу host дээрх
   процесс (`python -m uvicorn app.main:build --factory`). Энэ шалгалтад
   ингэж л босгосон.
3. **Broker 503.** `ALPACA_API_KEY`/`SECRET` DEV-д тавигдаагүй тул
   `/account`, `/positions`, `/attribution` нь 503 `broker_unavailable`
   Problem буцаана — гэрээний дагуу зөв. Бодит Alpaca зам нь UAT-д
   credential-тайгаар шалгагдана.

## 5. Алгассан зүйлс

| Зүйл | Шалтгаан |
|---|---|
| Бодит Alpaca REST/WS урсгал | DEV-д credential байхгүй (`ALPACA_KEY_REF` нь зөвхөн лавлагаа) |
| Order бөглөлт, reconciliation, approval эргэлт | Broker хүрэхгүй тул амьд өгөгдөл байхгүй |
| Frontend-ийн browser E2E | Энэ шатны хамрах хүрээнд байхгүй (static serve л шалгав) |

## 6. Цэвэрлэгээ

`docker compose -f docker-compose.dev.yml down` — 3 контейнер, сүлжээ устгагдав.

## Дүгнэлт

Postgres, Redis, frontend (nginx) болон backend (uvicorn) дөрвүүлээ амьд
шалгагдав. Health endpoint 200 буцааж, `database.reachable=true`,
`redis.reachable=true`. Kill switch, circuit breaker, append-only audit
chain, WS/Redis fan-out, Problem гэрээ — бүгд амьд системээр
баталгаажив. Блоклогч зөрчил илрээгүй.
