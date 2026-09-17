<!-- PERSONAL-3 · DEV тестийн тайлан (2-р ажиллалт) · DEV_TEST · 2026-09-18 -->

# DEV_TEST (2-р ажиллалт) — хянагчийн 2 саналын дараах дахин шалгалт

- **Орчин:** DEV, `docker-compose.dev.yml` (compose project `repo`)
- **Commit:** `43ccd63` (`issue/personal-3`) — 1-р ажиллалт `731cb74` дээр хийгдсэн
- **Огноо:** 2026-09-18
- **Шалтгаан:** хянагч 2 зүйлийг «DEVELOPMENT-д засаад дахин DEV_TEST хий» гэж буцаасан
- **Үүрэг:** шалгаж тайлагнах. Энэ ажиллалтад **код заваагүй** — доор тайлбарласнаар
  хоёр зүйл нь HEAD дээр аль хэдийн засагдсан байсныг амьд системээр баталгаажуулав.

## 0. Хянагчийн 2 саналын статус — амьд системээр

| # | Санал | Статус |
|---|---|---|
| 1 | `build()` нь `settings.REDIS_URL`-ийг EventBus-руу дамжуулдаггүй → `health.redis.reachable=false`, олон instance үед AC-14 зөрчигдөх эрсдэл | **ХААГДСАН.** Засвар `03b49ba` (`app/main.py:214-219` → `EventBus(redis=_make_redis(settings.REDIS_URL))`) нь HEAD-д байгаа. Амьд health: `"redis":{"name":"redis","reachable":true,"detail":null}`. **Хоёр чиглэл** шалгагдав (§2.1): (а) app-аас Redis рүү нийтлэгдэв, (б) ГАДНЫ нийтлэлт (өөр instance дуурайсан) WS клиент рүү хүрэв. |
| 2 | `app/stream/ingest.py` — broker байхгүй үед `stream_trade_updates()` coroutine never awaited RuntimeWarning, нөөц алдалт | **ХААГДСАН.** Засвар `03b49ba` (`run_forever()`-ийн `finally: await _close(stream)`, `app/stream/ingest.py:236-240`). Шалгалт: uvicorn-ыг `-W always`-ээр (бүх warning ил) 5 минут ажиллуулав; DEV-д credential байхгүй тул broker үнэхээр хүрэхгүй, `ws_disconnects` тоолуур 9 хүртэл өссөн — өөрөөр хэлбэл асуудалтай зам ҮНЭХЭЭР гүйсэн. Логт `never awaited` **0 удаа**, `RuntimeWarning` **0 удаа**, traceback **0**. |

Аль аль нь `03b49ba`-д, буюу 1-р DEV_TEST-ээс (`210deb6`) ӨМНӨ засагдсан байсан тул
энэ ажиллалтад нэмэлт засвар шаардлагагүй байв. Заваагүй гэдгээ ил тэмдэглэв
(шалгах үүрэгтэй ажилд код засах нь хяналтыг устгана).

## 1. Байршуулалтыг сэргээх

Өмнөх даалгаврын UAT stack (`personal3-uat-{postgres,redis,frontend}-1`) ажиллаж
байсан ба яг ижил портуудыг (25432 / 26379 / 18080) эзэлж байв. Түүний ажлын хавтас
устсан тул шинэчлэх боломжгүй — устгаж, DEV stack-ыг энэ хавтаснаас босгов
(`docker compose -f docker-compose.dev.yml up -d`). Backend нь compose-д багтаагүй
(runbook §0) тул host дээр `uvicorn app.main:build --factory --port 28000`,
`.env` нь `.env.example`-ээс DB/Redis порт солигдсон хувилбар.

## 2. Шалгагдсан зүйлс

### 2.0 Дэд бүтэц

| Шалгалт | Үр дүн |
|---|---|
| `pg_isready -U p3 -d p3` (25432) | `accepting connections` |
| `redis-cli ping` (26379) | `PONG` |
| `python -m app.migrate` | exit 0 |
| Үүссэн хүснэгт | 11 (`accounts` … `tuning_history`) |
| `npm ci` + `npm run build` | exit 0, `dist/assets/index-BbK0HJ_A.js` 1 035 255B |

### 2.1 WS fan-out + Redis (AC-2, AC-14) — ХОЁР ЧИГЛЭЛ

1. `ws://127.0.0.1:28000/ws` холбогдмогц хормын хувилбар: `seq:1`, `state:halted`, `reason:initial_deploy`.
2. `POST /api/v1/kill-switch` → 200; тэр даруй WS-ээр `seq:2`, `reason:"DEV_TEST дахин шалгалт"`.
3. Тэр ижил мессеж Redis-ийн `system` суваг дээр `psubscribe`-аар баригдав (`_src` нь өөрийн instance-ийн id).
4. **Fan-in:** гадны клиентээс Redis `system` суваг руу өөр `_src`-тэй мессеж нийтлэхэд WS клиент рүү хүрэв —
   `{"channel":"system","payload":{"seq":999,…,"reason":"DEV_TEST өөр instance-ийн fan-in"}}`.
   Энэ нь хянагчийн эргэлзсэн «олон instance үед бүх клиентэд хүрэх» замыг шууд баталгаажуулна.

### 2.2 Kill switch хүчинтэй (AC-7)

`halted` үед `POST /api/v1/orders/manual` (зөв `Idempotency-Key`, зөв схем) →
**409 `system_halted`** — «Систем зогссон — шинэ order илгээхгүй.» Order илгээгдээгүй.

### 2.3 Circuit breaker (AC-7 автомат зогсолт)

`POST /api/v1/system/activate` → **409 `breaker_still_tripped`**;
`api_error_rate=1.0000 > 0.05`, `ws_disconnects=9 > 5`. Унасан breaker дээр идэвхжүүлэхийг татгалзав.

### 2.4 Problem гэрээ

| Оролт | Хариу |
|---|---|
| `Idempotency-Key` байхгүй | 422 `invalid_request` |
| `Idempotency-Key` нь UUID биш | 422 |
| Схемийн бус талбар (`unknown_field`) | 422, `loc=body.unknown_field` |
| Талбарын нэр буруу (`type` vs `order_type`) | 422, `loc=body.order_type` «Field required» |
| `/account`, `/positions`, `/attribution` | 503 `broker_unavailable` (DEV-д credential байхгүй) |

### 2.5 Append-only audit log (AC-8)

```
UPDATE audit_log … → ERROR: append-only хүснэгт: audit_log дээр UPDATE хийх боломжгүй (LLD §5.7)
DELETE FROM audit_log → ERROR: append-only хүснэгт: audit_log дээр DELETE хийх боломжгүй (LLD §5.7)
```

`verify_chain()` амьд Postgres дээр **None** (эвдрэлгүй) буцаав.

### 2.6 Provider hot-swap (AC-10)

`GET /providers` → `active.research=claude-mcp` → `POST /providers/research/switch {openai-fc}` → 200 →
`GET /providers` → `active.research=openai-fc` → буцаан `claude-mcp` болгов. Restart шаардаагүй, алдаа гараагүй.

### 2.7 Frontend + reverse proxy (UAT U-1-ийн засварыг DEV-д)

`BACKEND=host.docker.internal:28000` өгсөн nginx (`ci/nginx.conf`):

| Зам | Код |
|---|---|
| `GET /` | 200, 420B, `text/html`, `lang="mn"` |
| `GET /dashboard` (deep link) | 200, `index.html` руу унав |
| `GET /assets/index-BbK0HJ_A.js` | 200, 1 035 255B |
| `GET /api/v1/health` (proxy) | 200, backend-ийн JSON |

### 2.8 Health

```json
{"source":"alpaca_paper","system_state":"halted","status":"degraded",
 "broker":{"name":"alpaca_paper","reachable":false,"detail":"BrokerUnavailable"},
 "database":{"name":"postgres","reachable":true},
 "redis":{"name":"redis","reachable":true,"detail":null},
 "providers":[claude-mcp, openai-fc, xai-fc, local-fallback — бүгд healthy]}
```

## 3. Тэмдэглэл (блоклогч БИШ)

1. **`enforce_breaker` job тогтмол алгасдаг — 1-р тайланг залруулав.** 1-р тайлан
   «асаалтын дараа тоо өсөөгүй (2 хэвээр)» гэсэн нь буруу байжээ. Энэ ажиллалтад
   хэмжихэд: 60 секундэд **3 алгасалт** (23 → 26). Интервал 5s тул минутад ~12
   гүйлтээс ~9 нь амжиж байна. Шалтгаан: broker хүрэхгүй үед `CircuitBreaker.enforce()`
   нэг гүйлт 5 секундээс удаан болдог. Breaker метрик шинэчлэгдсээр байгаа
   (`api_error_rate=1.0` амьдаар уншигдав) тул ажиллагааны алдаа биш, харин
   credential-гүй DEV-ийн үр дагавар. UAT-д credential-тайгаар дахин ажиглах нь зүйтэй.
2. **`GET /health` (proxy-гоор) 404.** nginx нь `/health`-ыг backend руу зөв дамжуулдаг ч
   backend дээр `/health` route байхгүй (зөвхөн `/api/v1/health`). Proxy зөв, зам байхгүй.
3. **Backend нь compose-д багтаагүй** — runbook §0-ийн дагуу host дээрх процесс.
4. **UAT stack-ыг устгав** (§1) — өмнөх даалгаврын үлдэгдэл, порт мөргөлдөж байсан.

## 4. Алгассан зүйлс

| Зүйл | Шалтгаан |
|---|---|
| Бодит Alpaca REST/WS урсгал, order бөглөлт, reconciliation | DEV-д `ALPACA_API_KEY`/`SECRET` байхгүй — broker 503. Энэ зам UAT-д шалгагдсан (`uat-test-report.md`) |
| Backend-ийн контейнер image | DEV_DEPLOY нь «python offline cache дутуу» гэж алгассан; энэ шатанд host дээрх процессоор шалгав (блоклогч биш) |
| Frontend-ийн browser E2E | Энэ шатны хамрах хүрээнд байхгүй — static + proxy л шалгав |

## 5. Цэвэрлэгээ

`docker compose -f docker-compose.dev.yml down` — 3 контейнер, `repo_default` сүлжээ
устгагдав. `docker ps` хоосон. Host дээрх uvicorn процесс мөн зогсоов.

## Дүгнэлт

Хянагчийн 2 зүйл хоёулаа амьд системээр хаагдсан: `redis.reachable=true` ба Redis-ийн
хоёр чиглэлийн fan-out/fan-in ажиллав; `never awaited` warning 0 (асуудалтай зам
үнэхээр гүйсэн нөхцөлд). Үүнээс гадна Postgres, Redis, frontend+proxy, backend
дөрвүүлээ, мөн kill switch, breaker, audit chain, Problem гэрээ, provider hot-swap
амьдаар шалгагдав. **Блоклогч зөрчил илрээгүй.**
