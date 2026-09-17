<!-- PERSONAL-3 · UAT тайлан · UAT_TEST · 2026-09-17 -->

# PERSONAL-3 — UAT тестийн тайлан

**Огноо:** 2026-09-17 · **Commit:** `03b49ba` · **Салбар:** `issue/personal-3`
**Орчин:** локал UAT host (Windows 11) — Postgres 25432, Redis 26379 (Docker
`personal3-uat`), backend `uvicorn app.main:build` :8000 (Python 3.12.13,
`requirements.lock`), frontend `vite preview` :4173 (`npm ci` + `npm run build`).

> Энэ бол **шалгалтын** тайлан: код заваагүй. Илэрсэн зөрчлийг зөвхөн
> тайлагнав (QA-гийн verify-deployment горим).

---

## 1. Нэгдсэн дүн

| Ангилал | Тоо |
|---|---|
| Шалгагдаж ТЭНЦСЭН шалгуур | 21 |
| Илэрсэн зөрчил (N-1) | 1 |
| Ажиглалт (O-1…O-3) | 3 |
| **Шалгагдаагүй** — credential дутсанаас | AC-1, AC-2, AC-5, AC-6, AC-7, AC-8, AC-9, AC-13, AC-18(бодит арилжаа), AC-30, AC-31, AC-32, AC-34, AC-35, AC-36 |

**Дүгнэлт:** байршуулсан хувилбар нь **broker-ээс хамааралгүй** бүх шалгуурыг
хангав. **Арилжааны гол зам (order илгээх, approval, wind-down)
ШАЛГАГДААГҮЙ** — UAT host дээр Alpaca paper API түлхүүр байхгүй тул
`/v2/account`, `/v2/positions` бүгд 503 `broker_unavailable` буцаана.
Үүний улмаас circuit breaker `api_error_rate=1.0000` дээр унасан бөгөөд
`activate` зүй ёсоор татгалзаж, `active`/`winding_down` төлөв рүү орох
боломжгүй. Энэ нь кодын алдаа БИШ, орчны урьдчилсан нөхцөл дутсан.

---

## 2. Тэнцсэн шалгуурууд (баримттай)

| AC | Шалгасан зүйл | Хэмжсэн үр дүн |
|---|---|---|
| AC-12 | paper endpoint анхдагч, live host руу дуудалтгүй | `mode=paper`, `base_url=https://paper-api.alpaca.markets` |
| AC-20 | `source` талбар 200 хариу бүрт | `/health`, `/system/state`, `/orders`, `/agent-decisions`, `/approvals`, `/providers`, `/tuning/parameters` — бүгд `alpaca_paper` |
| AC-21 | горим ил харагдана | `source=alpaca_paper`; build-ийн bundle дотор горимын заалт байгаа |
| AC-37 | restart-ийн дараа төлөв хадгалагдана | backend дахин асаасны дараа `state=halted, reason=initial_deploy` — `active` руу өөрөө БОСООГҮЙ |
| AC-37 | баталгаажуулалтгүй `activate` татгалзана | 409 (`breaker_still_tripped` — баталгаажуулалтаас ӨМНӨ breaker шалгагдана) |
| AC-37 | хуурамч `confirmation_token` татгалзана | 409 |
| AC-15 | breaker унасан үед `activate` татгалзана | 409 `breaker_still_tripped`, `api_error_rate=1.0000 > 0.05`, `ws_disconnects=14 > 5` |
| AC-14 | kill-switch → `halted` 1 сек дотор | WS мэдэгдэл **0.015 s**, дараагийн `/orders/manual` **0.000 s**-д 409 `system_halted` |
| AC-14 | төлөв WS `system` сувгаар түгээгдэнэ | `state_changed` payload хүлээн авсан (`seq`, `ts`, `from`, `to`, `reason`, `changed_by`) |
| AC-14 | **олон instance fan-out (Redis)** | :8000 дээр kill-switch дарахад :8001 instance-ийн WS клиент **0.016 s**-д ижил `seq=13` мессежийг авав; :8001 REST төлөв ч `halted` |
| AC-14 | frontend proxy-оор WS | `ws://127.0.0.1:4173/ws` мөн 0.016 s-д мэдэгдэл авав |
| AC-33 | `halted` үед гарын order бүх зам хаалттай | 409 `system_halted`, «Систем зогссон — шинэ order илгээхгүй», Alpaca руу дуудалт 0 |
| AC-34 | `halted`-аас wind-down руу шилжихгүй | 409 `system_halted` — «зогссон систем wind-down хийхгүй» |
| AC-22 | whitelist/bounds засах endpoint БАЙХГҮЙ | OpenAPI-ийн 21 зам дотор `whitelist\|bounds\|limit\|setting` загвартай mutator зам 0 |
| AC-24 | token-гүй `tuning/promote` татгалзана | 409 `confirmation_required` + `confirmation` объект |
| AC-10 | provider hot-swap restart-гүй | `research: claude-mcp → openai-fc` 200, **0.031 s**, `in_flight_calls=0`; сонсогч process PID өөрчлөгдөөгүй; буцаан солилт бас 200 |
| AC-10 | үл мэдэгдэх provider татгалзана | 422 `provider_unavailable` |
| AC-17 | audit chain бүрэн бүтэн | `python -m app.audit.verifier` → `chain бүрэн бүтэн` |
| AC-18 | лог дээрээс сэргээх зам | `python -m app.audit.replay` → `state_changes=3`, `provider_switches=4`, **`unknown_events=[]`** |
| AC-19 | лог дотор нууц утга алга | backend-ийн 61 мөр лог дээр key/secret pattern-ийн олдоц 0 |
| AC-26 | timestamp бүгд UTC-тэй | `information_schema`: 17 timestamp багана, `timestamp without time zone` = 0; `double precision`/`real` мөнгөн багана = 0 |
| FE | frontend түгээлт + SPA чиглүүлэлт | `/`, `/attribution`, `/ticket`, `/approvals`, `/decisions`, `/providers`, `/tuning`, `/settings` — бүгд 200 |
| FE | `/api` proxy | `http://127.0.0.1:4173/api/v1/health` → 200, `source=alpaca_paper` |
| FE | build-ийн агуулга | bundle дотор `Зогсоо`, `Унтраах бэлтгэл`, `Идэвхжүүл`, `Хэн юунд арилжаа хийж байна`, `Гарын арилжаа`, `origin` мөрүүд байна |

### Өмнөх хяналтын 2 засвар — баталгаажлаа

- **Redis fan-in:** `/health` → `redis.reachable=true`; хоёр instance хооронд
  WS түгээлт 0.016 s-д ажиллав (дээрх AC-14 мөр).
- **`stream_trade_updates()` coroutine never awaited:** backend-ийн 61 мөр
  лог дээр `RuntimeWarning` / `never awaited` / `Task exception` олдсонгүй
  (broker хүрэхгүй байгаа ч гэсэн, яг тэр нөхцөл).

---

## 3. Илэрсэн зөрчил

### N-1 · 422 validation хариу гэрээний `Problem` схемийг зөрчиж байна

**Хаана:** `backend/app/main.py` — `RequestValidationError`-ийн exception
handler байхгүй (зөвхөн `ProblemError`, `BrokerUnavailable`,
`MixedSourceError` баригдсан).

**Гэрээ:** `contracts/openapi.yaml` → `/orders/manual` → `"422"` →
`$ref: "#/components/schemas/Problem"`.

**Бодит хариу:**

```
POST /orders/manual  (Idempotency-Key байхгүй)
422 {"detail":[{"type":"missing","loc":["header","Idempotency-Key"],...}]}

POST /orders/manual  (side="sideways")
422 {"detail":[{"type":"enum","loc":["body","side"],...}]}

POST /tuning/promote {}
422 {"detail":[{"type":"missing","loc":["body","tuning_history_ids"],...}]}

POST /providers/research/switch {}
422 {"detail":[{"type":"missing","loc":["body","provider_id"],...}]}
```

**Яагаад чухал:** `Problem`-ийн `code` талбар дээр салаалдаг клиент
(frontend-ийн алдааны боловсруулалт) эдгээр хариуг `code=undefined` гэж
уншина — «Risk татгалзав» ба «биеийн алдаа» хоёрыг ялгах боломжгүй. Гэрээнд
байгаа хариу нь бодитоор өөр хэлбэртэй байх нь contract тестээр баригдаагүй.

**Хамрах хүрээ:** зөвхөн буруу бүтэцтэй хүсэлт. Аюулгүй байдал, арилжааны
шийдвэрт нөлөөлөхгүй.

---

## 4. Ажиглалт (зогсоох зөрчил биш)

- **O-1 · kill-switch-ийн HTTP хариу 2.56 s.** Төлөв ба WS түгээлт нь
  **0.015 s**-д дуусдаг (AC-14 хангагдсан), гэвч хариуны бие
  `state_body()` → `CircuitBreaker.measure()` → broker-ийн REST probe хийдэг
  тул хүрэхгүй broker дээр хариу 2.5 s хүлээнэ. Operator-ийн нүдэнд улаан
  товч ~2.5 s «өлгөгдсөн» мэт харагдана. Broker эрүүл үед энэ саатал
  байхгүй гэж таамаглаж байгаа ч **энэ орчинд шалгагдаагүй**. Мөн
  `GET /system/state` = 1.56 s.
- **O-2 · `enforce_breaker` job давхцаж алгасагдав.** Лог дээр 3 удаа
  `Execution of job "enforce_breaker" ... skipped: maximum number of running
  instances reached (1)`. Шалтгаан нь O-1-тэй ижил: 5 секундын job нь 1.5+ s
  үргэлжлэх broker probe хийдэг. Broker удаашрах үед breaker-ийн хэмжилт
  сийрэгжинэ.
- **O-3 · `read_only` provider-ыг `research` role-д оноож болдог.**
  `POST /providers/research/switch {"provider_id":"local-fallback"}` → 200,
  анхааруулгагүй. Үүний дараа `any_writable()` худал болж шинэ санал
  гарахаа болино — operator-т ямар ч дохио өгөхгүй. AC-10-ийн зөрчил биш
  (LLD нь fallback-ийг ийм зориулалттай гэж тайлбарласан), гэвч чимээгүй
  чадвар алдалт.

---

## 5. Шалгагдаагүй шалгуур ба шалтгаан

UAT host дээр **Alpaca paper API түлхүүр байхгүй**. `.env`-ийн
`ALPACA_KEY_REF=secretsmanager://p3/alpaca-paper` нь бодит утга руу
шийдэгддэггүй тул broker-ийн бүх REST дуудалт 503 `broker_unavailable`.

| AC | Юуг шалгах ёстой байсан | Яагаад боломжгүй |
|---|---|---|
| AC-1, AC-2 | `/account`, `/positions`, `/orders` нь Alpaca-ийн түүхий утгыг буцаана; dashboard-ийн stale banner | 503 `broker_unavailable` |
| AC-5, AC-6 | Approval queue: босгоос дээш санал → approve/reject, TTL-ийн expire | санал үүсгэх зам broker + LLM шаардана |
| AC-7, AC-8, AC-9 | `grounded_in`, grounding checker, UI дээрх түүхий payload | `agent_decisions` мөр 0 |
| AC-13 | 30 хоногийн paper proving window-ийн 4 метрик | арилжааны түүх байхгүй |
| AC-18 | Alpaca-ийн тайлантай 100% тэнцүү reconstruction | Alpaca-ийн activity тайлан авах боломжгүй (replay-ийн зам өөрөө ажиллаж байгаа) |
| AC-30 | attribution харагдац | `/attribution` → 503 (`/v2/positions` дуудна) |
| AC-31, AC-32 | Гарын order Risk → Execution → Alpaca; `origin=manual_operator` audit | `halted`-аас гарах боломжгүй |
| AC-34, AC-35, AC-36 | wind-down урсгал, эрсдэл нэмэгдүүлэх order-ийн хориг, grace | `activate` нь breaker дээр татгалзана (api_error_rate=1.0) |

**Хэрэгтэй зүйл:** UAT host дээр ажиллах Alpaca **paper** API key/secret
(`ALPACA_API_KEY` / `ALPACA_API_SECRET`, эсвэл `ALPACA_KEY_REF`-ийг
шийддэг secrets manager). Түүнийг олгомогц дээрх 15 AC-ийн тест давтагдана.

---

## 6. Орчны төлөв (тестийн дараа)

- Системийн төлөв `halted` (reason: `UAT fan-out`) — аюулгүй анхны төлөв рүү
  буцаагдсан.
- Provider: `research=claude-mcp` (анхны утга сэргээгдсэн).
- Postgres/Redis контейнер, backend :8000, frontend :4173 ажиллаж байна.
- Хоёр дахь instance (:8001) — тест дууссаны дараа зогсоосон.
