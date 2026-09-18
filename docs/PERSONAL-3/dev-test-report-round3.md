<!-- PERSONAL-3 · тест тайлан · DEV_TEST (3-р ажиллалт) · 2026-09-18 -->

# DEV тест — 3-р ажиллалт (commit `24b7b14`)

Орчин: DEV compose project `personal3-dev` (`docker-compose.dev.yml`),
backend `:28000`, frontend `:18080`, postgres `:25432`, redis `:26379`.
Alpaca түлхүүр БАЙХГҮЙ — broker-ийн бодит зам шалгагдахгүй (бүтээгдэхүүний
хязгаарлалт, блоклогч биш).

## Хянагчийн 2 саналын амьд баталгаа

| # | Санал | Үр дүн |
|---|---|---|
| R-1 | `build()` нь `settings.REDIS_URL`-ийг EventBus руу дамжуулдаггүй | **Хаагдсан.** `/api/v1/health` → `redis.reachable=true`. Цаашилбал redis дээр `psubscribe "*"` хийхэд kill-switch дарамагц `system` сувагт `{"seq":5,...,"event":"state_changed","_src":"52c2657..."}` бодитоор нийтлэгдэв — өөр процесс EventBus-ийн мессежийг Redis-ээс хүлээн авах боломжтой (AC-14 олон instance). |
| R-2 | `stream_trade_updates()` coroutine never awaited (ingest.py:211) | **Хаагдсан.** Backend-ийн бүх лог дээр `RuntimeWarning` / `never awaited` / `Traceback` илрээгүй. |

## Шалгасан зүйлс (бодит HTTP/WS)

- `GET /api/v1/health` → 200, `status=degraded`, `database.reachable=true`,
  `redis.reachable=true`, `broker.reachable=false` (түлхүүргүй), 4 provider эрүүл.
- `GET /api/v1/system/state` → 200; breaker метрик `api_error_rate=1.0000`
  (босго `0.05`) ба `ws_disconnects=9` (босго `5`) `tripped=true` — босгууд
  тохиргооноос уншигдаж байна.
- Унших REST: `/orders` 200, `/approvals` 200, `/providers` 200,
  `/agent-decisions` 200, `/tuning/parameters` 200 (bounds-той).
  `/account`, `/positions`, `/attribution` → 503 `broker_unavailable` —
  Alpaca байхгүй үед ЗӨВ алдаа, хуурамч утга буцаагаагүй.
- **Горимын заалт (AC-9):** хариу бүрт `source="alpaca_paper"` +
  `as_of` + `stale` + `system_state` талбар бүрэн байв.
- **Kill switch:** `POST /api/v1/kill-switch` → 200, төлөв `halted`,
  шалтгаан хадгалагдав.
- **Halted үед order блоклогдов:** `POST /api/v1/orders/manual` → 409
  `system_halted` («Идэвхжүүлэх нь operator-ийн үйлдэл»).
  Схемийн шалгалт ч ажиллав: UUID биш `Idempotency-Key` → 422.
- **Breaker нь activate-ыг зогсоов:** `POST /api/v1/system/activate` → 409
  `breaker_still_tripped` (метрикүүдийг хариунд ил гаргав).
  `POST /api/v1/system/wind-down` халагдсан төлөвөөс → 409 `system_halted`.
- **Provider hot-swap (restart-гүй):** `POST /api/v1/providers/research/switch`
  → 200, `previous=claude-mcp`, `new=openai-fc`, `in_flight_calls=0`;
  `/providers` → `active.research=openai-fc`. Буцааж соливол дахин 200.
  Байхгүй role (`analysis`) → 422 `provider_unavailable`.
- **WebSocket fan-out:** `ws://backend:8000/ws` — холбогдмогц төлөвийн
  snapshot ирэв, дараа нь kill-switch-ийн `state_changed` push хүрэв.
  Frontend nginx-ээр (`ws://frontend:80/ws`) мөн адил ажиллав — `ci/nginx.conf`-ийн
  upgrade header дамжуулалт бодитоор батлагдав.
- **Frontend:** `/` 200, SPA deep link `/approvals` `/settings` `/activity`
  бүгд 200, `/api/v1/health` proxy 200, `/health` (O-2 засвар) нь `index.html`
  биш backend-ийн health JSON-ыг буцаав.
- **Audit chain:** миний үйлдлээс `audit_log`-д 7 бичлэг үүсэв
  (`state_changed`×5, `provider_switched`×2); `prev_hash` нь өмнөх мөрийн
  `hash`-тай мөр бүрт таарав (seq 2..7) — гинж тасраагүй.
- DB migration: 11 хүснэгт (`orders`, `fills`, `approvals`, `agent_decisions`,
  `tool_calls`, `audit_log`, `breaker_events`, `system_state`, `accounts`,
  `confirmations`, `tuning_history`) байрандаа.

## Шалгаагүй / алгассан

- Alpaca-ийн бодит захиалга, position, EOD reconciliation, market-data WS ingest —
  API түлхүүргүй тул амьд зам ажиллуулах боломжгүй.
- `activate → wind-down → halted` бүтэн E2E — breaker (api_error_rate=1.0,
  broker хүрэхгүйгээс) `activate`-ыг зөв зогсоосон тул амьд орчинд гүйцээгдэхгүй.
  Энэ нь хамгаалалт ажиллаж байгаагийн нотолгоо; үйлдэл нь unit/E2E тестээр
  (ID=677) хаагдсан.

## Цэвэрлэгээ

`docker compose -p personal3-dev -f docker-compose.dev.yml down` — 4 контейнер,
сүлжээ устгагдав; `personal3` нэртэй контейнер үлдээгүй.
