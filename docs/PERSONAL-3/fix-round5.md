<!-- PERSONAL-3 · засварын тайлан · Код + тест · 2026-09-17 -->

# UAT 5-р тойргийн засвар — бодит Alpaca trade-update WS, Problem гэрээ

Энэ баримт нь `issue/personal-3` салбарын «Код + тест» шатны гаралт.
Гурван зүйл засав: нэг блоклогч + хоёр нээлттэй ажиглалт (N-2, N-3).

## B-1 (блоклогч) — `stream_trade_updates()` нь бодит WS болов

**Байсан.** `app/broker/alpaca.py` дахь метод `NotImplementedError` шиднэ.
`TradeUpdateIngestor.run_forever()` түүнийг мөнхийн давталтад дуудаж, уналт
бүрт `breaker_events`-д `ws_disconnect` бичдэг. Тоолуур `WS_DISCONNECT_LIMIT`
босгыг хэдхэн минутад давдаг тул `POST /system/activate` үргэлж 409
`breaker_still_tripped` буцаана — байршуулсан систем `halted`-аас **хэзээ ч
гарахгүй**, ямар ч арилжаа хийгдэхгүй. Түүнчлэн fill нь локал `orders`/`fills`
руу огт шингэхгүй тул AC-2 биелэхгүй.

**Болсон.** Alpaca-ийн `/stream` протоколын бүтэн хэрэгжүүлэлт
(`docs.alpaca.markets` «Websocket Streaming»):

1. `wss://{broker_host}/stream` — `broker_host(mode)`-оос, тиймээс live host нь
   `check_egress()`-ээр REST-ийн адил хаагдана (AC-12).
2. `{"action":"auth","key":…,"secret":…}` → `authorization`/`authorized`.
   `unauthorized` бол `BrokerUnavailable` — чимээгүй хүлээх холболт үүсэхгүй.
3. `{"action":"listen","data":{"streams":["trade_updates"]}}`.
4. `{"stream":"trade_updates","data":{…}}` → `map_trade_update()`. paper нь
   frame-ийг **binary**-ээр илгээдэг тул `json.loads` bytes ба str хоёуланг
   уншина.
5. Серверийн `{"action":"error",…}` → `BrokerUnavailable`.

Холболт нь `async with` дотор тул урсгал ямар ч замаар дуусахад socket
хаагдана; `run_forever`-ийн `_close()` нь generator-ыг `aclose()`-оор цэвэрлэнэ.

`websockets==17.1` нь `uvicorn[standard]`-аар дамжин аль хэдийн суудаг байсан —
шинэ хамаарал нэмээгүй, зөвхөн `pyproject.toml`-д ил зарлав (шууд ашиглаж
байгаа тул).

**Тест.** `backend/tests/unit/test_alpaca_stream.py` (6 ш) + регресс
`tests/integration/test_ingest_reconcile.py::test_the_real_adapter_stream_runs_a_clean_cycle_without_a_disconnect`
— бодит `AlpacaAdapter`-ыг `TradeUpdateIngestor`-т залгаж нэг цэвэр мөчлөг
ажиллуулахад `ws_disconnect` мөр **0**, fill нь `orders.status = filled`
болно.

## N-2 — 422 validation хариу нь Problem гэрээг хангана

**Байсан.** FastAPI-ийн анхдагч `RequestValidationError` нь
`{"detail": [...]}` буцаана — `code` талбаргүй. Frontend зөвхөн `code`-оор
салаалдаг (`src/lib/api.ts`) тул кодгүй хариу нь «үл мэдэгдэх алдаа» болж,
operator шалтгааныг харахгүй.

**Болсон.** `app/main.py`-д `RequestValidationError` handler:
`code = invalid_request`, 422, унасан талбар бүр `errors[]`-д
(`{loc, msg}`). **Оролтын утга буцаахгүй** — хүсэлтийн бие нууц агуулж болно
(LLD §14 redaction).

## N-3 — Alpaca-ийн татгалзал ≠ Alpaca-ийн уналт

**Байсан.** `submit_order` нь `httpx.HTTPError` салаа бүрийг
`BrokerUnavailable` болгоно → 503 `broker_unavailable`. Гэтэл Alpaca-ийн 403
(wash trade, buying power) нь broker **хариулсан** гэсэн үг. Гурван гэм:
operator «дахин оролдоод үз» гэсэн худал зөвлөгөө авна; `api_error_rate`
(хүрэхгүй байдлын метрик) татгалзлаар бохирдоно; татгалзал нь
`order_reject_rate`-д огт тоологдохгүй тул дараалсан татгалзал breaker-ийг
хэзээ ч унагаахгүй.

**Болсон.**

| HTTP | Ангилал | Илэрхийлэл |
|---|---|---|
| 400 · 403 · 409 · 422 | арилжааны татгалзал | `BrokerRejected` → 422 `broker_rejected` + `broker_code` |
| 401 · 429 · 5xx · сүлжээ | хүрэхгүй байдал | `BrokerUnavailable` → 503 `broker_unavailable` |

- `BrokerRejected` нь `app/broker/models.py`-д, `BrokerUnavailable`-ээс
  **тусдаа** төрөл (удамшихгүй) — `except BrokerUnavailable` бүхэн түүнийг
  санамсаргүй залгихгүй.
- Татгалзал үед `api_error` нь `ok=True` (broker амьд), харин
  `ExecutionAgent` нь `order_reject` `ok=False` бичнэ.
- `ExecutionAgent._fail()` нь order-ыг `failed` болгож
  `failure_reason = broker_rejected:<alpaca code>` гэж үлдээнэ.

## Гэрээний өөрчлөлт — `openapi.yaml` v1.0.0 → v1.1.0

Зөвхөн НЭМЭЛТ (breaking БИШ):

- `Problem.code` enum: `+ broker_rejected`, `+ invalid_request`.
- `Problem.broker_code` (string, optional) — Alpaca-ийн алдааны код.
- `Problem.errors[] {loc, msg}` (optional) — зөвхөн `invalid_request` үед.

`docs/PERSONAL-3/contracts.yaml` (bundle) ба
`frontend/src/lib/api.generated.ts` дахин үүсгэгдэв.

## Шалгалт

| Гадаргуу | Команд | Үр дүн |
|---|---|---|
| backend | `pytest -q --cov` (Python 3.12.13 + `requirements.lock`) | **377 passed**, coverage gate ногоон |
| contracts | `npm test` | lint ✓ · bundle ✓ · mock 10 зам / 5 дүрэм ✓ |
| frontend | `npm test` | `check:api` ✓ · lint ✓ · typecheck ✓ · **66 passed** |

## Шалгаж чадаагүй

- **Бодит Alpaca WS холболт.** `LiveEgressGuard` нь тестийн явцад гарах
  дуудалтыг хоригложтул протоколыг хуурамч socket-оор шалгав. Хүлээн авсан
  frame-үүд нь Alpaca-ийн баримтын жишээ payload. Бодит handshake нь DEV_TEST
  шатанд paper түлхүүрээр батлагдана.
- Бодит Postgres DDL, browser түвшний assert, 30 хоногийн proving window —
  өмнөх тойргуудын адил энэ шатны хамрах хүрээнээс гадуур.
