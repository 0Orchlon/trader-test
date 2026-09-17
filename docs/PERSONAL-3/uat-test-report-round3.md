<!-- PERSONAL-3 · UAT тестийн тайлан (3-р ажиллалт) · UAT_TEST · 2026-09-18 -->

# PERSONAL-3 — UAT тестийн тайлан (3-р ажиллалт)

- **Орчин:** UAT, compose project `personal3-uat` (`docker-compose.dev.yml`) —
  Postgres 16 `:25432`, Redis 7 `:26379`, **backend контейнер** `:28000`,
  nginx `:18080`
- **Commit:** `f997545` (`issue/personal-3`) — UAT_DEPLOY 3-р ажиллалтын
  байршуулсан хувилбар
- **Үүрэг:** зөвхөн ШАЛГАЖ тайлагнах — **энэ ажиллалтад кодын засвар хийгээгүй**
- **Харьцуулах суурь:** `uat-test-report-round2.md` (commit `d790a91`,
  блоклогч U-2 ба U-4-тэй унасан)

---

## 1. Нэгдсэн дүн

| Ангилал | Тоо |
|---|---|
| Амьд системийн шалгуур (`uat/uat_round6.py`, БАЙРШУУЛСАН контейнер дээр) | **17 тэнцэв / 0 унав** |
| Гараар нэмэлт шалгасан зүйл | 14 |
| Автомат тест | backend `pytest` **388 passed / 0 failed**, frontend `npm test` **66 passed** |
| API гэрээний нийцэл | **21/21 зам+метод таарав** |
| Хаагдсан өмнөх зөрчил | **U-2 (блоклогч), U-4 (блоклогч), O-1, O-2** |
| Шинэ блоклогч зөрчил | **0** |
| Шалгалт хийгдээгүй хамрах хүрээ | broker-ээс хамаарах арилжааны гол зам (§6) |

**Дүгнэлт: UAT ТЭНЦЭВ.**

Өмнөх хоёр тойргийг унагаж байсан байршуулалтын хоёр блоклогч (U-2 —
түр зуурын ажлын хавтаснаас bind mount, U-4 — backend огт байршуулаагүй)
`f997545`-д бодитоор хаагдсан: контейнеруудад **bind mount огт алга**
(статик нь image дотор), backend нь compose-ийн service болж ажиллаж байна,
nginx-ийн `BACKEND` анхдагч нь тэр service (`backend:8000`) руу заана.
Байршуулсан хэвээрээ нь операторт ашиглах боломжтой.

---

## 2. Өмнөх тойргийн зөрчлүүд — одоогийн байдал

| ID | Өмнөх тайлбар | Одоо | Нотолгоо |
|---|---|---|---|
| **U-2** (блоклогч, 3 удаа давтагдсан) | байршуулсан frontend нь устсан ажлын хавтас руу mount хийгдсэн | **ЗАСАГДСАН** | `docker inspect personal3-uat-frontend-1` → `Mounts` **хоосон**; `docker inspect personal3-uat-backend-1` → мөн хоосон. Статик нь image дотор (`/usr/share/nginx/html/assets` = `index-BbK0HJ_A.js`, `index-DVbWxlh7.css`) |
| **U-4** (блоклогч) | UAT-д backend байршуулаагүй, proxy нь ГАДНЫ процесс руу заасан | **ЗАСАГДСАН** | `personal3-uat-backend-1` (image `personal3-uat-backend`, Python 3.12.14) ажиллаж байна; frontend контейнерын `BACKEND=backend:8000` (host руу заахаа больсон); `GET :18080/api/v1/health` нь backend-ийн шууд хариутай ижил `system_state` |
| **O-1** | broker унасан үед `enforce_breaker` давхцаж алгасагдана (round2-т 101 удаа) | **ЗАСАГДСАН** | `breaker.BROKER_PROBE_TIMEOUT=2.0` + `scheduler`-ийн ил `max_instances`/`coalesce` (`6cde1aa`); байршуулсан backend-ийн логт `maximum number of running instances` **0 удаа** |
| **O-2** | `nginx.conf → location /health` нь backend дээр байхгүй зам | **ЗАСАГДСАН** | `GET :18080/health` → `200`, backend-ийн health JSON-ыг буцаана |
| Хянагчийн санал (1) — `REDIS_URL` EventBus-т дамждаггүй | | **ЗАСАГДСАН, UAT-д дахин батлав** | `/api/v1/health` → `"redis":{"reachable":true,"detail":null}`; instance хоорондын Redis fan-out бодитоор ажиллав (§3.3) |
| Хянагчийн санал (2) — `stream_trade_updates()` coroutine never awaited | | **ЗАСАГДСАН, UAT-д дахин батлав** | Байршуулсан 2 backend контейнерын логт `RuntimeWarning`/`never awaited`/`Traceback` **0 удаа** |
| U-1, U-3, N-1…N-4 | өмнөх тойрогт хаагдсан | хэвээр хаалттай | §3.2, §3.3, §3.5 |

---

## 3. Шалгагдсан зүйлс

Гол скрипт: `docs/PERSONAL-3/uat/uat_round6.py` — **өөрчлөгдөөгүй**, энэ удаа
БАЙРШУУЛСАН контейнер дотроос ажиллав (§7). AC-14 нь хоёр instance
шаарддаг тул шалгалтын хугацаанд ижил image-ээс хоёр дахь backend
(`personal3-uat-backend-2`, host порт нээгээгүй) түр ажиллуулав — энэ нь
**шалгалтын тоноглол**, байршуулалтын бүрэлдэхүүн биш, төгсгөлд устгав.

### 3.1 Дэд бүтэц

| Шалгалт | Үр дүн |
|---|---|
| `personal3-uat-postgres-1` | up (healthy) `:25432`, **11 хүснэгт** (контейнер эхлэхэд `app.migrate`) |
| `personal3-uat-redis-1` | up (healthy) `:26379` |
| `personal3-uat-backend-1` | up `:28000`, `/api/v1/health` → `200` |
| `personal3-uat-frontend-1` | up `:18080`, bind mount алга |
| `GET /api/v1/health` | `status=degraded`, `database.reachable=true`, `redis.reachable=true`, `broker.reachable=false` (түлхүүргүй), 4 provider healthy |

### 3.2 Байршуулсан nginx (U-1/U-2/U-4)

```
GET :18080/            200      GET :18080/providers   200
GET :18080/approvals   200      GET :18080/tuning      200
GET :18080/settings    200      GET :18080/activity    200
GET :18080/api/v1/health 200   (backend-ийн шууд хариутай ижил system_state)
GET :18080/health        200   (JSON, O-2)
GET :18080/assets/index-BbK0HJ_A.js 200
ws://:18080/ws?channels=system,orders → upgrade OK, эхний event = state_changed
```

Serve хийгдэж буй bundle-ийн нэр `index-BbK0HJ_A.js` нь DEV_TEST болон
өмнөх хоёр UAT тайланд бичигдсэнтэй **яг ижил** — давтагдах build-ийн
нэмэлт нотолгоо (энэ удаа image дотор угсрагдсан хувилбар дээр).

### 3.3 Олон instance + Redis (AC-14)

```
POST backend-1 /api/v1/providers/research/switch {"provider_id":"openai-fc"} -> 200
WS@backend-2 {"channel":"system","payload":{"seq":2,"event":"provider_switched",
              "role":"research","previous_provider_id":"claude-mcp",
              "new_provider_id":"openai-fc","in_flight_calls":0}}
```

Мөн backend-1-д хийсэн `kill-switch` нь backend-2-ийн зам дээр `halted`
болж хүрэв (§3.4).

### 3.4 Төлөвийн машин ба хамгаалалт

| AC | Шалгалт | Үр дүн |
|---|---|---|
| AC-36 | `POST /kill-switch` | `200 state=halted`; давтан дуудахад мөн `200` (идемпотент) |
| AC-33 | `halted` үед гарын order (backend-1) | `409 system_halted` |
| AC-33 | `halted` үед гарын order (backend-2) | `409 system_halted` — халалт нь СИСТЕМД хамаарна |
| AC-15 | broker унасан үед `POST /system/activate` | `409 breaker_still_tripped`, `tripped=[api_error_rate, ws_disconnects]` |
| AC-37 | төлөв DB-д тогтвортой | backend-2-ийг **бүрэн restart** хийсний дараа `state=halted`, `reason=uat6` DB-ээс уншигдав |

### 3.5 Гэрээ, аудит, өгөгдлийн үнэн зөв байдал

| AC | Шалгалт | Үр дүн |
|---|---|---|
| — | амьд `openapi.json` vs `contracts/openapi.yaml` | **21 зам+метод : 21** таарав; цорын ганц зөрүү нь path parameter-ийн НЭР (`{orderId}` vs `{order_id}` гэх мэт 4 зам) — URL-ийн бүтэц ижил, O-5 болгон бүртгэв |
| AC-20/21 | 200 хариу бүрд `source`/`as_of`/`stale`/`system_state` | 7/7 (200 буцаасан бүгд), `source=alpaca_paper`; үлдсэн 3 нь `503 broker_unavailable` |
| AC-9/AC-25 | broker хүрэхгүй үед өгөгдөл ЗОХИОХГҮЙ | `/account`, `/positions`, `/attribution`, `/market/quote/AAPL` → `503 broker_unavailable` (`Problem`). **Бие даасан баталгаа:** тухайн үед Alpaca paper данс өөрөө АЖИЛЛАЖ БАЙСАН (`equity=100014.39`, данс `PA3RXD70V8XN`, `alpaca` MCP-ээр уншив) — өөрөөр хэлбэл backend нь өгөгдөл байхгүй биш, түлхүүргүй үедээ ч хуучин/зохиомол тоо буцаадаггүй |
| N-2 | дутуу биетэй `POST /orders/manual` | `422` + `type/title/status/code/detail/errors` |
| AC-17 | `python -m app.audit.verifier` (контейнер дотор) | `chain бүрэн бүтэн`, exit 0 |
| AC-8 | `audit_log` дээр `UPDATE`/`DELETE`/`TRUNCATE` | 3/3 татгалзав (`p3_refuse_mutation`, LLD §5.7) |
| AC-18 | `python -m app.audit.replay` | энэ ажиллалтын төлөвийн шилжилт ба 4 provider солилт ЗӨВХӨН логоос сэргээгдэв, `unknown_events: []` |
| AC-10 | `POST /providers/{role}/switch` | `200`, restart шаардахгүй, нөгөө instance-д хүрнэ |
| AC-19 | лог ба DB дотор түлхүүр хэлбэрийн мөр | backend 2 контейнерын логт 0; `audit_log.payload ~* '(apca\|api_key\|secret\|bearer )'` → **0 мөр** |
| AC-22 | whitelist/bounds засах endpoint | 21 замын дунд mutator **алга** |
| AC-24 | token-гүй `POST /tuning/promote` | `409 confirmation_required` |
| AC-13 | горимын заалт | API-ийн бүх 200 хариунд `source=alpaca_paper`; serve хийгдсэн bundle дотор `PAPER`/`LIVE`/`BACKTEST` шошго байна |

### 3.6 Автомат тест (байршуулсан эх кодоос)

| Багц | Үр дүн |
|---|---|
| backend `pytest -q` (`.venv-uat`, `requirements.lock`, Python 3.12.13) | **388 passed, 1 warning, 0 failed** (113s) |
| frontend `npm test -- --run` (`check:api` + `lint` + `typecheck` + `vitest`) | **6 файл / 66 тест passed** (54s) |

---

## 4. Илэрсэн зөрчил

**Блоклогч зөрчил алга.** Энэ ажиллалтад шинэ зөрчил илрээгүй.

---

## 5. Ажиглалт (зөрчил биш)

- **O-3 — WS `seq` нь process тус бүрдээ** (өмнөх тайлангуудын ажиглалт хэвээр).
- **O-4 — агент дуудах endpoint байхгүй**: `GET /agent-decisions` хоосон,
  21 замын дунд шинжилгээ эхлүүлэх зам алга. AC-4/AC-6 нь зөвхөн автомат
  тестээр шалгагдана (өмнөх тайлангийн ажиглалт хэвээр).
- **O-5 (шинэ) — гэрээ vs код дахь path parameter-ийн нэрлэлт зөрөөтэй**:
  `contracts/openapi.yaml` нь `{orderId}`, `{approvalId}`, `{decisionId}`,
  харин код нь `{order_id}`, `{approval_id}`, `{decision_id}`. URL-ийн
  бүтэц ижил тул клиентэд нөлөөлөхгүй, гэхдээ гэрээнээс код үүсгэвэл
  нэр зөрнө.
- **O-6 (шинэ) — backend image дотор `pytest` ажиллуулбал static тестүүд
  унана**: тестүүд репогийн root-ийн `/contracts/openapi.yaml`,
  `frontend/package-lock.json` зэргийг хайдаг бол image-д зөвхөн `app/`
  байдаг (`FileNotFoundError: '/contracts/openapi.yaml'`). Энэ нь
  бүтээгдэхүүний гэм биш, тестийг ЯМАР контекстээс ажиллуулахын ялгаа —
  репогоос ажиллуулахад 388 бүгд тэнцэнэ (§3.6).

---

## 6. Шалгалт ХИЙГДЭЭГҮЙ хамрах хүрээ (ил тодорхойлолт)

Байршуулсан backend-д Alpaca түлхүүр **олгогдоогүй**
(`ALPACA_API_KEY=`/`ALPACA_API_SECRET=` хоосон; `.env` нь `.gitignore`-д,
түлхүүр зөвхөн орчноос ирнэ). Тиймээс **broker-ээс хамаарах дараах зүйлс
энэ тойрогт шалгагдаагүй**:

- AC-31 (хязгаар доторх order Risk→Execution→Alpaca), idempotency
- AC-5 (хязгаараас дээш order → `ESCALATE_TO_HUMAN` → approval)
- AC-34/AC-35 (wind-down үеийн exposure нэмэх/багасгах)
- AC-30 (бодит позицтой attribution), AC-1 (equity/позицийн тэнцэл)
- AC-16 (halt нь позицийг автоматаар хаахгүй), EOD reconciliation

Энэ тойрогт нэмж тогтоосон зүйл:

1. **Alpaca paper данс өөрөө хүрэх боломжтой байсан** (`alpaca` MCP server
   ажиллав: данс `PA3RXD70V8XN`, `equity=100014.39`,
   `position_market_value=7748.24`). Өөрөөр хэлбэл саад нь сүлжээ биш,
   **байршуулалт руу түлхүүр дамжуулах зам байхгүй** явдал.
2. **Систем энэ ажиллалтад ямар ч order илгээгээгүй**: Alpaca дээрх сүүлийн
   order `16:30Z` (өмнөх ажиллалтынх), шалгалтын үе `20:11–20:17Z` —
   `halted` төлөв дэх хориг амьдаар ч биелэв. Позиц хаагдаагүй
   (`position_market_value` хэвээр) нь AC-16-ийн зан төлөвтэй нийцнэ.
3. Дээрх ACs нь **1-р UAT ажиллалтад (`uat-test-report.md`, commit
   `66c528c`) бодит paper данс дээр тэнцсэн**. Тэрнээс хойш `backend/app`-д
   орсон өөрчлөлт нь `agents/router.py`, `main.py`, `risk/breaker.py`,
   `system/scheduler.py` (4 файл, +103 мөр) — **order илгээх зам огт
   өөрчлөгдөөгүй**. Гэвч энэ нь амьд шалгалтыг ОРЛОХГҮЙ.

---

## 7. Давтан гүйцэтгэх заавар

```bash
# 1. байршуулалт (repo root). backend/.env нь .env.example-ээс — runbook §0
docker compose -p personal3-uat -f docker-compose.dev.yml up -d --build

# 2. AC-14-д хэрэгтэй 2 дахь instance (шалгалтын тоноглол, устгана)
docker inspect personal3-uat-backend-1 --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -vE '^(PATH|LANG|GPG_KEY|PYTHON_)' > b2.env
docker run -d --name personal3-uat-backend-2 --network personal3-uat_default \
  --env-file b2.env personal3-uat-backend:latest

# 3. шалгуур — БАЙРШУУЛСАН контейнер дотроос
docker cp docs/PERSONAL-3/uat/uat_round6.py personal3-uat-backend-1:/tmp/uat6.py
docker exec -e UAT_A=http://localhost:8000 \
            -e UAT_B=http://personal3-uat-backend-2:8000 \
            -e UAT_FE=http://frontend:80 \
            personal3-uat-backend-1 python /tmp/uat6.py

# 4. аудит
docker exec personal3-uat-backend-1 python -m app.audit.verifier
docker exec personal3-uat-backend-1 python -m app.audit.replay

# 5. автомат тест (репогоос, image-ээс БИШ — O-6)
cd backend && uv venv --python 3.12 .venv-uat && uv pip install -p .venv-uat -r requirements.lock
./.venv-uat/Scripts/python -m pytest -q
cd ../frontend && npm ci && npm test -- --run

# 6. broker-ээс хамаарах гол зам (түлхүүр байгаа үед)
ALPACA_API_KEY=... ALPACA_API_SECRET=... python docs/PERSONAL-3/uat/uat_round5.py

# цэвэрлэгээ
docker rm -f personal3-uat-backend-2
```

---

## 8. Дараагийн алхамд буцаах жагсаалт

1. **Пайплайн (блоклогч биш, хамрах хүрээ)** — UAT байршуулалтад Alpaca
   paper түлхүүрийг орчноос дамжуулах зам тогтоох. Түлхүүр энэ machine
   дээр байгаа боловч байршуулсан backend-д хүрэхгүй тул арилжааны гол
   зам UAT-д 3 тойрог дараалан амьдаар шалгагдахгүй байна (§6).
2. **O-5 (DEVELOPMENT, жижиг)** — `contracts/openapi.yaml`-ийн path
   parameter-ийн нэрийг кодтой нэгтгэх.
3. **O-4 (бүтээгдэхүүний шийдвэр)** — шинжилгээ эхлүүлэх operator-ийн
   endpoint/UI байхгүй тул AC-4/AC-6 нь UAT-д амьдаар шалгагдахгүй.
4. **Harbor** — энэ репод registry pipeline тодорхойлогдоогүй тул
   байршуулалт нь локал `--build`-аар хийгддэг (UAT_DEPLOY-ийн тэмдэглэлтэй
   ижил, өөрчлөлт алга).
