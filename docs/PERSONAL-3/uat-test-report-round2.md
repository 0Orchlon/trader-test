<!-- PERSONAL-3 · UAT тестийн тайлан (2-р ажиллалт) · UAT_TEST · 2026-09-18 -->

# PERSONAL-3 — UAT тестийн тайлан (2-р ажиллалт)

- **Орчин:** UAT, compose project `personal3-uat` (`docker-compose.dev.yml`) —
  Postgres 16 `localhost:25432`, Redis 7 `localhost:26379`, nginx `localhost:18080`
- **Commit:** `d790a91` (`issue/personal-3`) — UAT_DEPLOY 2-р ажиллалтын байршуулсан хувилбар
- **Үүрэг:** зөвхөн ШАЛГАЖ тайлагнах — **энэ ажиллалтад кодын засвар хийгээгүй**
- **Броker:** Alpaca paper түлхүүр **энэ ажиллалтад олгогдоогүй**
  (`alpaca` MCP server `CONNECT_TIMEOUT`, `ALPACA_API_KEY`/`SECRET` орчны
  хувьсагчид алга). `paper-api.alpaca.markets` сүлжээгээр хүрэх боловч
  баталгаажуулалтгүй (`401`) — §6-г үз.
- **Харьцуулах суурь:** `uat-test-report.md` (өмнөх ажиллалт, commit `66c528c`)

---

## 1. Нэгдсэн дүн

| Ангилал | Тоо |
|---|---|
| Амьд системийн шалгуур (round6 harness) | **17 тэнцэв / 0 унав** |
| Гараар нэмэлт шалгасан зүйл | 12 |
| Автомат тест | backend `pytest` **383 passed / 0 failed**, frontend `npm test` **66 passed** |
| API гэрээний нийцэл | **21/21 зам таарав** |
| Хаагдсан өмнөх зөрчил | **U-1 (блоклогч), U-3**, хянагчийн 2 санал |
| **Блоклогч зөрчил (шинэ/давтагдсан)** | **U-2 (давтагдав), U-4 (шинэ)** |
| Шалгалт хийгдээгүй хамрах хүрээ | broker-ээс хамаарах арилжааны гол зам (§6) |

**Дүгнэлт: UAT ТЭНЦЭЭГҮЙ.**

Програм хангамжийн тал бүрэн ногоон: өмнөх тойргийн блоклогч **U-1 арилсан**,
**U-3 арилсан**, хянагчийн 2 санал амьд системээр дахин баталгаажив, шалгасан
17 шалгуур бүгд тэнцэв, автомат тестүүд ногоон. Гэвч **UAT-д байршуулсан
зүйл операторт ашиглах боломжгүй хэвээр**: (U-2) байршуулсан frontend
контейнер энэ алхам эхлэхэд бүх хүсэлтэд `500` буцааж байсан, (U-4) UAT-д
backend огт байршуулаагүй бөгөөд nginx-ийн `BACKEND` анхдагч нь ГАДНЫ,
төсөлтэй холбоогүй процесс руу зааж байна. Хоёулаа DEPLOY талын зөрчил.

---

## 2. Өмнөх тойргийн зөрчлүүд — одоогийн байдал

| ID | Өмнөх тайлбар | Одоо | Нотолгоо |
|---|---|---|---|
| **U-1** (блоклогч) | байршуулсан UI нь backend-д хүрэхгүй (`/api/*` 404, deep link 404) | **ЗАСАГДСАН** | `ci/nginx.conf` байршуулагдсан: `/`, `/approvals`, `/settings`, `/activity`, `/providers`, `/tuning` → бүгд `200`; `GET :18080/api/v1/health` → `200` ба backend-ийн шууд хариутай ижил `system_state`; `ws://:18080/ws` upgrade амжилттай, эхний фрэйм `state_changed` |
| **U-2** | байршуулсан frontend нь УСТСАН ажлын хавтас руу mount хийгдсэн | **ЗАСАГДААГҮЙ — 3 дахь удаа давтагдав** | §4.1 |
| **U-3** | provider hot-swap зөвхөн тухайн process-д үйлчилнэ | **ЗАСАГДСАН** | `:28000`-д `xai-fc` болгосны дараа `:28001` мөн `xai-fc`; `:28001`-ийг БҮРЭН дахин асаасны дараа ч `xai-fc` (өмнө нь үргэлж `claude-mcp`-ээс эхэлдэг байсан) |
| Хянагчийн санал (1) | `build()` нь `settings.REDIS_URL`-ийг EventBus-руу дамжуулдаггүй | **ЗАСАГДСАН, UAT-д дахин батлав** | `GET /api/v1/health` → `"redis": {"reachable": true, "detail": null}`; instance хоорондын Redis fan-out бодитоор ажиллав (§3.3) |
| Хянагчийн санал (2) | `stream_trade_updates()` — coroutine never awaited RuntimeWarning | **ЗАСАГДСАН, UAT-д дахин батлав** | `:28000` нь `-X dev -W always` дор 20+ мин ажиллаж, broker унасан дахин холболтын зам 25 удаа гүйсэн (`ws_disconnects=25`) атлаа логт `RuntimeWarning`/`never awaited` **0 удаа** (логт зөвхөн `websockets`-ийн 3 `DeprecationWarning`) |
| N-1 … N-4 | өмнөх тойрогт хаагдсан | хэвээр хаалттай | `pytest` 383 passed, `Problem` гэрээ §3.5 |

---

## 3. Шалгагдсан зүйлс

Бүх шалгуурын скрипт: `docs/PERSONAL-3/uat/uat_round6.py` (давтан ажиллуулах
заавар §7).

### 3.1 Дэд бүтэц

| Шалгалт | Үр дүн |
|---|---|
| `personal3-uat-postgres-1` | up (healthy) `:25432`; `python -m app.migrate` → exit 0, **11 хүснэгт** |
| `personal3-uat-redis-1` | up (healthy) `:26379` |
| `personal3-uat-frontend-1` | up `:18080` — **эхэндээ бүх зам `500`** (U-2), дахин угсарсны дараа `200` |
| `GET /api/v1/health` | `status=degraded`, `database.reachable=true`, `redis.reachable=true`, `broker.reachable=false` (түлхүүргүй), 4 provider healthy |

### 3.2 Байршуулсан nginx — U-1 (байршуулалтын гадаргуу)

```
GET :18080/            200      GET :18080/providers   200
GET :18080/approvals   200      GET :18080/tuning      200
GET :18080/settings    200      GET :18080/activity    200
GET :18080/api/v1/health 200   (backend-ийн шууд хариутай ижил system_state)
GET :18080/assets/index-BbK0HJ_A.js 200
ws://:18080/ws?channels=system → upgrade OK, эхний event = state_changed
```

Тэмдэглэл: энэ шалгалтыг хийхийн тулд `BACKEND`-ийг өөрөө ажиллуулсан backend
(`:28000`) руу зааж контейнерийг дахин үүсгэх шаардлага гарсан — байршуулсан
анхдагч утга нь ажиллахгүй (U-4).

### 3.3 Олон instance + Redis (AC-14)

`:28000`-д provider сольж, `:28001`-ийн `/ws?channels=system`-ийг сонсов:

```
POST :28000/api/v1/providers/research/switch {"provider_id":"openai-fc"} -> 200
WS@:28001 {"channel":"system","payload":{"seq":8,"event":"provider_switched",
           "role":"research","previous_provider_id":"claude-mcp",
           "new_provider_id":"openai-fc","in_flight_calls":0}}
```

Мөн `:28000`-д хийсэн `kill-switch` нь `:28001`-ийн WS клиентэд `state_changed`
болж хүрэв. Энэ нь хянагчийн 1-р саналын (`REDIS_URL` дамжуулагдахгүй)
бодит үр дагаврыг хаасныг батална.

### 3.4 Төлөвийн машин ба хамгаалалт

| AC | Шалгалт | Үр дүн |
|---|---|---|
| AC-36 | `POST /kill-switch` | `200 state=halted`; давтан дуудахад мөн `200` (идемпотент) |
| AC-33 | `halted` үед гарын order (`:28000`) | `409 system_halted` — broker руу 0 дуудалт |
| AC-33 | `halted` үед гарын order (`:28001`) | `409 system_halted` — халалт нь instance-д биш СИСТЕМД хамаарна |
| AC-15 | broker унасан үед `POST /system/activate` | `409 breaker_still_tripped`, `tripped=[api_error_rate=1.0000 > 0.05, ws_disconnects=25 > 5]` — эрүүл бус үед систем өөрөө асахыг зөвшөөрөхгүй |
| AC-37 | төлөв DB-д тогтвортой | `:28001`-ийг дахин асаасны дараа `halted` төлөв DB-ээс уншигдав |

### 3.5 Гэрээ, аудит, сэргээлт

| AC | Шалгалт | Үр дүн |
|---|---|---|
| — | амьд API vs `contracts/openapi.yaml` | **21/21 зам+метод таарав**, зөрүү 0 (server prefix `/api/v1` нормчилсон) |
| AC-20/21 | 200 хариу бүрд `source`/`as_of`/`stale`/`system_state` | 7/7 (200 буцаасан бүгд), `source=alpaca_paper` |
| AC-9/AC-25 | broker хүрэхгүй үед өгөгдөл ЗОХИОХГҮЙ | `/account`, `/positions`, `/attribution` → `503 broker_unavailable` (`Problem`), хуучин/зохиомол утга буцаагаагүй |
| N-2 | дутуу биетэй `POST /orders/manual` | `422` + `type/title/status/code/detail/errors` |
| AC-17 | `python -m app.audit.verifier` | `chain бүрэн бүтэн`, exit 0 |
| AC-8 | `audit_log` дээр `UPDATE`/`DELETE`/`TRUNCATE` | 3/3 татгалзав: `append-only хүснэгт: audit_log дээр … боломжгүй (LLD §5.7)` |
| AC-18 | `python -m app.audit.replay` | төлөвийн 4 шилжилт, provider-ийн 4 солилт ЗӨВХӨН логоос сэргээгдэв, `unknown_events: []` |
| AC-10 | `POST /providers/{role}/switch` | `200`, restart шаардахгүй, бүх instance-д хүрнэ (§3.3) |
| AC-19 | лог ба DB дотор түлхүүр хэлбэрийн мөр | backend 3 логт 0 тохиолдол; `audit_log.payload` дээр `apca|api_key|secret|bearer` → 0 мөр |
| AC-22 | whitelist/bounds засах endpoint | 21 замын дунд mutator **алга** |
| AC-24 | token-гүй `POST /tuning/promote` | `409 confirmation_required` |

### 3.6 Автомат тест (байршуулсан эх кодоос)

| Багц | Үр дүн |
|---|---|
| backend `pytest -q` (`.venv-uat`, `requirements.lock`, Python 3.12.13) | **383 passed, 1 warning, 0 failed** (102.5s) |
| frontend `npm test -- --run` (`check:api` + `lint` + `typecheck` + `vitest`) | **6 файл / 66 тест passed** (57.2s) |

Дахин угсарсан bundle-ийн нэр `index-BbK0HJ_A.js` нь DEV_TEST болон өмнөх UAT
тайланд бичигдсэнтэй **яг ижил** — давтагдах build-ийн нэмэлт нотолгоо.

---

## 4. Илэрсэн зөрчил

### 4.1 U-2 (БЛОКЛОГЧ, давтагдсан) — байршуулсан frontend устсан хавтаснаас mount хийгдсэн

Энэ алхам эхлэх үеийн БОДИТ байдал (өөрчлөхөөс өмнө):

```
docker inspect personal3-uat-frontend-1
  C:\...\Temp\task-300\repo\frontend\dist -> /usr/share/nginx/html
  C:\...\Temp\task-300\repo\ci\nginx.conf -> /etc/nginx/templates/default.conf.template

GET http://localhost:18080/           -> 500
GET http://localhost:18080/approvals  -> 500
```

`task-300` нь өмнөх алхмын ажлын хавтас — даалгавар дуусмагц устдаг.
Тиймээс байршуулалт нь дараагийн алхам эхлэхэд өөрөө унана. Ижил зөрчлийг
DEV_TEST болон өмнөх UAT_TEST тайланд аль хэдийн бүртгэсэн, `runbook.md §0`-д
дүрэм болгон бичсэн ч UAT_DEPLOY 2-р ажиллалт үүнийг дахин давтав.

Үр дагавар: UAT-д «байршуулсан» гэж бүртгэгдсэн UI нь дараагийн алхмын
хувьд ажиллахгүй — оператор нээвэл `500`.

Шалгалтыг үргэлжлүүлэхийн тулд `npm ci && npm run build` хийж контейнерийг
энэ хавтаснаас дахин үүсгэв (**код заваагүй**, зөвхөн байршуулалтыг сэргээв).

### 4.2 U-4 (БЛОКЛОГЧ, шинэ) — UAT-д backend байршуулаагүй; proxy нь ГАДНЫ процесс руу заасан

`docker-compose.dev.yml` нь `BACKEND: ${BACKEND:-host.docker.internal:8000}`
гэсэн анхдагчтай бөгөөд UAT_DEPLOY нь backend service-ийг **огт байршуулаагүй**.
Host-ийн `:8000` дээр төсөлтэй огт холбоогүй өөр процесс сонсож байна:

```
GET http://127.0.0.1:8000/api/v1/health
  HTTP/1.0 404 File not found
  Server: SimpleHTTP/0.6 Python/3.14.6
```

Тиймээс байршуулсан хэвээрээ нь UI-аас ирэх `/api/v1/*` бүр ГАДНЫ static
файл серверт очиж `404` авна — чимээгүй бөгөөд оношлоход төөрөгдүүлэм.

**UAT_DEPLOY-ийн алгасах үндэслэл энэ орчинд БАТЛАГДСАНГҮЙ.** Тайланд
«локал Python 3.14.6 бөгөөд `>=3.12,<3.13` шаарддаг, `pip cache` дутуу» гэж
бичсэн. Энэ шалгалтын явцад ЯГ ЭНЭ machine дээр дараах нь нэг оролдлогоор
амжилттай болов:

```
uv venv --python 3.12 .venv-uat          # CPython 3.12.13 (uv-аар суусан, аль хэдийн байсан)
uv pip install -r requirements.lock      # 58 pin бүгд суув
python -m app.migrate                    # exit 0, 11 хүснэгт
python -m uvicorn app.main:build --factory --port 28000   # up
python -m uvicorn app.main:build --factory --port 28001   # up
```

Өөрөөр хэлбэл backend-ийг энэ орчинд суулгаж ажиллуулах боломжтой — `uv` нь
`PATH` дээр байгаа, Python 3.12.13 нь суусан, `files.pythonhosted.org` хүрнэ.
Backend-ийг байршуулахгүй байх орчны саад одоогийн байдлаар байхгүй.

Үр дагавар: операторын хувьд UAT-д ажиллаж байгаа бүтээгдэхүүн ГЭЖ БАЙХГҮЙ —
зөвхөн static UI + хоосон proxy. UI шаарддаг AC-3, AC-4, AC-6, AC-7, AC-9,
AC-11, AC-13 нь байршуулсан хэлбэрээрээ шалгагдах боломжгүй.

---

## 5. Ажиглалт (зөрчил биш)

- **O-1 — broker унасан үед `enforce_breaker` job давхцаж алгасагдана.**
  `:28000`-ийн логт `Execution of job "enforce_breaker" … skipped: maximum
  number of running instances reached (1)` **101 удаа**. Шалтгаан: job нь 5
  секундын интервалтай (`scheduler.py:99`) атлаа доторх broker дуудлага
  хүрэхгүй үед интервалаас удаан үргэлжилдэг; APScheduler-ийн анхдагч
  `max_instances=1` тул дараагийнх нь алгасагдана. Одоогийн зан төлөв нь
  АЮУЛГҮЙ (breaker аль хэдийн унасан, систем `halted`, автоматаар сэргэхгүй)
  боловч breaker-ийн үнэлгээний давтамж нь яг broker эвдэрсэн үед муудна.
  Шийдвэр DEVELOPMENT-д: broker дуудлагад timeout өгөх эсвэл job-д
  `max_instances`/`misfire_grace_time`-ыг ил заах.
- **O-2 — `nginx.conf`-ийн `location /health` нь backend дээр байхгүй зам.**
  Backend нь `/api/v1/health`-ийг л үзүүлдэг (`GET :28000/health` → `404`).
  Proxy дүрэм өөрөө зөв ажиллаж байгаа тул зөрчил биш, гэхдээ энэ location
  нь юу ч үйлчлэхгүй.
- **O-3 — WS `seq` нь process тус бүрдээ** (өмнөх тайлангийн ажиглалт хэвээр):
  энэ ажиллалтад `:28001` дахин асаасны дараа `seq` 8-аас эхлэв.
- **O-4 — агент дуудах endpoint байхгүй** (өмнөх тайлангийн ажиглалт хэвээр):
  `GET /agent-decisions` хоосон, 21 замын дунд шинжилгээ эхлүүлэх зам алга.
  AC-4/AC-6 нь зөвхөн автомат тестээр шалгагдана.

---

## 6. Шалгалт ХИЙГДЭЭГҮЙ хамрах хүрээ (ил тодорхойлолт)

Alpaca paper түлхүүр энэ ажиллалтад олгогдоогүй (`alpaca` MCP server
`CONNECT_TIMEOUT`; `ALPACA_API_KEY`/`ALPACA_API_SECRET` орчинд алга; репод
хадгалагддаггүй). Тиймээс **broker-ээс хамаарах дараах зүйлс энэ тойрогт
дахин шалгагдаагүй**:

- AC-31 (хязгаар доторх order Risk→Execution→Alpaca), idempotency
- AC-5 (хязгаараас дээш order → `ESCALATE_TO_HUMAN` → approval)
- AC-34/AC-35 (wind-down үеийн exposure нэмэх/багасгах)
- AC-30 (бодит позицтой attribution), AC-1 (equity/позицийн тэнцэл)
- AC-16 (halt нь позицийг автоматаар хаахгүй), EOD reconciliation

Эдгээр нь **өмнөх UAT ажиллалтад (`uat-test-report.md`, commit `66c528c`)
бодит paper данс дээр тэнцсэн**. Тэрнээс хойшхи backend-ийн цорын ганц
кодын өөрчлөлт нь `b6d29af`-ийн ProviderRouter (adopt/follow/restore) бөгөөд
order-ийн замд хамаарахгүй; тэр замуудыг 383 автомат тест хамардаг. Гэвч
энэ нь амьд шалгалтыг ОРЛОХГҮЙ — дээрх жагсаалт нь энэ тойргийн хамрах
хүрээний бодит цоорхой хэвээр.

---

## 7. Давтан гүйцэтгэх заавар

```bash
# 1. дэд бүтэц
docker compose -p personal3-uat -f docker-compose.dev.yml up -d
# 2. frontend static + proxy (BACKEND нь backend ХААНА байгааг заана)
cd frontend && npm ci --prefer-offline && npm run build
BACKEND=host.docker.internal:28000 \
  docker compose -p personal3-uat -f docker-compose.dev.yml up -d --force-recreate frontend
# 3. backend (Python 3.12 + requirements.lock). backend/.env дотор:
#    DATABASE_URL=postgresql+asyncpg://p3:p3@localhost:25432/p3
#    REDIS_URL=redis://localhost:26379/0
cd backend && uv venv --python 3.12 .venv-uat && uv pip install -r requirements.lock
./.venv-uat/Scripts/python -m app.migrate
./.venv-uat/Scripts/python -X dev -W always -m uvicorn app.main:build --factory --port 28000
./.venv-uat/Scripts/python -m uvicorn app.main:build --factory --port 28001
# 4. шалгуур
./.venv-uat/Scripts/python ../docs/PERSONAL-3/uat/uat_round6.py
# 5. broker-ээс хамаарах гол зам (түлхүүр байгаа үед)
ALPACA_API_KEY=... ALPACA_API_SECRET=... python ../docs/PERSONAL-3/uat/uat_round5.py
```

Alpaca paper түлхүүр нь орчноос ирнэ — репод ХЭЗЭЭ Ч хадгалагдахгүй
(`backend/.env` нь `.gitignore`-д).

---

## 8. DEPLOY / DEVELOPMENT руу буцаах жагсаалт

1. **U-4 (DEPLOY, блоклогч)** — UAT-д backend-ийг бодитоор байршуулах
   (Python 3.12 + `requirements.lock`), `BACKEND`-ийг тэр рүү заах. Энэ
   орчинд боломжтой болохыг §4.2-т нотолсон. Хэрэв эцсийн шийдэл нь
   контейнер (Harbor image) бол энэ репод Dockerfile/CI одоо ч байхгүй тул
   тэр цоорхойг ил тодорхойлох шаардлагатай.
2. **U-2 (DEPLOY, блоклогч)** — түр зуурын ажлын хавтсаас bind mount хийхээ
   болих (static-аа image дотор шатаах эсвэл нэрлэсэн volume). `runbook.md §0`
   дүрэм байгаа тул шинэ шийдвэр биш, ЗӨВХӨН хэрэгжүүлэлт дутуу.
3. **O-1 (DEVELOPMENT, блоклогч биш)** — broker унасан үед `enforce_breaker`
   давхцаж алгасагдахыг timeout эсвэл ил `max_instances`-аар шийдэх.
4. **Хамрах хүрээ (пайплайн)** — UAT_TEST алхамд Alpaca paper түлхүүр
   тогтмол хүрдэг болгох; түлхүүргүйгээр арилжааны гол зам шалгагдахгүй (§6).
