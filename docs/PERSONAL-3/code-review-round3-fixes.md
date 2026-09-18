<!-- PERSONAL-3 · fixes · CODE+TEST · 2026-09-17 -->

# PERSONAL-3 — 3-р тойргийн хяналтын засвар (CODE+TEST)

**Ажил:** PERSONAL-3 · **Салбар:** `issue/personal-3`
**Оролт:** `docs/PERSONAL-3/code-review-round3.md` (УЛААН — B-1, N-1…N-5)
**Арга:** шалгуур бүрд ЭХЛЭЭД унадаг тест, дараа нь код.

---

## 1. Зогсоох зөрчил

### B-1 — `api_error_rate` метрик эх сурвалжгүй атлаа ногоон (LLD §15.2, AC-15, AC-16)

Гурван давхар нэг дор засагдав: тоолуурын эх сурвалж, хэмжигдээгүйн ил
илэрхийлэл, UI-ийн харуулалт.

| Юу | Хаана |
|---|---|
| `AlpacaAdapter.bind_api_reporter(...)` — REST дуудалт БҮРИЙН үр дүн (уншилт, `submit_order`, `cancel_order`). Нэг ЛОГИК дуудалт = нэг мөр; retry-ийн 3 оролдлого нэг л мөр | `backend/app/broker/alpaca.py` |
| `create_app` нь reporter-ыг `breaker_events(kind='api_error')` руу утаслана — хүсэлтийн session-ээс ТУСДАА session (унасан дуудалтын rollback тоолуурыг арчихгүй) | `backend/app/main.py` |
| `_rate()` нь хоосон цонхыг `0.0000` гэж ХЭЛЭХГҮЙ — `unmeasured`, `tripped=false` | `backend/app/risk/breaker.py` |
| Гэрээ: `breaker_metrics[].value` дээр `unmeasured` sentinel ил бичигдэв | `contracts/openapi.yaml` |
| UI: хэмжигдээгүй метрик «ХЭМЖИГДЭЭГҮЙ» (улбар шар), мөр тутам `data-testid` | `frontend/src/app/StateBar.tsx` |
| LLD §15.2-д эх сурвалж ба `unmeasured` дүрэм бичигдэв | `docs/PERSONAL-3/lld.md` |

Тест (эхлээд унасан):
- `tests/unit/test_breaker_api_source.py` — амжилттай уншилт `ok=True`;
  унасан уншилт `ok=False` (нэг мөр); `submit_order`-ийн уналт; хоосон цонх
  `unmeasured`; broker бүрэн унасан үед `api_error_rate` ДАНГААРАА `halted`.
- `tests/integration/test_breaker_api_wiring.py` — prod-ийн ЯГ угсралт
  (`create_app` + `AlpacaAdapter`): `GET /system/state` дуудахад broker
  унасан бол `breaker_events` мөр үүсч, метрик `1.0000 · УНАСАН` болно.
- Frontend: «хэмжигдээгүй метрик нь "хэвийн" гэж харагдахгүй».

Хянагчийн гол сценарио (Alpaca бүрэн унасан) одоо: `daily_loss = unmeasured`,
`api_error_rate = 1.0000 → tripped` → систем `halted`. Самбар ногоон үлдэхгүй.

---

## 2. Ажиглалтууд

| # | Засвар | Хаана | Тест |
|---|---|---|---|
| N-1 | Ticket-ийн лавлах үнэ нь `rules.reference_price`-тай ЯГ ижил дараалалтай: limit үнэ → эс бөгөөс quote-ийн сүүлийн үнэ. Хэрэглэсэн эх сурвалж дэлгэцэд нэрлэгдэнэ | `ManualTicketPage.tsx`, LLD §16.5 | «limit order дээр лавлах үнэ нь LIMIT үнэ» |
| N-2 | `heartbeat` нь query invalidation өдөөхгүй — сул таб минутад 30 `GET /system/state` (тэр бүр нь `get_account`) татахаа болив | `frontend/src/hooks/useSystemState.ts` | `useSystemState.test.tsx` — heartbeat татахгүй, бодит үйл явдал татна |
| N-3 | Market-data WS нь v1-д БАЙХГҮЙ гэдгийг ил бичив: LLD §22-ийн мөр REST quote-оор солигдов, `ticks` суваг «нөөцлөгдсөн, нийтлэгддэггүй» гэж тэмдэглэгдэв. (Alpaca market-data WS хэрэгжүүлэх нь v1-ийн хамрах хүрээнээс гадуур — нүхийг код биш, баримт хаав) | `docs/PERSONAL-3/lld.md`, `contracts/asyncapi.yaml` | — (гэрээний lint) |
| N-4 | `checked_claims` UI-д гарна: «0 тоо шалгав» ба «12 тоо шалгав» ялгарна | `DecisionsPage.tsx` | «шалгасан тооны ТОО харагдана», «шалгасан тоо олон бол мөн ил» |
| N-5 | `approvals`-ийн мөр `SELECT ... FOR UPDATE`-ээр уншигдана (§6.2-ийн төлөвийн машинтай ижил хэв маяг) | `routes_approvals.py::locked_approval_stmt`, LLD §15.3 | `tests/unit/test_approval_lock.py` — Postgres диалект дээр `FOR UPDATE` |

---

## 3. Хэмжилт

| Гадаргуу | Команд | Үр дүн |
|---|---|---|
| backend | `pytest -q --cov` (Python 3.12.13, `requirements.lock`) | **356 passed**, coverage gate ногоон (`app/risk/**` = 100%) |
| frontend | `npm test` (`check:api` + lint + typecheck + vitest) | **66 passed** |
| contracts | `npm test` (redocly lint + `check:bundle` + `verify:mock`) | OK — 10 зам, 5 үл хөдлөх дүрэм |

---

## 4. Хамрах хүрээний ил заалт

- Бодит Postgres дээр `FOR UPDATE` ба append-only trigger ажиллуулж
  БАТЛААГҮЙ (тест SQLite) — компиляцийн шалгалт нь prod-ийн диалект дээрх
  statement-ыг хардаг хэвээр.
- Бодит Alpaca (paper/live) руу сүлжээгээр холбогдоогүй; шинэ тоолуур нь
  `httpx.MockTransport` дээр шалгагдав.
- Playwright түвшний assert, backtest зам, 30 хоногийн proving window нь
  өмнөх тойргуудын нэгэн адил ажиллаагүй.
