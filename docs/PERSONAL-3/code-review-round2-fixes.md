<!-- PERSONAL-3 · fixes · CODE+TEST · 2026-09-17 -->

# PERSONAL-3 — 2-р тойргийн хяналтын засвар (CODE+TEST)

**Ажил:** PERSONAL-3 · **Салбар:** `issue/personal-3`
**Оролт:** `docs/PERSONAL-3/code-review-round2.md` (УЛААН — B-1…B-3, N-1…N-5)
**Арга:** шалгуур бүрд ЭХЛЭЭД унадаг тест, дараа нь код.

---

## 1. Зогсоох зөрчлүүд

### B-1 — Холимог origin UI-д огт байхгүй (LLD §16.4, §11.1)

| Юу | Хаана |
|---|---|
| `Attribution.pairs` — symbol дээр fill хийсэн БҮХ `(origin, origin_detail)` хос, сүүлийн fill эхэнд | `backend/app/api/attribution.py` |
| `build_groups()` нь холимог symbol-ыг холбогдох БҮХ бүлэгт гаргана; `SymbolRow.origin_mixed` | `backend/app/api/attribution.py` |
| `/attribution`-ийн мөрөнд `origin_mixed` талбар | `backend/app/api/routes_read.py` |
| Гэрээ: `Position.origin_mixed` (шаардлагатай) + attribution мөрийн `origin_mixed` | `contracts/openapi.yaml` |
| UI: `MixedOriginBadge` — attribution-ийн мөр ба dashboard-ийн позицийн `OriginBadge` | `frontend/src/features/attribution/AttributionPage.tsx`, `DashboardPage.tsx` |

Тест: `test_mixed_symbol_appears_in_every_origin_group`,
`test_single_origin_symbol_is_not_flagged_mixed`, `test_positions_flag_mixed_origin`
(backend); «холимог origin нь БҮХ картад тэмдэгтэй харагдана», «нэг origin-той
symbol дээр холимог тэмдэг ГАРАХГҮЙ» (frontend).

Хянагчийн жишээ (AI 10 ш AAPL + operator 5 ш) одоо хоёр картад гарч, хоёул
«холимог origin» тэмдэгтэй. Позицийн ширхэг/дүн нь давхардана — энэ нь
задаргаа биш «оролцоо» гэсэн утгатай тул тэмдэг заавал хамт явна (гэрээнд
ил бичигдэв). N-5 (гэрээнээс гадуур `origin_mixed`) үүнтэй хамт арилав.

### B-2 — Илгээхээс өмнөх notional нь quote-оос (LLD §16.5)

- Шинэ зам **`GET /market/quote/{symbol}`** (`operationId: getQuote`) —
  `QuoteEnvelope`, envelope-ийн `stale` тугтай. Quote байхгүй бол 503
  `broker_unavailable`; таамагласан үнэ ХЭЗЭЭ Ч буцаахгүй.
- `ManualTicketPage` нь дүнг `qty × quote.last`-аар бодно. `market`/`stop`
  order дээр ч дүн харагдана (`limit_price` талбар идэвхгүй байсан ч).
- Хуучирсан quote нь `quote-stale` тэмдэгтэй; quote огт байхгүй бол дүнгийн
  оронд «quote байхгүй».
- Лавлах үнэ нь Risk-ийн R9-тэй ижил эх сурвалжтай болов.

Тест: `test_get_quote_returns_last_price_with_envelope`,
`test_get_quote_marks_stale_instead_of_hiding_it`,
`test_get_quote_unknown_symbol_is_a_problem_not_a_guess` (backend);
«market order дээр ч дүн харагдана», «хуучирсан quote нь ИЛ тэмдэгтэй»,
«quote байхгүй бол дүн ЗОХИОХГҮЙ» (frontend).

### B-3 — Давтсан гарын order чимээгүй залгигдана

`Idempotency-Key` нь одоо **бие + илгээх ОРОЛДЛОГО**-оос гарна
(`idempotencyKeyFor(body, attempt)`). Оролдлогын тэмдэг нь «Илгээх» товч
дархад шинэчлэгддэг, баталгаажуулалтын хоёр дахь дуудалтад ТОГТМОЛ. Тиймээс:

- баталгаажуулалтын урсгал идемпотент хэвээр (нэг л order);
- ижил маягтыг ДАХИН илгээвэл шинэ key → §9.2-ийн дедуп хуучин order-ыг
  буцаахаа болив → «Хүлээн авав» гэдэг худал баталгаажуулалт арилав.

Backend-ийн дедуп семантик өөрчлөгдөөгүй (LLD §9.2 хэвээр). Тест:
«ижил бие + ШИНЭ оролдлого → ӨӨР key», «ижил маягтыг ДАХИН илгээхэд ӨӨР
Idempotency-Key явна», хуучин «ижил key-тэй баталгаажуулалт» тест хэвээр.

---

## 2. Ажиглалтын засвар

| # | Засвар | Байршил |
|---|---|---|
| N-1 | §16.3-ийн «Унтраах бэлтгэл»-ийн асуултын текст хасагдаж, кодын шийдвэртэй (асуултгүй) нийцэв; §16.4/§16.5-д `origin_mixed`, quote endpoint, idempotency-ийн заалт нэмэгдэв | `docs/PERSONAL-3/lld.md` |
| N-2 | `StateMachine.current(fresh=True)` — TOCTOU шалгалт 200ms кэшийг ТОЙРНО | `app/system/state.py`, `app/execution/agent.py` |
| N-3 | Ажиллаагүй grounding нь `{"passed": false, "not_run": true}`; UI «ажиллаагүй (санал эрт татгалзсан)» гэж ялгаж харуулна; гэрээнд `not_run`/`checked_claims` бүртгэгдэв | `app/agents/tools.py`, `contracts/openapi.yaml`, `DecisionsPage.tsx` |
| N-4 | `requires-python = ">=3.12,<3.13"` — дэмжсэн муж нь бодит (sqlalchemy 2.0.36 нь 3.13+ дээр импортоор унана) | `backend/pyproject.toml` |
| N-5 | B-1-тэй хамт арилав (`origin_mixed` нь гэрээнд) | `contracts/openapi.yaml` |

---

## 3. Хэмжсэн баримт

| Гадаргуу | Команд | Үр дүн |
|---|---|---|
| contracts | `npm test` | ✅ redocly lint + bundle round-trip + дуурайлтын 10 зам |
| backend | `pytest -q --cov=app` (Python 3.12, `requirements.lock`) | ✅ 349 passed, coverage gate ногоон |
| frontend | `npm test` | ✅ `check:api` + eslint + tsc + 60 passed |

## 4. Шалгаагүй хэвээр (ил хамрах хүрээ)

Бодит Postgres DDL (trigger, `FOR UPDATE`), бодит Alpaca, browser түвшний
assert (Playwright), backtest зам, 30 хоногийн paper proving window.
