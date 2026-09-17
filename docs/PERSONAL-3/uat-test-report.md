<!-- PERSONAL-3 · UAT тестийн тайлан · UAT_TEST · 2026-09-18 -->

# PERSONAL-3 — UAT тестийн тайлан (4-р ажиллалт)

- **Орчин:** UAT, compose project `personal3-uat` (`docker-compose.dev.yml`) —
  Postgres 16 `localhost:25432`, Redis 7 `localhost:26379`, nginx static
  `localhost:18080`
- **Backend:** энэ ажиллалтад ШАЛГАХЫН ТУЛД өөрөө асаасан —
  `uvicorn app.main:build --factory` :28000 ба :28001 (Python 3.12.13,
  `requirements.lock` бүрэн), `REDIS_URL=redis://localhost:26379/0`
- **Broker:** Alpaca **paper** (`paper-api.alpaca.markets`), зах зээл
  **НЭЭЛТТЭЙ** (`/v2/clock → is_open=true`) — өмнөх бүх ажиллалт хаалттай
  цагт хийгдсэн тул энэ нь шинэ нөхцөл
- **Commit:** `66c528c` (`issue/personal-3`)
- **Үүрэг:** зөвхөн ШАЛГАЖ тайлагнах — **код заваагүй**

---

## 1. Нэгдсэн дүн

| Ангилал | Тоо |
|---|---|
| Тэнцсэн шалгуур (арилжааны гол зам, round5 harness) | 17 |
| Тэнцсэн шалгуур (регресс, round1 harness) | 20 |
| Нэмэлт гараар шалгасан зүйл | 9 |
| Автомат тест | backend `pytest` **377 passed / 0 failed**, frontend `npm test` **66 passed** |
| **Блоклогч зөрчил** | **U-1** — UAT-д байршуулсан UI нь backend-д хүрэхгүй |
| Бусад зөрчил | U-2, U-3 |
| Ажиглалт | O-1 … O-4 |

**Дүгнэлт: UAT ТЭНЦЭЭГҮЙ.**

Програм хангамжийн логик талаас **өмнөх тойргийн блоклогч N-1 арилсан** —
систем бодит paper данс дээр `active` болж, order илгээж, wind-down/kill-switch
хийж, WS-ээр бүх instance-д түгээж байна. Гэвч UAT-д **байршуулсан** зүйл нь
операторт ашиглах боломжгүй хэвээр: frontend зөвхөн static-аар гарсан бөгөөд
backend руу reverse proxy алга (`/api/v1/*` → 404), SPA fallback алга
(`/approvals` → 404), мөн UAT_DEPLOY нь backend-ийг огт байршуулаагүй.

---

## 2. Өмнөх тойргийн зөрчлүүд — одоогийн байдал

| ID | Өмнөх тайлбар | Одоо | Нотолгоо |
|---|---|---|---|
| **N-1** (блоклогч) | trade-update WS хэрэгжээгүйгээс breaker мөнх унасан, `activate` үргэлж 409 | **ЗАСАГДСАН** | `POST /system/activate` → `200 state=active`; бодит Alpaca WS-ээс `trade_update` ирж байна (§3.3) |
| **N-2** | 422 хариу `Problem` схемийг зөрчсөн | **ЗАСАГДСАН** | дутуу биетэй `POST /orders/manual` → `422` + `type/title/status/code/detail/errors` |
| **N-3** | broker-ийн бизнес татгалзал `broker_unavailable` болж далдардаг | **ЗАСАГДСАН** — энэ ажиллалтад `order_failed` огт үүсээгүй; тодорхойгүй symbol нь broker-т хүрэхээсээ ӨМНӨ `risk_rejected` болов | audit_log-д өнөөдрийн `order_failed` = 0 |
| **N-4** | repo дотор secret хэлбэрийн мөр (pytest 1 унасан) | **ЗАСАГДСАН** | `pytest -q` → 377 passed, **0 failed** |
| Хянагчийн санал (1) | `build()` нь `settings.REDIS_URL`-ийг EventBus-руу дамжуулдаггүй → `redis.reachable=false` | **ЗАСАГДСАН** (`03b49ba`) | `/health` → `"redis": {"reachable": true}`; instance хоорондын fan-out бодитоор ажиллав (§3.3) |
| Хянагчийн санал (2) | `stream_trade_updates()` coroutine never awaited RuntimeWarning | **ЗАСАГДСАН** (`03b49ba`) | `python -X dev -m uvicorn …` (бүх warning асаалттай) — логт `RuntimeWarning`/`never awaited` **0 удаа**; `run_forever` нь `finally: await _close(stream)` хийдэг |

---

## 3. Шалгагдсан зүйлс

### 3.1 Дэд бүтэц

| Шалгалт | Үр дүн |
|---|---|
| `personal3-uat-postgres-1` | up (healthy), 25432; `python -m app.migrate` → exit 0, 11 хүснэгт |
| `personal3-uat-redis-1` | up (healthy), 26379 |
| `personal3-uat-frontend-1` | up, 18080 — **эхэндээ 404** (U-2), дахин угсарсны дараа 200 |
| `GET /health` | `status=ok`, `broker.reachable=true`, `database.reachable=true`, `redis.reachable=true`, 4 provider healthy |

### 3.2 Арилжааны гол зам (бодит paper данс, зах зээл нээлттэй)

| AC | Шалгалт | Үр дүн |
|---|---|---|
| AC-37 | баталгаажуулалтгүй `activate` | 409 `confirmation_required` |
| AC-37 | token-той `activate` | **200 `state=active`** |
| AC-37 | дахин асаалтын дараа төлөв хадгалагдана | `halted` төлөв DB-ээс уншигдав |
| AC-31 | хязгаар доторх гарын order Risk→Execution→Alpaca | 202, 1.1 сек, Alpaca дээр ижил `client_order_id`-тай order бодитоор үүсэв |
| AC-31 | idempotency (ижил `Idempotency-Key`) | давхар order үүсээгүй (alpaca 12→12) |
| AC-32 | гарын order-ийн гарал үүсэл | `origin=manual_operator`, `origin_detail=operator` |
| AC-5 | хязгаараас дээш order | `ESCALATE_TO_HUMAN` → 409 `confirmation_required`, Alpaca руу **0 дуудалт**; баталгаажуулсны дараа л илгээгдэв; нэг token дахин ажиллахгүй (409) |
| §7 | хатуу хязгаар давсан order | `REJECT position_pct: 14.46 vs MAX_POSITION_PCT 10` → 422, broker руу очоогүй |
| AC-34 | wind-down | 200 `winding_down`, `seconds_remaining=899`, HTTP 0.30 сек |
| AC-35 | `winding_down` үед exposure НЭМЭГДҮҮЛЭХ | 422 `winding_down_increase_blocked`, alpaca 12→12 |
| AC-35 | `winding_down` үед позиц БАГАСГАХ | 202, alpaca 12→13 |
| AC-36 | kill-switch | 200 `halted`, 0.33 сек |
| AC-16 | halt нь позиц/order-ыг АВТОМАТААР хаахгүй | позиц 22→22, нээлттэй order 0→0 |
| AC-33 | `halted` үед гарын order-ийн бүх зам | 3/3 замд 409 `system_halted`, Alpaca руу 0 дуудалт |
| AC-30 | attribution | бодит позицтой таарав (`AAPL`, `manual_operator`) |
| AC-20/21 | бүх 200 хариунд `source`, `as_of`, `stale`, `system_state` | 10/10 endpoint дээр `alpaca_paper` |

### 3.3 WS fan-out хоёр instance хооронд (AC-14) + бодит trade-update

`:28000`-д order илгээгээд `:28001`-ийн `/ws?channels=orders,system`-ийг сонсов:

```
order    202 p3-e06abde322cb8791af79093c        (:28000-д илгээв)
WS@28001 system  state_changed  active
WS@28001 orders  order_submitted broker_order_id=1fe8434b-...
WS@28001 orders  trade_update    client_order_id=p3-e06abde322cb8791af79093c
```

`order_submitted` нь Redis-ээр нөгөө instance-д хүрсэн, `trade_update` нь
**бодит Alpaca WS урсгалаас** ирсэн — хоёулаа N-1 ба хянагчийн 1-р саналын
бүрэн шийдэгдсэнийг батална.

### 3.4 Аудит, сэргээлт, provider

| AC | Шалгалт | Үр дүн |
|---|---|---|
| AC-17 | `python -m app.audit.verifier` | `chain бүрэн бүтэн` (exit 0), 58 бичлэг |
| AC-8 | audit_log дээр `UPDATE`/`DELETE` | DB trigger татгалзав: `append-only хүснэгт: audit_log дээр UPDATE хийх боломжгүй (LLD §5.7)` |
| AC-18 | `python -m app.audit.replay` | арилжаа/төлөв/provider солилтыг ЗӨВХӨН логоос сэргээв, `unknown_events: []` |
| AC-10 | `POST /providers/research/switch` | 200, `claude-mcp → openai-fc`, restart БАЙХГҮЙ (гэхдээ U-3-ыг үз) |
| AC-19 | лог ба DB дотор түүхий түлхүүр | backend 2 логт 0 тохиолдол, `audit_log.payload`-д 0 тохиолдол |
| AC-22 | whitelist/bounds засах endpoint | 21 замын дунд mutator **алга** |
| AC-24 | token-гүй tuning promote | 409 `confirmation_required` |

---

## 4. Илэрсэн зөрчил

### U-1 (БЛОКЛОГЧ) — UAT-д байршуулсан UI нь backend-д хүрэхгүй

```
GET http://localhost:18080/              -> 200 (index.html)
GET http://localhost:18080/api/v1/health -> 404 (nginx)
GET http://localhost:18080/approvals     -> 404 (nginx)
```

Frontend нь `fetch('/api/v1/...')` ба `ws://.../ws`-ыг **нэг origin**-оос
дууддаг (`frontend/vite.config.ts`: «production-д reverse proxy энэ үүргийг
гүйцэтгэнэ»). UAT байршуулалт нь `nginx:alpine`-ыг тохиргоогүйгээр зөвхөн
static serve хийсэн тул:

- өгөгдөл татах бүх хүсэлт 404 — самбар, approval queue, activity log,
  provider switcher, settings БҮГД хоосон;
- SPA deep link (`/approvals`, `/settings`) 404.

Үр дагавар: операторын хувьд UAT-д байршуулсан бүтээгдэхүүн **ажиллахгүй**.
UI шаарддаг AC-3, AC-4, AC-6, AC-7, AC-9, AC-11, AC-13 нь энэ орчинд
шалгагдах боломжгүй.

Шалтгаан нь код биш **байршуулалт**: `docker-compose.dev.yml`-ийн `frontend`
нь nginx-д `proxy_pass` ба `try_files $uri /index.html` бүхий тохиргоо
өгөхгүй. Мөн UAT_DEPLOY нь **backend-ийг огт байршуулаагүй** — энэ шалгалтыг
хийхийн тулд backend-ийг эх кодоос өөрөө асаах шаардлага гарсан.

### U-2 — байршуулсан frontend нь УСТСАН ажлын хавтас руу mount хийгдсэн

```
docker inspect personal3-uat-frontend-1
  -> C:\...\Temp\task-293\repo\frontend\dist -> /usr/share/nginx/html
GET http://localhost:18080/ -> 404 (153B)
```

Ажлын хавтас даалгавар бүрийн дараа устдаг тул өмнөх алхмын байршуулалт
дараагийн алхам дээр өөрөө «унана». Яг ижил зөрчлийг DEV_TEST тайланд
бүртгэсэн боловч UAT_DEPLOY давтсан. Шалгалтыг үргэлжлүүлэхийн тулд
`npm ci && npm run build` хийж `frontend` контейнерийг энэ хавтаснаас дахин
үүсгэв (код заваагүй — байршуулалтыг сэргээсэн).

Дашрамд: дахин угсарсан bundle-ийн нэр `index-BbK0HJ_A.js` нь DEV_TEST-ийн
тайланд бичигдсэнтэй **яг ижил** — давтагдах build-ийн нэмэлт нотолгоо.

### U-3 — provider hot-swap нь зөвхөн тухайн process-д үйлчилнэ

```
POST :28000/api/v1/providers/research/switch {"provider_id":"openai-fc"} -> 200
GET  :28000/api/v1/providers -> active = {"research": "openai-fc"}
GET  :28001/api/v1/providers -> active = {"research": "claude-mcp"}   <- хуучин
```

`ProviderRouter._active` нь process-ийн дотоод dict
(`backend/app/agents/router.py:68,126`), `default_router()` нь эхлэхдээ үргэлж
`{"research": "claude-mcp"}`-ээр эхэлдэг (`router.py:167`) — солилт нь
Redis/DB руу тархдаггүй, дахин асаахад сэргээгддэггүй. `provider_switched`
нь audit_log-д бичигдэж WS-ээр түгээгддэг ч бусад instance-ийн **шийдвэр
гаргах замд** нөлөөлөхгүй.

Үр дагавар: олон instance-тай байршуулалтад оператор provider сольсон ч
хүсэлт аль instance-д унахаас хамаарч ХУУЧИН модель ажилласаар байна —
AC-10 «ажиллагааг тасалдуулахгүйгээр солих» нь чимээгүй хагас биелнэ.

Тэмдэглэл: LLD §12.2 нь router-ийг санаатайгаар process-дотоод (atomic
reference swap) гэж тодорхойлсон бөгөөд хэрэгжилт нь LLD-тэй НИЙЦНЭ. Гэвч
AC-14-ийн шаардлагаар байршуулалт нь олон instance + Redis fan-out-той тул
энэ хосолмол байдал нь AC-10-ыг зөрчих боломжтой. Хянагчийн өмнөх саналд
дурдсан Redis-ийн зөрчилтэй ЯГ ИЖИЛ ангиллын асуудал — шийдвэрийг
DEVELOPMENT/дизайн шатанд гаргах шаардлагатай.

---

## 5. Автомат тест

| Багц | Үр дүн |
|---|---|
| backend `pytest -q` (`.venv-uat`, `requirements.lock`, Python 3.12.13) | **377 passed, 1 warning, 0 failed** (98.99s) |
| frontend `npm test -- --run` | **6 файл / 66 тест passed** (62.14s) |

Өмнөх тойрогт унаж байсан secret-pattern тест (N-4) одоо тэнцэж байна.

---

## 6. Ажиглалт (зөрчил биш)

- **O-1 — `avg_entry_price` нь центэд бөөрөнхийлөгдөнө.** App `336.26`,
  Alpaca `336.265`. `contracts.yaml`-ийн `Money` нь 2 орон гэж заасан тул
  `money_str()` нь `quantize(CENT)` хийдэг. Гэрээний дагуу ЗӨВ боловч дундаж
  үнэ мэтийн центээс нарийн broker утгад AC-1-ийн «яг тэнцүү» шалгуур
  биелэхгүй. Загварын шийдвэр шаардсан зөрүү.
- **O-2 — зах зээл нээлттэй үед equity таарахгүй нь хэвийн.** Дараалсан
  дуудалтуудад Alpaca өөрөө `99999.47 → 99999.67 → 99999.68` гэж хөдөлж
  байв. Өмнөх harness-ийн «app == alpaca тэмдэгт тэмдэгтээр» шалгуур нь зах
  зээл ХААЛТТАЙ үеийн таамаглал дээр бичигдсэн — кодын зөрчил биш.
- **O-3 — WS `seq` нь process тус бүрдээ.** Нэг үед `:28000`-ийн `system`
  суваг `seq=31`, `:28001`-ийнх `seq=18` байв. Клиент дахин холбогдоход өөр
  instance рүү унавал `seq` ухарч харагдана — «завсар алдсан эсэх»-ийг
  `seq`-ээр илрүүлэх клиент андуурч болно.
- **O-4 — агент дуудах endpoint байхгүй.** `GET /agent-decisions` хоосон;
  байршуулсан API-д шинжилгээ эхлүүлэх зам алга (21 замын аль нь ч биш).
  Тиймээс AC-4 (яагаад гэдгийн нотолгоо) ба AC-6 (grounding) нь зөвхөн
  автомат тестээр шалгагдана, амьд системд биш.

---

## 7. Давтан гүйцэтгэх заавар

```bash
# 1. дэд бүтэц
docker compose -p personal3-uat -f docker-compose.dev.yml up -d
# 2. frontend static
cd frontend && npm ci --prefer-offline && npm run build
docker compose -p personal3-uat -f docker-compose.dev.yml up -d --force-recreate frontend
# 3. backend (Python 3.12 + requirements.lock). backend/.env дотор:
#    DATABASE_URL=postgresql+asyncpg://p3:p3@localhost:25432/p3
#    REDIS_URL=redis://localhost:26379/0
cd backend && python -m app.migrate
python -X dev -m uvicorn app.main:build --factory --host 127.0.0.1 --port 28000
python       -m uvicorn app.main:build --factory --host 127.0.0.1 --port 28001
# 4. harness (artifacts/PERSONAL-3/uat.py, uat5.py — портыг 28000/28001/18080 болго)
ALPACA_API_KEY=... ALPACA_API_SECRET=... python uat5.py
```

Alpaca paper түлхүүр нь орчноос ирнэ — репод ХЭЗЭЭ Ч хадгалагдахгүй
(`backend/.env` нь `.gitignore`-д).

---

## 8. DEVELOPMENT / DEPLOY руу буцаах жагсаалт

1. **U-1 (DEPLOY, блоклогч)** — UAT-ийн frontend-д reverse proxy (`/api` ба
   `/ws` → backend) ба SPA fallback (`try_files $uri /index.html`) бүхий
   nginx тохиргоо өгөх; мөн UAT-д **backend service-ийг бодитоор байршуулах**.
2. **U-2 (DEPLOY)** — bind mount-ыг түр зуурын ажлын хавтас руу заахаа болих
   (static-аа image дотор шатаах эсвэл нэрлэсэн volume ашиглах).
3. **U-3 (DEVELOPMENT/дизайн)** — олон instance-тай байршуулалтад идэвхтэй
   provider-ийг хуваалцах/сэргээх эсэхийг шийдэх (Redis/DB-д хадгалах, эсвэл
   LLD-д «нэг instance» гэж ил тодорхойлох).
