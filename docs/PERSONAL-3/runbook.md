<!-- PERSONAL-3 · runbook · CODE_TEST · 2026-09-17 -->

# PERSONAL-3 — Ажиллагааны runbook (T-41)

Энэ баримт нь **гүйцэтгэх заавар**, тайлбар биш. Алхам бүр нь ямар
команд, ямар хариу хүлээхийг ил бичнэ. AC-15-ийн «хүн гараар цэвэрлэх»
нь бичигдсэн журамгүйгээр биелдэггүй — энэ бол тэр журам.

> Хамрах хүрээ: `spec.md` / `lld.md`-ийн шийдвэрүүд эрх бүхий. Энд тэднийг
> ДАВТАХГҮЙ, зөвхөн гүйцэтгэх дарааллыг бичнэ.

---

## 0. Урьдчилсан мэдээлэл

| Зүйл | Утга |
|---|---|
| Бүтэн байршуулалт | репогийн root → `docker compose -f docker-compose.dev.yml up -d --build` |
| Backend | `backend/Dockerfile` (Python 3.12 + `requirements.lock`); эхлэхдээ `python -m app.migrate` өөрөө ажиллана; `:28000` |
| Frontend | `frontend/Dockerfile` — `npm ci && npm run build` нь image ДОТОР, статик нь image-д шатсан; nginx `:18080` |
| Reverse proxy | `ci/nginx.conf` — `/api`, `/health`, `/ws` → backend; бусад → `index.html`. `BACKEND=<host:port>` орчноор дарж бичнэ (анхдагч `backend:8000`) |
| Тохиргоо | `backend/.env` (`.env.example`-ээс). Байхгүй бол backend ЗОРИУД эхлэхгүй (§7-ийн хязгаарууд анхдагчгүй). Alpaca түлхүүр зөвхөн орчноос |
| Төлөвийн эх сурвалж | Postgres-ийн `system_state` хүснэгт (**Redis БИШ**) |
| Хамгийн аюулгүй төлөв | `halted` |

Байршуулалтын ХОЁР дүрэм — хоёулаа UAT-д бодитоор зөрчигдөж байсан:

1. Статикийг ДАНГААР serve хийж болохгүй: UI нь `/api/v1/...` ба `/ws`-ыг нэг
   origin-оос дууддаг тул proxy-гүй байршуулалтад бүх дэлгэц хоосон, deep
   link 404 болно (UAT U-1).
2. `frontend/dist`-ийг **түр зуурын** ажлын хавтаснаас mount ХИЙХГҮЙ (UAT
   U-2) ба backend-гүйгээр proxy-г host дээрх санамсаргүй порт руу ЗААХГҮЙ
   (UAT U-4). Дээрх `docker compose … --build` нь хоёуланг нь бүтцээрээ
   хаадаг: статик image дотор, backend нь compose-ийн service, proxy-ийн
   анхдагч нь тэр service.

Хөгжүүлэлтийн явцад backend-ийг host дээр ажиллуулах бол:
`docker compose -f docker-compose.dev.yml up -d postgres redis` +
`BACKEND=host.docker.internal:8000 docker compose … up -d frontend`.

**Гурван товчийг АНДУУРАХГҮЙ** (LLD §16.3):

| Товч | Юу болох | Буцаах боломж |
|---|---|---|
| **Зогсоо** (улаан, зүүн) | Тэр дор нь `halted`. Асуулт БАЙХГҮЙ. | `Идэвхжүүл` |
| **Унтраах бэлтгэл** (шар, төв) | `winding_down` — agent-ууд позиц ХААХ цонхтой; шинэ эрсдэл нэмэгдэхгүй; grace дуусахад автоматаар `halted` | `Зогсоо` эсвэл grace дуусна |
| **Идэвхжүүл** (ногоон, баруун) | `halted` → `active`. Баталгаажуулалт ЗААВАЛ. | `Зогсоо` |

---

## 1. Машинаа унтраах (төлөвлөгөөт)

Зорилго: agent болон алгоритм ашгаа авч позицоо хааж амжих, шинэ эрсдэл
нэмэхгүй байх.

1. UI → `Унтраах бэлтгэл` дарна. Гарч ирэх асуултыг УНШААД батална.
2. Төлөвийн самбар шар болж, `Позиц хаах цонх · үлдсэн mm:ss` тоолуур гарна.
   - Энэ мөчөөс: **exposure нэмэгдүүлэх бүх order татгалзана** (422
     `winding_down_increase_blocked`), хаах order дамжина.
   - Agent-ууд төлөвийг tool result-ийн `system_state.guidance`-ээс
     ДАРААГИЙН дуудалтдаа мэдэх ба хаах санал гаргана (AC-34).
3. Тоолуур дуусахыг хүлээнэ, эсвэл эрт дуусгахыг хүсвэл `Зогсоо` дарна.
4. Төлөв `ЗОГССОН` (улаан) болсныг харна:
   ```bash
   curl -s localhost:8000/api/v1/system/state | jq '.state, .reason'
   # "halted"  "wind_down_grace_expired"
   ```
5. Одоо л машинаа унтраа.

**Хүлээхгүй зүйл:** систем позицийг АВТОМАТААР хаахгүй (спек A-2). Grace
дууссаны дараа ч байгаа позиц хэвээрээ. Хаалт нь agent / operator-ийн
үйлдэл.

---

## 2. Дахин асаах

1. Backend-ийг эхлүүлнэ. Startup нь төлөвийг **УНШИНА, эхлүүлэхгүй** (AC-37).
2. Төлөв шалгана — `halted` байх ЁСТОЙ:
   ```bash
   curl -s localhost:8000/api/v1/system/state | jq '.state'
   ```
   - Хэрэв `active` гарвал энэ бол **алдаа**. Тэр дор нь `Зогсоо` дараад
     `docs/PERSONAL-3/lld.md` §6.3-ыг зөрчсөн гэж мэдээл.
   - Унтарсан хугацаанд grace дууссан бол `reason` нь
     `grace_expired_while_down`.
3. Арилжааг үргэлжлүүлэхээр шийдвэл §3-ын алхмуудыг дага.

---

## 3. `activate` — арилжааг дахин эхлүүлэх

`halted`-аас гарах **цорын ганц зам**.

1. UI → `Идэвхжүүл`. Эхний дуудалт `409 confirmation_required` буцаана —
   энэ нь алдаа БИШ, урсгалын алхам.
2. Гарч ирэх цонхонд **circuit breaker-ийн ОДООГИЙН хэмжилт** харагдана.
   Хэрэв аль нэг метрик `УНАСАН` гэж бичигдсэн бол §4 рүү оч — энэ товч
   ажиллахгүй.
3. Батална. Төлөв `ИДЭВХТЭЙ` (ногоон) болно.

CLI-аар:
```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/system/activate \
  -H 'Content-Type: application/json' -d '{}' | jq -r '.confirmation.token')
curl -s -X POST localhost:8000/api/v1/system/activate \
  -H 'Content-Type: application/json' -d "{\"confirmation_token\":\"$TOKEN\"}" | jq '.state'
```

⚠ `activate` нь **хадгалагдсан тугийг уншдаггүй** — метрикийг ДАХИН
хэмжинэ. Тиймээс «цэвэрлэсэн» гэж тэмдэглэх замаар тойрох боломжгүй.

---

## 4. Circuit breaker унасан — цэвэрлэх журам

`activate` нь `409 breaker_still_tripped` буцаавал:

### 4.1 Аль метрик унасныг ТОДОРХОЙЛ
```bash
curl -s localhost:8000/api/v1/system/state | jq '.breaker_metrics[] | select(.tripped)'
```

### 4.2 Метрик тус бүрийн үйлдэл

| Метрик | Утга | Хийх зүйл |
|---|---|---|
| `daily_loss` | Өдрийн P&L нь `DAILY_LOSS_LIMIT`-ээс доош | **Өнөөдөр дахин эхлүүлэхгүй.** Шалтгааныг §6-ийн reconstruction-оор шинжил. Дараагийн арилжааны өдөр `last_equity` шинэчлэгдэнэ. |
| `api_error_rate` | Alpaca-ийн алдааны хувь `ERROR_RATE_LIMIT`-ээс их | Alpaca-ийн статус хуудсыг шалга. `curl -s localhost:8000/api/v1/health \| jq '.broker'`. Сэргэсний дараа `BREAKER_WINDOW` секунд хүлээнэ — цонх өнгөрөхөд тоолуур өөрөө цэвэрлэгдэнэ. |
| `order_reject_rate` | Alpaca-ийн татгалзлын хувь их | Татгалзлын шалтгааныг шалга (маржин, PDT, symbol). Хэрэв config-ийн асуудал бол засварыг **deploy**-ээр хийнэ. |
| `ws_disconnects` | Тасалдал `WS_DISCONNECT_LIMIT`-ээс олон | Сүлжээ / proxy шалга. Тогтворжсоны дараа `BREAKER_WINDOW` хүлээнэ. |

### 4.3 «Цонх өнгөрөхийг хүлээх» гэж юу вэ
`api_error_rate`, `order_reject_rate`, `ws_disconnects` нь `BREAKER_WINDOW`
секундын **гулсдаг цонх**. Асуудал зогссоны дараа тэр хугацаа өнгөрөхөд
метрик өөрөө босгоос доош унана. **Гараар тэглэх команд БАЙХГҮЙ** — тийм
команд байвал энэ хаалга утгаа алдана.

### 4.4 Цэвэрлэгдсэнийг батал
```bash
curl -s localhost:8000/api/v1/system/state | jq '[.breaker_metrics[] | select(.tripped)] | length'
# 0
```
Дараа нь §3.

---

## 5. Live рүү promote хийх (хавсралт 06 §5-ийн 5 нөхцөл)

Таван нөхцөл БҮГД хангагдсан байх ёстой. Аль нэг нь дутвал ЗОГС.

- [ ] **1. Paper proving window** — 30+ хоног тасралтгүй цэвэр.
      ```bash
      cd backend && python -c "
      import asyncio
      from app.config.settings import get_settings
      from app.db import init_engine, make_sessionmaker
      from app.system.proving import measure
      async def main():
          engine = init_engine(get_settings().DATABASE_URL)
          async with make_sessionmaker(engine)() as s:
              print((await measure(s)).to_json())
      asyncio.run(main())"
      ```
      `passed: true` байх ёстой. `clean_days < 30` бол ЗОГС.
- [ ] **2. Audit chain бүрэн бүтэн** — `python -m app.audit.verifier` →
      `chain бүрэн бүтэн`.
- [ ] **3. Reconstruction** — §6-ийн алхмууд гүйцэтгэгдэж, тайлан хавсаргагдсан.
- [ ] **4. Live-ийн гурван ил дохио** тохируулагдсан (LLD §17.2):
      `ALPACA_ENV=live`, `LIVE_TRADING_ACKNOWLEDGED=true`,
      `LIVE_CHECKLIST_SIGNATURE=<гарын үсэг>`. Гурвын аль нэг дутвал систем
      эхлэхгүй — энэ нь алдаа биш, хаалга.
- [ ] **5. Хязгаарууд дахин батлагдсан** — `.env`-ийн §7-ийн 10 утга
      operator-ээр шалгагдсан. Эдгээрийг UI-аас засах боломж БАЙХГҮЙ.

Auto-tuning-ийн параметрийг live рүү дэвшүүлэх нь **тусдаа** үйлдэл:
UI → `Авто-тохируулга` → мөр сонгоод `LIVE рүү дэвшүүлэх` →
баталгаажуулалт. Ямар ч модель үүнийг хийж чадахгүй (AC-23).

---

## 6. Audit reconstruction (AC-18)

Арилжааг **зөвхөн логоос** сэргээнэ — `orders`/`fills` хүснэгтэд хүрэхгүй.

```bash
cd backend
python -m app.audit.verifier                 # 1) гинж бүрэн бүтэн үү
python -m app.audit.replay --from 2026-09-01T00:00:00Z > reconstruction.json
jq '.orders[] | {client_order_id, symbol, side, qty, origin, rationale}' reconstruction.json
```

Тайланд байх ЁСТОЙ зүйлс:
- `orders[]` — юу илгээгдсэн, ямар origin-той, ямар горимд;
- `decisions[]` — ямар санал, ямар provider/model, ямар өгөгдөл иш татсан;
- `approvals[]` — хэн зөвшөөрсөн / татгалзсан, шалтгаан нь;
- `state_changes[]` — зогсоолт бүр, шалтгаантайгаа;
- `unknown_events[]` — **хоосон байх ёстой**. Хоосон биш бол replay скрипт
  нь шинэ үйл явдлын төрлийг мэдэхгүй байна (тест үүнийг барих ёстой).

---

## 7. Rollback

1. **Арилжааг ЭХЛЭЭД зогсоо** — UI → `Зогсоо`. Deploy-ийн өмнө биш, ХАМГИЙН
   ТҮРҮҮНД.
2. Позиц хэвээр үлдэнэ. Хаах шаардлагатай бол гараар (`Гарын арилжаа`) —
   rollback нь позиц хаадаггүй.
3. Өмнөх tag руу буцаана:
   ```bash
   git checkout <өмнөх-tag>
   cd backend && pip install -r requirements.lock && pip install -e . --no-deps
   cd ../frontend && npm ci && npm run build
   ```
4. DB migration буцаах шаардлагатай эсэхийг шалга. `audit_log` нь
   append-only — түүнийг ХЭЗЭЭ Ч буцаахгүй.
5. Backend-ийг эхлүүлээд §2 → §3.

---

## 8. Автономи research loop + profit cut (T-99, хувийн төсөл, LLD-д тусгаагүй)

Энэ хэсэг зөвхөн хувийн (компанийн бус) байршуулалтад хамаарна.

### 8.1 Идэвхжүүлэх

`backend/.env`-д:
```bash
ANTHROPIC_API_KEY=sk-ant-...        # Claude-аар мөчлөг ажиллуулах бол
LOCAL_MODEL_URL=http://host.docker.internal:11434/v1/chat/completions  # local бол
LOCAL_MODEL_NAME=llama3.1
RESEARCH_SYMBOLS=AAPL,MSFT,SPY
RESEARCH_INTERVAL_SECONDS=300
```
Хоёулаа хоосон бол `run_research_cycle` job чимээгүй алгасна (эвдрэл БИШ).
`docker compose up -d backend` дараа Provider Switcher (`/providers`) дотор
`local-fc` idний provider харагдана — `research` role-д идэвхжүүлбэл
(эсвэл `claude-mcp` анхдагчаар) тэр мөчлөг тус тус ажиллана. **Систем
`active` төлөвтэй, зах зээл нээлттэй үед л ажиллана** — `halted`/
`winding_down` эсвэл хаалттай зах дээр чимээгүй алгасна.

### 8.2 Хүний оролт БАЙХГҮЙ гэдэг нь юу гэсэн үг вэ

`propose_order`-ийн Risk Agent-ийн ESCALATE_TO_HUMAN (>`MAX_ORDER_NOTIONAL`)
хэвээрээ л мөр үүсгэдэг `/approvals`-д — ГЭХДЭЭ хэн ч дараагүй бол
`APPROVAL_TTL` хугацаанд `expire_approvals` job (30s) автоматаар `expired`
болгож reject хийнэ. Ямар ч гараар дарах алхам ХЭРЭГГҮЙ — энэ бол зогсоох
биш, автомат татгалзал.

### 8.3 Profit cut

```bash
curl -X POST localhost:8000/api/v1/capital/withdraw -d '{"pct": "30"}'
curl localhost:8000/api/v1/capital/summary
```
Alpaca руу ЮУ Ч илгээгдэхгүй — локал ledger. `total_withdrawn`-ийг
`GET /account`-ийн raw equity-ээс ХЭЗЭЭ Ч хасахгүй (AC-1) — зөвхөн Risk
Agent-ийн дараагийн шийдвэр бүрийн `equity`/`last_equity`-г тооцно
(`risk_context.build`). Өөрөөр хэлбэл: 30% авсны дараа R6/R7/R8/R5 бүгд
үлдсэн ~70%-иар тооцоолж эхэлнэ, LLM хэт том санал гаргавал `risk_rejected`
болно — trust-аар БИШ, хатуу дүрмээр хязгаарлагдана.

---

## 9. Өдөр тутмын шалгалт

```bash
curl -s localhost:8000/api/v1/health | jq '{status, broker:.broker.reachable, redis:.redis.reachable}'
curl -s localhost:8000/api/v1/system/state | jq '{state, reason}'
cd backend && python -m app.audit.verifier
```

EOD reconciliation нь 22:00 UTC-д автоматаар ажиллана. Зөрүү гарвал
`audit_log`-д `reconciliation_drift` бичигдэнэ:
```bash
python -m app.audit.replay | jq '.unknown_events, ([.orders[] | select(.failure_reason)] | length)'
```
