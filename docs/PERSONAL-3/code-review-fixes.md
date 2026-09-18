<!-- PERSONAL-3 · fix-report · CODE_AND_TEST · 2026-09-17 -->

# PERSONAL-3 — Кодын хяналтын засварын тайлан

**Ажил:** PERSONAL-3 · **Салбар:** `issue/personal-3`
**Хяналтын тайлан:** `docs/PERSONAL-3/code-review.md` (commit `9023ed7`, дүгнэлт УЛААН)
**Засварын хамрах хүрээ:** зогсоох гурван зөрчил B-1…B-3 + долоон ажиглалт N-1…N-7

---

## 1. Зогсоох зөрчлүүд

### B-1 · Төлөвийн шилжилтэд мөрийн lock

`app/system/state.py`:

- `locked_state_stmt()` — `SELECT … ORDER BY seq DESC LIMIT 1 FOR UPDATE`
  (LLD §6.2-ийн 1-р алхам).
- `transition()` нь энэ statement-ээр төлөвийг ДАХИН уншиж, 200ms-ийн
  process-дотоод кэшийг тойрдог болов. Кэш нь зөвхөн `current()`-ийн унших
  замд үлдэв (tool result, envelope) — тэнд хуучирсан утга нь шийдвэр
  гаргадаггүй.

Тест (`tests/unit/test_state_machine.py`):

| Тест | Юу барина |
|---|---|
| `test_transition_reads_the_row_with_for_update` | postgresql диалект дээр компиляц хийхэд `FOR UPDATE` гарна. SQLite нь мөрийн lock дэмждэггүй тул ажиллах тестээр энэ баригдахгүй. |
| `test_transition_ignores_the_read_cache` | Хуучирсан кэш `halted` гэж хэлж байхад DB нь `active` — шилжилт нь DB-г уншиж `already_active` буцаана. |

### B-2 · WS payload ↔ `contracts/asyncapi.yaml`

Кодын тал:

- `EventBus.stamp()` — `seq` + `ts`-ийг НЭГ газраас тамгална. WS-ээр
  bus-гүйгээр шууд явдаг хоёр frame (холболтын snapshot, heartbeat) мөн
  түүгээр дамжина (`app/api/ws.py`).
- `state_changed`: `"type"` → `"event"`, `state` талбар нэмэгдэв.
- `order_event()` (`app/api/serializers.py`) — `order_id`, `status`,
  `origin`, `source` зэрэг шаардлагатай талбарууд ДЭЭД ТҮВШИНД. Гурван
  нийтлэгч (гарын order, approval, trade update) нэг угсрагч ашиглана.
- `DecisionEvent`-д `agent`, `model`, `grounded_in` нэмэгдэв.
- ESCALATE үед `approval_created` нь `system` сувагт нийтлэгдэнэ (LLD §9.4).

Гэрээний тал (`contracts/asyncapi.yaml` → **1.1.0**, зөвхөн НЭМЭЛТ):

- `SystemEvent.event` enum-д `stream_stale`, `stream_live` нэмэгдэв —
  staleness мэдэгдэл аль хэдийн ажиллаж байсан ч enum-д бүртгэлгүй байв.
- `OrderUpdate.order_id` нь `null` байж болох болов: Alpaca UI-аас гараар
  нээсэн order-ийн шинэчлэлт локал мөргүй ирдэг. Локал id ЗОХИОХГҮЙ —
  тэр үед `origin` нь `external` (LLD §11.1).

Хаалга: `tests/asyncapi_schema.py`-ийн `ValidatingEventBus` нь `conftest`-ийн
`bus` fixture-ээр ирдэг тул **API/integration тестийн нийтлэл БҮР** гэрээгээр
шалгагдана. `tests/integration/test_ws_contract.py` нь (а) шалгагч өөрөө
буруу payload-ыг унагадгийг, (б) bus-гүйгээр явдаг хоёр frame-ийг барина.

### B-3 · Coverage gate-ийн хамрах хүрээ

`tests/coverage_gate.py`-ийн `risk` бүлэг нь гурван файл нэрлэхээ болиод
`app/risk/` бүхэлдээ болов. `app/risk/breaker.py`-ийн хэмжигдээгүй гурван
салаанд тест нэмэв (`tests/unit/test_breaker.py`): хүрэхгүй broker,
`last_equity`-гүй данс, унаагүй метрик дээрх `enforce()`.

Одоогийн хэмжилт: `app/risk/**` — **100%** (agent, rules, limits, breaker),
gate ногоон.

---

## 2. Ажиглалтууд

| # | Юу хийсэн | Байршил |
|---|---|---|
| N-1 | RULE (`DO INSTEAD NOTHING` — чимээгүй залгидаг) → `RAISE EXCEPTION` trigger; `BEFORE TRUNCATE` trigger хоёр хүснэгтэд. `REVOKE` нь хоёр дахь давхарга хэвээр. Статик хаалга: `tests/static/test_append_only_sql.py` | `backend/migrations/postgres_append_only.sql` |
| N-2 | Grace дуусах ЯГ агшинд ажиллах `date` job (`schedule_wind_down_deadline`); 10s `interval` sweep нь алдагдсан үеийн нөөц хэвээр | `app/system/scheduler.py`, `app/api/routes_system.py` |
| N-3 | `DAILY_LOSS_LIMIT` нь сөрөг байх validator — эерэг утга нь чимээгүй бүтэн түгжээ үүсгэдэг байв | `app/config/settings.py` |
| N-4 | `orders.decision_id` → `agent_decisions.id`, `orders.approval_id` → `approvals.id` FK болов (хоёулаа `null` байж БОЛНО: гарын order-т шийдвэр байхгүй нь хэвийн) | `app/models.py` |
| N-5 | Нэг хүснэгтэд хоёр `source` гарахыг хориглов: tool call хүснэгтийн шошго мөр бүрээс гарч хүснэгтийн толгойд НЭГ удаа; холимог үед хүснэгт харагдахгүй, ил анхааруулга | `frontend/src/lib/source.ts`, `DecisionsPage.tsx` + тест |
| N-6 | **Шийдвэр:** wind-down нь баталгаажуулалтгүй болов | `frontend/src/app/StateBar.tsx` |
| N-7 | Codegen шалгалт мөрийн төгсгөлийг нормчилдог болов — Windows checkout дээр `npm test` бүхэлдээ ногоон | `frontend/scripts/check-generated.mjs` |

### N-6-ийн шийдвэр (LLD §16.3 vs §8.4)

LLD §8.4 нь баталгаажуулалт шаардах гурван үйлдлийг ил жагсаасан бөгөөд
wind-down тэдний дунд БАЙХГҮЙ; §16.3 нь UI-д бодлогын текст хатуу кодлохыг
хориглоно. Хоёрыг зэрэг хангах ганц зам нь **wind-down-ийн асуултыг
устгах**: тэр нь kill switch-тэй нэг тал дээрх эрсдэл БУУРУУЛАХ үйлдэл
(шинэ эрсдэл нэмэхгүй), буруу дарвал `Идэвхжүүл`-ээр буцна — тэр зам нь
баталгаажуулалттай (AC-37). Ингэснээр UI-д үлдсэн цорын ганц асуулт нь
backend-ийн 409 хариунаас ирнэ.

### N-4-ийн үлдэгдэл (ил хамрах хүрээ)

`orders.account_id` нь `nullable` ХЭВЭЭР: одоогийн урсгалд `accounts` мөрийг
бичих зам байхгүй (данс нь Alpaca-д, локал хуулбар нь `mode` + `key_ref`
хэлбэрээр settings-д). `NOT NULL` болгох нь дансны мөр үүсгэх шинэ бичих
зам шаардах тул энэ засварын хамрах хүрээнээс ГАДУУР. Мөн загварт
байхгүй `filled_qty`, `idempotency_key`, `request_hash`, `failure_reason`
баганууд ба `breaker_events` хүснэгт нь кодод хэвээр — тэдгээрийг LLD §5-д
буцааж бичих нь баримтын шат.

---

## 3. Шалгалт (эмпирик, 2026-09-17)

| Гадаргуу | Команд | Үр дүн |
|---|---|---|
| contracts | `npm test` | lint ✓ · bundle ✓ · дуурайлт 10 зам ✓ |
| backend | `pytest -q --cov=app` (Python 3.12.13) | **342 passed**, coverage gate **ногоон**, `app/risk/**` 100%, нийт 89% |
| frontend | `npm test` (check:api → lint → typecheck → vitest) | бүхэлдээ ногоон, **52 passed** |

## 4. Шалгаж ЧАДААГҮЙ (өөрчлөгдөөгүй)

Хяналтын тайлангийн §5-ийн жагсаалт хүчинтэй хэвээр: Postgres-ийн DDL
(тест SQLite), бодит Alpaca, browser түвшний assert, backtest замууд, 30
хоногийн proving window, `ci/reproducible-build.sh`, 1 секундын хугацааны
төсөв. N-1-ийн шинэ trigger-ууд мөн Postgres дээр ажиллуулж БАТЛААГҮЙ —
агуулгын статик хаалгаар л баригдаж байна.
