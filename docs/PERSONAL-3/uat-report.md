<!-- PERSONAL-3 · UAT тайлан · UAT_TEST · 2026-09-17 -->

# PERSONAL-3 — UAT тестийн тайлан (3-р ажиллалт, бүрэн)

**Огноо:** 2026-09-17 · **Салбар:** `issue/personal-3`
**Орчин:** локал UAT host (Windows 11) — Postgres 25432, Redis 26379 (Docker
`personal3-uat`), backend `uvicorn app.main:build --factory` :8000 ба :8001
(Python 3.12.13, `requirements.lock`), frontend `vite preview` :4173
(`npm ci` + `npm run build`), Alpaca **paper** (`paper-api.alpaca.markets`).

> Энэ бол **шалгалтын** тайлан: код заваагүй (QA-гийн verify-deployment
> горим). Илэрсэн зөрчлийг зөвхөн тайлагнав.

Энэ ажиллалтад операторын өгсөн Alpaca paper key ID **ба secret** хоёулаа
ирсэн тул `GET /v2/account` → **200** болж, өмнөх хоёр ажиллалтад блоклогдож
байсан **арилжааны гол зам бүхэлдээ** (order илгээх, escalation, wind-down,
kill-switch, лог сэргээлт) бодит broker дээр шалгагдав.

---

## 1. Нэгдсэн дүн

| Ангилал | Тоо |
|---|---|
| Тэнцсэн шалгуур (round5 арилжааны зам) | 24 |
| Тэнцсэн шалгуур (round1 регресс) | 22 |
| Автомат тест | backend `pytest` 357 тэнцсэн / 1 унасан (N-4), frontend 66 тэнцсэн |
| **Блоклогч зөрчил** | **N-1** — систем `active` болж чадахгүй |
| Бусад зөрчил | N-2, N-3, N-4 |
| Ажиглалт | O-1 … O-5 |
| Шалгах боломжгүй (deploy хийсэн бүтээгдэхүүнд гадаргуу байхгүй) | AC-3, AC-4, AC-6, AC-7, AC-8, AC-9, AC-11, AC-13 |

**Дүгнэлт: UAT ТЭНЦЭЭГҮЙ.** Шалтгаан нь N-1: бодит (болон ямар ч) орчинд
`POST /system/activate` нь **үргэлж** `409 breaker_still_tripped` буцаадаг тул
систем `halted`-аас хэзээ ч гарахгүй — өөрөөр хэлбэл гаргасан хувилбар нь
арилжаа хийх чадваргүй. Бусад бүх зүйл (гэрээ, эрсдэл, төлөвийн машин,
audit, fan-out) ажиллаж байгаа нь батлагдсан.

---

## 2. N-1 (БЛОКЛОГЧ) — trade-update WS хэрэгжээгүйгээс circuit breaker байнга унасан

**Илрэл.** Шинээр босгосон, `breaker_events` хүснэгт нь **хоосон** орчинд:

```
t≈0s   ws_disconnects=6/5  tripped=True  activate=409 breaker_still_tripped
t≈60s  ws_disconnects=8/5  tripped=True  activate=409 breaker_still_tripped
t≈180s ws_disconnects=12/5 tripped=True  activate=409 breaker_still_tripped
```

`daily_loss`, `api_error_rate`, `order_reject_rate` — бүгд `tripped=false`.
Зөвхөн `ws_disconnects` унасан бөгөөд тоо нь **хязгааргүй өсдөг**.

**Шалтгаан (кодоор).**

- `app/broker/alpaca.py:302` — `AlpacaAdapter.stream_trade_updates()` нь
  `raise NotImplementedError("app.stream.ingest нь WS холболтыг эзэмшинэ")`.
- `app/stream/ingest.py:229` — `TradeUpdateIngestor.run_forever()` яг тэр
  метод руу ханддаг, `except Exception` дээр `breaker.record("ws_disconnect",
  ok=False)` бичээд backoff-оор **мөнхөд** дахин оролддог.
- `app/main.py:148` — энэ давталт startup дээр task болж эхэлдэг.

Өөрөөр хэлбэл Alpaca-ийн WS холболтыг **хэн ч хэрэгжүүлээгүй**: adapter нь
"ingest эзэмшинэ" гэж, ingest нь adapter-ыг дууддаг. Тиймээс `BREAKER_WINDOW`
(300 сек) дотор backoff-ийн дээд утга 30 сек ⇒ цонх тутамд ≥10 `ws_disconnect`
⇒ `WS_DISCONNECT_LIMIT=5`-ыг байнга давна.

**Үр дагавар.**

1. `POST /system/activate` (AC-37-ийн цорын ганц зам) үргэлж 409 → систем
   `halted`-аас гарахгүй → агент ч, оператор ч арилжаа хийх боломжгүй.
2. Fill ingestion байхгүй: `orders.status` нь `accepted` дээр хөлдөнө,
   `fills` хүснэгт хоосон үлдэнэ (AC-18-ийн fill талын сэргээлт, AC-13-ийн
   drift метрик хэмжигдэхгүй).
3. AC-2-ийн "WS тасарсны дараа 5 сек дотор stale banner" нь ticks урсгал огт
   байхгүй тул утгагүй болно.

**Хэмжилт (баталгаа).** Энэ метрикийг **зөвхөн оношилгооны зорилгоор**
хажуу тийш нь тавьж (`WS_DISCONNECT_LIMIT=1000000` орчны хувьсагчаар,
код заваагүй) дахин ажиллуулахад **бүх 24 шалгуур тэнцсэн** — доорх §3.
Энэ нь N-1-ийг "нөхөх" арга БИШ: тохиргоогоор хязгаарыг өргөх нь breaker-ийн
дөрөв дэх метрикийг бүхэлд нь унтраана. Засвар нь DEVELOPMENT-д: WS урсгалыг
бодитоор хэрэгжүүлэх, эсвэл хэрэгжээгүй урсгалыг `ws_disconnect` гэж
бүртгэхгүй байх (`NotImplementedError`-ыг тасалдал гэж үзэхгүй).

---

## 3. Арилжааны гол зам — 24 шалгуур (round5)

`docs/PERSONAL-3/uat/uat_round5.py`, breaker-ийг оношилгооны зорилгоор
хажуу тийш тавьсан үед. Alpaca paper данс: equity 100 000, зах зээл хаалттай
(09:12 UTC), тул extended-hours limit order-оор бодит **позиц** үүсгэж,
market order-ууд `accepted` төлөвт дараалав.

| AC | Шалгуур | Баримт |
|---|---|---|
| AC-1 | `/account` нь Alpaca-тай тэнцүү | `equity=99999.79 cash=99665.50 buying_power=399598.01` — Alpaca-ийн түүхий утгатай Decimal-аар тэнцүү |
| AC-1 | `/positions` нь Alpaca-тай тэнцүү | `AAPL qty=1 avg_entry_price=334.50`, зөрүү 0 талбар |
| AC-29 | гадуур нээсэн позиц `external` | `positions=1 external=1` — `ext-uat-probe-1` client_order_id-тай, локал мөргүй позиц `external` гэж шошгологдов (таамаглаагүй) |
| AC-30 | attribution нь бодит мөрөөс | `attribution=['AAPL'] positions=['AAPL']`, groups нь origin-оор (`external`, `manual_operator`) |
| AC-2 | quote `as_of` + `stale` | `as_of=2026-09-16T20:00:03Z stale=true` — хаалттай зах зээлийн хуучин quote-ыг ЗАСААГҮЙ, ил тэмдэглэв |
| AC-37 | баталгаажуулалтгүй `activate` | `409 confirmation_required` |
| AC-15 | breaker хэвийн үед | `daily_loss -0.10/-2000`, `api_error_rate 0.0000/0.05` — унаагүй |
| AC-37 | token-той `activate` | `200 state=active` |
| AC-31 | гарын order Risk→Execution→Alpaca | `202` 2.141s, `risk.decision=APPROVE`, `broker_order_id=42538973-…` |
| AC-32 | origin = `manual_operator` | `origin=manual_operator origin_detail=operator client_order_id=p3-93ad5e105f6673a7c7ab81b9` |
| AC-31 | Alpaca дээр ижил `client_order_id` | Alpaca order 6→7, `('AAPL','buy','1','new')` |
| AC-31 | idempotency | ижил key → ижил `order.id`, Alpaca order 7→7 (давхар submit БАЙХГҮЙ) |
| AC-5 | хязгаараас дээш → баталгаажуулалт | `409 confirmation_required`, `ESCALATE_TO_HUMAN: order_notional 6649.80 vs MAX_ORDER_NOTIONAL 5000.00`, **Alpaca руу 0 дуудалт** (7→7) |
| AC-5 | баталгаажуулсны дараа илгээгдэнэ | `202`, Alpaca 7→8 |
| AC-5 | token дахин хэрэглэгдэхгүй | `409 confirmation_required` |
| AC-34 | wind-down 1 сек дотор + WS | `200 winding_down seconds_remaining=899`; WS: :8000 **0.328 s**, :8001 **0.328 s** (Redis fan-out) |
| AC-35 | wind-down: НЭМЭГДҮҮЛЭХ хориглогдоно | `422 winding_down_increase_blocked`, `wind_down_direction: increase vs reduce_only`, Alpaca 8→8 |
| AC-35 | wind-down: БАГАСГАХ дамжина | `202`, Alpaca 8→9, sell 1 AAPL (позиц хаах) |
| AC-36 | wind-down үед kill-switch → halted | `200 halted`, WS :8000 **0.297 s**, :8001 **0.297 s** |
| AC-16 | halt позицыг хаахгүй | өмнө `[('AAPL','1')]` дараа `[('AAPL','1')]` |
| AC-16 | halt нээлттэй order-ыг цуцлахгүй | нээлттэй order 1→1 |
| AC-33 | HALTED үед гарын order-ийн БҮХ зам | `['409/system_halted','409/system_halted','409/system_halted']` (энгийн buy, sell, баталгаажуулалттай том order), Alpaca 9→9 |
| AC-20 | бүх 200 хариунд `source` | 7 endpoint, бүгд `alpaca_paper` |
| FE | frontend proxy бодит өгөгдөл | `200 positions=1` |

### 3.1 AC-18 — арилжааг ЗӨВХӨН логоос сэргээх

`python -m app.audit.replay --from 2026-09-17T00:00:00Z` (зөвхөн `audit_log`
уншина) → Alpaca-ийн `/v2/orders?status=all`-тай тулгав:

```
логийн order:            14  (8 амжилттай + 6 илгээгдээгүй оролдлого)
Alpaca дээрх p3- order:   8
амжилттай лог == Alpaca:  True     зөрүү: []
талбарын зөрүү (side/qty): []
unknown_events:           []
```

6 амжилтгүй мөр нь broker руу хүрээгүй оролдлогууд (`failure_reason` талбартай)
— Alpaca дээр байхгүй нь ЗӨВ. Сэргээлтэд алдагдсан ч, зохиогдсон ч арилжаа
байхгүй.

### 3.2 AC-17 — audit chain

- Гараар засах оролдлого: `UPDATE audit_log …` → `ERROR: append-only хүснэгт:
  audit_log дээр UPDATE хийх боломжгүй (LLD §5.7)` (DB trigger).
- `DELETE` → мөн адил татгалзав.
- Trigger-ийг зориудаар унтраагаад `seq=5`-ийн `actor`-ыг сольж verifier
  ажиллуулахад: **`ЭВДЭРСЭН seq=5: мөрийн агуулга hash-тайгаа таарахгүй`**.
  Буцааж сэргээсний дараа `chain бүрэн бүтэн`.

### 3.3 AC-10 — hot-swap

`POST /providers/research/switch {"provider_id":"openai-fc"}` → `200` **0.016 s**,
process PID 34800 → 34800 (**restart БАЙХГҮЙ**), `in_flight_calls=0`.
Үл мэдэгдэх provider → `422 provider_unavailable` (Problem схемийн дагуу).

### 3.4 AC-19 — нууц утга

Бодит key/secret `.env`-д байхад backend :8000, :8001, frontend-ийн лог, мөн
`audit_log.payload` дотор **0 олдоц**. CI-ийн secret scanner ажиллаж байгааг
N-4 (доор) нотлов.

---

## 4. Регресс — 22 шалгуур (round1)

`docs/PERSONAL-3/uat/uat_round1.py` → **22 PASS, 0 FAIL, 4 INFO**. Онцлох:
AC-20 (10 endpoint бүгд `alpaca_paper`), AC-21, AC-37 (restart → `halted`,
өөрөө `active` болоогүй), AC-22 (21 route-ийн дотор whitelist/bounds засах
mutator = 0), AC-24 (token-гүй promote `409`), AC-14 (kill-switch **0.328 s**,
WS broadcast ирсэн), AC-34/AC-36, frontend index + `/api` proxy.

Автомат тест: `pytest -q` → **357 passed, 1 failed** (N-4); `npm test`
(tsc + vitest) → **66 passed**.

---

## 5. Илэрсэн зөрчил

### N-1 (блоклогч) — §2-т дэлгэрэнгүй

Систем хэзээ ч `active` болохгүй. Засвар DEVELOPMENT-д.

### N-2 — 422 validation хариу гэрээний `Problem` схемийг зөрчсөн

Гуравдахь ажиллалтад мөн давтагдав. `RequestValidationError`-ийн handler
`app/main.py`-д бүртгэгдээгүй тул FastAPI-ийн анхдагч хэлбэр гарна:

```
POST /orders/manual  (Idempotency-Key header байхгүй)
422 {"detail":[{"type":"missing","loc":["header","Idempotency-Key"],…}]}
    хүлээгдэж буй: {"type":…,"title":…,"status":422,"code":…,"detail":…}
```

`code` талбар байхгүй тул `code`-оор салаалдаг frontend `undefined` авна.
Ижил зүйл `/tuning/promote`, `/providers/{role}/switch` дээр. Анхаарах нь —
**гэрээний дагуу гаргасан** 422 (жишээ: `provider_unavailable`) зөв хэлбэртэй;
зөрчил нь зөвхөн FastAPI-ийн барьсан validation алдаанд хамаарна.

### N-3 — broker-ийн бизнес татгалзал `broker_unavailable` болж далдардаг

Alpaca-ийн 403-ыг бодитоор барив:

```
Alpaca:  403 {"code":40310000,"message":"potential wash trade detected…",
              "reject_reason":"opposite side market/stop order exists"}
App:     503 {"code":"broker_unavailable","title":"Broker хүрэхгүй байна",
              "detail":"submit_order амжилтгүй: Client error '403 Forbidden'…"}
audit_log / replay:  "failure_reason": "BrokerUnavailable"
```

Оператор "broker хүрэхгүй байна" гэж уншина, бодит байдалд broker **хүрсэн**
бөгөөд order-ыг тодорхой шалтгаанаар татгалзсан. Мөн log-ийн сэргээлтэд
шалтгаан нь алдагдаж, "яагаад илгээгдээгүй" гэдэг хариугүй үлдэнэ.
(4-р ажиллалтын O-4-ийн батлагдсан хэлбэр: 401/403 хоёулаа ижил замаар
далдардаг.)

### N-4 — repo дотор secret хэлбэрийн мөр

`pytest tests/static/test_secret_scanner.py` унав:

```
AssertionError: repo-д secret хэлбэрийн мөр байна:
['docs\PERSONAL-3\uat-report.md: PK…<Alpaca key ID>…', ×4]
```

Өмнөх (2-р) ажиллалтын тайлан нь Alpaca key ID-г бүтнээр нь бичиж commit
хийсэн байв. **Энэ ажиллалтад тэр мөрүүдийг устгаж, тайланг дахин бичив** —
шалгуур дахин ногоон болно. Ямар ч түлхүүрийн утга энэ баримтад байхгүй.

---

## 6. Шалгах боломжгүй байсан шалгуур

Эдгээр нь **credential-ийн асуудал биш** — байршуулсан бүтээгдэхүүнд тэдгээрийг
гаднаас өдөөх гадаргуу байхгүй:

| AC | Яагаад |
|---|---|
| AC-3, AC-4, AC-7, AC-8, AC-9, AC-11 | LLM-ийн turn-ийг ажиллуулах runtime зам БАЙХГҮЙ. `app/agents/gateway.py`, `tools.py`, adapter-ууд нь сан хэлбэрээр байгаа ч тэднийг дуудах HTTP/MCP/scheduler орц байхгүй (`grep`-ээр батлав: `gateway` нь зөвхөн тестээс дуудагдана). Тиймээс `agent_decisions`, `tool_calls`, `approvals` мөр ажиллаж буй системд огт үүсэхгүй. |
| AC-6 | Approval мөр үүсэхгүй тул TTL-ийн автомат reject шалгагдахгүй (мөн цаг хөлдөөх боломжгүй). |
| AC-13 | `app/system/proving.py` нь код дотор ХЭН Ч дууддаггүй (scheduler-т ч, route-д ч бүртгэлгүй) — 30 хоногийн 4 метрикийг гаргах гадаргуу байхгүй. |
| AC-21(UI), AC-38, AC-2(banner), AC-9(UI) | Playwright энэ host дээр байхгүй; frontend-ийн шалгалтыг HTTP түвшинд (8 зам 200, proxy) л хийв. |

AC-23, AC-25…AC-28 нь CI/тестийн шалгуур тул UAT-д давхардуулаагүй
(`pytest` 357 тэнцсэн дотор багтана).

---

## 7. Ажиглалт

- **O-1** `GET /system/state` = **1.5–11 s**. `state_body()` бүрт
  `CircuitBreaker.measure()` broker руу probe хийдэг. Kill-switch-ийн HTTP
  хариу удаашрах шалтгаан нь энэ (төлөв нь 0.3 сек дотор солигдож, WS-ээр
  түгсэн — хариу л удаан).
- **O-2** `enforce_breaker` job давхцаж `skipped: maximum number of running
  instances reached` гэж алгасагдана (O-1-ийн үр дагавар).
- **O-3** `read_only` provider (`local-fallback`)-ыг `research` role-д 200-аар
  чимээгүй оноож болно; дараа нь шинэ санал гарахаа болих ч дохио байхгүй.
- **O-4** Хоёр instance-ыг **зэрэг** (хоосон DB дээр) асаахад хоёулаа анхны
  `audit_log seq=1` мөрийг бичихийг оролдож, нэг нь
  `UniqueViolationError: audit_log_pkey` дээр **startup failed** болж унана.
  Scale-out байршуулалтад анхны boot нь дараалсан байх шаардлагатай.
- **O-5 (орчны олдвор, кодын алдаа биш)** Энэ host дээр HTTPS нь MITM
  proxy-гоор дамждаг тул Python/httpx `CERTIFICATE_VERIFY_FAILED` өгнө.
  Backend-ийг Windows үндэс гэрчилгээний PEM рүү заасан `SSL_CERT_FILE`-тай
  ажиллуулж арилгав — runbook-д нэмэх нь зүйтэй.

---

## 8. Давтан гүйцэтгэх заавар

```bash
# 1) дэд бүтэц
docker compose -p personal3-uat -f docker-compose.dev.yml up -d

# 2) backend (Python 3.12)
cd backend && uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.lock
#   .env: DATABASE_URL …localhost:25432/p3 · REDIS_URL redis://localhost:26379/0
#         ALPACA_ENV=paper · ALPACA_API_KEY/ALPACA_API_SECRET (secrets manager-ээс)
.venv/Scripts/python.exe -m app.migrate
.venv/Scripts/python.exe -m uvicorn app.main:build --factory --port 8000
.venv/Scripts/python.exe -m uvicorn app.main:build --factory --port 8001   # fan-out тест

# 3) frontend
cd frontend && npm ci && npm run build && npm run preview -- --port 4173

# 4) шалгалт
python docs/PERSONAL-3/uat/uat_round4.py   # credential эсэх
python docs/PERSONAL-3/uat/uat_round5.py   # арилжааны гол зам (24 шалгуур)
python docs/PERSONAL-3/uat/uat_round1.py   # регресс (22 шалгуур)
python -m app.audit.verifier               # AC-17
python -m app.audit.replay --from <өдөр>   # AC-18
```

`uat_round5.py` нь N-1 засагдаагүй байхад `WS_DISCONNECT_LIMIT`-ийг өндөр
утгаар дарж ажиллуулахыг шаардана — энэ нь **оношилгооны тохиргоо**, хүлээн
зөвшөөрөх нөхцөл БИШ.

---

## 9. DEVELOPMENT руу буцаах жагсаалт

1. **N-1** — `stream_trade_updates()` хэрэгжээгүйгээс `ws_disconnect` мөнх
   давталт. Систем `active` болох боломжгүй. (блоклогч)
2. **N-2** — `RequestValidationError` handler нэмж 422-ыг `Problem` схемд
   оруулах.
3. **N-3** — broker-ийн 4xx (401/403) бизнес татгалзлыг `broker_unavailable`
   гэж нэгтгэхгүй, шалтгааныг ил үлдээх (audit-д ч).
4. **O-4** — олон instance-ийн анхны boot дээрх `audit_log seq=1` уралдаан.
5. **O-1/O-2** — `state_body()` доторх breaker probe-ийг унших замаас салгах.
