<!-- PERSONAL-3 · UAT тайлан · UAT_TEST · 2026-09-17 -->

# PERSONAL-3 — UAT тестийн тайлан (2-р ажиллалт)

**Огноо:** 2026-09-17 · **Commit:** `f771182` · **Салбар:** `issue/personal-3`
**Орчин:** локал UAT host (Windows 11) — Postgres 25432, Redis 26379 (Docker
`personal3-uat`), backend `uvicorn app.main:build` :8000 ба :8001 (Python
3.12.13, `requirements.lock`), frontend `vite preview` :4173
(`npm ci` + `npm run build`).

> Энэ бол **шалгалтын** тайлан: код заваагүй. Илэрсэн зөрчлийг зөвхөн
> тайлагнав (QA-гийн verify-deployment горим).

Энэ ажиллалт нь орчныг **тэглээд шинээр** босгосон (ажлын хавтас өмнөх
даалгаврын дараа устсан): репог дахин clone, Python 3.12 венв дахин
суулгаж, migration ажиллуулж, backend/frontend-ийг дахин асаав. Дараа нь
операторын өгсөн Alpaca paper түлхүүрийг тохируулж, broker-ээс хамаарах
шалгуурыг давтахыг оролдов.

---

## 1. Нэгдсэн дүн

| Ангилал | Тоо |
|---|---|
| Шалгагдаж ТЭНЦСЭН шалгуур | 21 |
| Илэрсэн зөрчил (N-1) | 1 |
| Ажиглалт (O-1…O-4) | 4 |
| **Шалгагдаагүй** — credential хүчингүйгээс | AC-1, AC-2, AC-5, AC-6, AC-7, AC-8, AC-9, AC-13, AC-18(бодит арилжаа), AC-30, AC-31, AC-32, AC-34, AC-35, AC-36 |

**Дүгнэлт:** байршуулсан хувилбар нь **broker-ээс хамааралгүй** бүх шалгуурыг
дахин хангав. **Арилжааны гол зам (order илгээх, approval, grounding,
wind-down) ШАЛГАГДААГҮЙ ХЭВЭЭР** — өгөгдсөн Alpaca түлхүүр нь Alpaca-ийн
`/v2/account` дээр **401 `unauthorized`** буцааж байна (доор §5).

---

## 2. Өгөгдсөн Alpaca credential-ийн шалгалтын үр дүн

Операторын өгсөн утга:

```
ENDPOINT = https://paper-api.alpaca.markets/v2
KEY      = PKQURU6KO464BI67XJAGCJK65C
API      = "PKQURU6KO464BI67XJAGCJK65C"   (KEY-тэй ЯГ ижил мөр)
```

Alpaca-ийн REST нь **хоёр** утга шаарддаг: `APCA-API-KEY-ID` (`PK…`-ээр
эхэлдэг ID) ба `APCA-API-SECRET-KEY` (тусдаа нууц мөр). Өгөгдсөн хоёр мөр
нь ижил тул зөвхөн **key ID** ирсэн, **secret ирээгүй** байна.

Шууд шалгалт (app-аас гадуур, curl):

```
GET https://paper-api.alpaca.markets/v2/account
    APCA-API-KEY-ID: PKQURU6KO464BI67XJAGCJK65C
    APCA-API-SECRET-KEY: PKQURU6KO464BI67XJAGCJK65C
→ 401 {"message": "unauthorized."}
```

App дотуур ижил үр дүн (`.env`-д `ALPACA_API_KEY`/`ALPACA_API_SECRET`
тавьсан):

```
GET /api/v1/account   → 503 broker_unavailable  ("Alpaca хүрэхгүй: /v2/account")
GET /api/v1/positions → 503 broker_unavailable  ("Alpaca хүрэхгүй: /v2/positions")
```

`AlpacaAdapter._read()` нь `raise_for_status()`-ийн `HTTPStatusError`-ийг
`BrokerUnavailable` болгодог тул 401 нь мөн «broker хүрэхгүй» гэж
харагдана (үүнийг O-4 болгон тэмдэглэв).

**Дүгнэлт:** түлхүүр нь бүрэн бус — `api_error_rate` 1.0000 хэвээр, breaker
унасан хэвээр, `active` төлөв рүү орох боломжгүй хэвээр.

---

## 3. Тэнцсэн шалгуурууд (энэ ажиллалтын баримт)

| AC | Шалгасан зүйл | Хэмжсэн үр дүн |
|---|---|---|
| AC-12 | paper endpoint анхдагч, live host руу дуудалтгүй | `source=alpaca_paper`; backend-ийн 63 мөр лог дээр `api.alpaca.markets` (live) 0 удаа |
| AC-20 | `source` талбар 200 хариу бүрт | `/health`, `/system/state`, `/orders`, `/agent-decisions`, `/approvals`, `/providers`, `/tuning/parameters` — бүгд `alpaca_paper` |
| AC-21 | горим ил харагдана | `source=alpaca_paper` бүх хариунд |
| AC-37 | restart-ийн дараа төлөв хадгалагдана | шинэ процесс асаахад `state=halted` — `active` руу ӨӨРӨӨ босоогүй |
| AC-37 | хуурамч `confirmation_token` татгалзана | 409 |
| AC-15 | breaker унасан үед `activate` татгалзана | 409 `breaker_still_tripped`; `api_error_rate=1.0000 > 0.05`, `ws_disconnects=20 > 5` |
| AC-14 | kill-switch → `halted` 1 сек дотор | WS мэдэгдэл **0.000 s** (хэмжилтийн нарийвчлалаас доош), төлөв солигдсон |
| AC-14 | төлөв WS `system` сувгаар түгээгдэнэ | `state_changed` payload (`seq`, `ts`, `from`, `to`, `reason`, `changed_by`) |
| AC-14 | **олон instance fan-out (Redis)** | :8000 дээр kill-switch → :8001 instance-ийн WS клиент **0.000 s**-д `seq=10` авав; :8001-ийн REST төлөв ч `halted` |
| AC-14 | frontend proxy-оор WS | `ws://127.0.0.1:4173/ws` мөн 0.000 s-д ижил `seq=10` авав |
| AC-14 | kill-switch-ийн дараа order зам шууд хаагдана | дараагийн `/orders/manual` **0.000 s**-д 409 `system_halted` |
| AC-33 | `halted` үед гарын order хаалттай | 409 `system_halted` — «Систем зогссон — шинэ order илгээхгүй» |
| AC-34 | `halted`-аас wind-down руу шилжихгүй | 409 `system_halted` — «зогссон систем wind-down хийхгүй» (0.000 s) |
| AC-22 | whitelist/bounds засах endpoint БАЙХГҮЙ | OpenAPI-ийн 21 зам дотор mutator зам **0** |
| AC-24 | token-гүй `tuning/promote` татгалзана | 409 `confirmation_required` |
| AC-10 | provider hot-swap restart-гүй | `research: claude-mcp → openai-fc` 200, **0.016 s**, `in_flight_calls=0`; буцаан солилт ч 200 |
| AC-10 | үл мэдэгдэх provider татгалзана | 422 `provider_unavailable` |
| AC-17 | audit chain бүрэн бүтэн | `python -m app.audit.verifier` → `chain бүрэн бүтэн` |
| AC-18 | лог дээрээс сэргээх зам | `python -m app.audit.replay` → `state_changes`, `provider_switches` бүртгэгдсэн, **`unknown_events=[]`** |
| AC-19 | лог дотор нууц утга алга | `.env`-д бодит key тавьсан үед ч backend-ийн 72 мөр лог дээр key/`APCA-API`/`SECRET` олдоц **0** |
| AC-26 | timestamp бүгд UTC, мөнгө float биш | `information_schema`: 17 timestamp багана, `timestamp without time zone` = 0; `double precision`/`real` = 0; 11 хүснэгт |
| FE | frontend түгээлт + SPA чиглүүлэлт | `/`, `/attribution`, `/ticket`, `/approvals`, `/decisions`, `/providers`, `/tuning`, `/settings` — бүгд 200 |
| FE | `/api` proxy | `http://127.0.0.1:4173/api/v1/health` → 200, `source=alpaca_paper` |

### Репогийн автомат тестүүд (энэ орчинд дахин ажиллуулав)

| Хэрэгсэл | Үр дүн |
|---|---|
| `backend`: `pytest -q` | **358 passed**, 1 warning, 110.47 s |
| `frontend`: `npm test` (`tsc --noEmit` + vitest) | typecheck цэвэр, **66 passed** (6 файл), 57.13 s |

### Өмнөх хяналтын 2 засвар — дахин баталгаажлаа

- **Redis fan-in:** `/health` → `redis.reachable=true` (хоёр instance дээр);
  instance хооронд WS түгээлт ажиллав.
- **`stream_trade_updates()` coroutine never awaited:** 72 мөр лог дээр
  `RuntimeWarning` / `never awaited` / `Task exception` олдсонгүй.

---

## 4. Илэрсэн зөрчил

### N-1 · 422 validation хариу гэрээний `Problem` схемийг зөрчиж байна

**Хаана:** `backend/app/main.py` — `RequestValidationError`-ийн exception
handler байхгүй (зөвхөн `ProblemError`, `BrokerUnavailable`,
`MixedSourceError` баригдсан).

**Гэрээ:** `contracts/openapi.yaml` → `/orders/manual` → `"422"` →
`$ref: "#/components/schemas/Problem"`.

**Бодит хариу (энэ ажиллалтад давтагдав):**

```
POST /orders/manual  (Idempotency-Key байхгүй)
422 {"detail":[{"type":"missing","loc":["header","Idempotency-Key"],"msg":"Field required"}]}
```

Мөн `/tuning/promote`, `/providers/{role}/switch` дээр ижил.

**Яагаад чухал:** `Problem`-ийн `code` талбар дээр салаалдаг клиент эдгээр
хариуг `code=undefined` гэж уншина — «Risk татгалзав» ба «биеийн алдаа»
хоёрыг ялгах боломжгүй.

**Хамрах хүрээ:** зөвхөн буруу бүтэцтэй хүсэлт. Аюулгүй байдал, арилжааны
шийдвэрт нөлөөлөхгүй.

---

## 5. Ажиглалт (зогсоох зөрчил биш)

- **O-1 · `GET /system/state` = 11.56 s.** Өмнөх ажиллалтад 1.56 s байсан
  нь энэ удаа 11.5 s болов: TLS холболт бодитоор үүсч, `_read()`-ийн 3
  оролдлого × хэд хэдэн endpoint нь бүтнээрээ сүлжээгээр явдаг болсон.
  `state_body()` → `CircuitBreaker.measure()` нь broker руу REST probe
  хийдэг тул operator-ийн төлөвийн дэлгэц broker эрүүл бус үед 10+ секунд
  хүлээнэ. Төлөв өөрөө болон WS түгээлт нь саатдаггүй (AC-14 хангагдсан).
- **O-2 · `enforce_breaker` job давхцаж алгасагдана.** Шалтгаан нь O-1-тэй
  ижил — 5 секундын job нь түүнээс урт broker probe хийдэг.
- **O-3 · `read_only` provider-ыг `research` role-д оноож болдог.**
  `POST /providers/research/switch {"provider_id":"local-fallback"}` → 200,
  анхааруулгагүй. Дараа нь шинэ санал гарахаа болино, дохио байхгүй.
- **O-4 · 401/403 нь `broker_unavailable` болж далдардаг.**
  `AlpacaAdapter._read()` нь бүх `httpx.HTTPError`-ийг (түүний дотор
  `HTTPStatusError` 401) `BrokerUnavailable` болгодог. Operator-т
  «сүлжээ тасарсан» ба «түлхүүр буруу» хоёр ижил харагдана — энэ ажиллалтад
  яг тэр нь шалгалтыг удаашруулав (401-ийг зөвхөн app-аас гадуур curl-ээр
  л ялгаж чадсан). Санал: credential алдааг тусад нь кодлох.

---

## 6. Орчны урьдчилсан нөхцөлийн олдвор (энэ host)

- **TLS interception.** Энэ machine дээр гадагшаа HTTPS нь байгууллагын
  proxy-гоор дамжиж, Python/`httpx` нь `certifi`-ийн багцаар шалгахад
  `CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain`
  гэж унадаг (curl нь Windows-ийн сан ашигладаг тул ажилладаг). Backend-ийг
  Windows-ийн үндэс гэрчилгээг экспортолсон PEM рүү заасан
  `SSL_CERT_FILE`-тай ажиллуулж энэ саадыг арилгав. Кодын алдаа БИШ —
  байршуулалтын орчны тохиргоо. Ийм proxy-тай орчинд байршуулах бол
  `SSL_CERT_FILE` (эсвэл `REQUESTS_CA_BUNDLE`) заавал өгөх ёстойг
  runbook-д нэмэх нь зүйтэй.

---

## 7. Шалгагдаагүй шалгуур ба шалтгаан

Alpaca-ийн **paper secret key** байхгүй тул broker-ийн бүх REST дуудалт
401 → `broker_unavailable`.

| AC | Юуг шалгах ёстой байсан | Яагаад боломжгүй |
|---|---|---|
| AC-1, AC-2 | `/account`, `/positions`, `/orders` нь Alpaca-ийн түүхий утгыг буцаана; stale banner | 503 `broker_unavailable` (401) |
| AC-5, AC-6 | Approval queue: босгоос дээш санал → approve/reject, TTL expire | санал үүсгэх зам broker + LLM шаардана |
| AC-7, AC-8, AC-9 | `grounded_in`, grounding checker, UI дээрх түүхий payload | `agent_decisions` мөр 0 |
| AC-13 | 30 хоногийн paper proving window-ийн 4 метрик | арилжааны түүх байхгүй |
| AC-18 | Alpaca-ийн тайлантай 100% тэнцүү reconstruction | Alpaca-ийн activity тайлан авах боломжгүй (replay-ийн зам өөрөө ажиллаж байгаа) |
| AC-30 | attribution харагдац | `/attribution` → 503 (`/v2/positions` дуудна) |
| AC-31, AC-32 | Гарын order Risk → Execution → Alpaca; `origin=manual_operator` audit | `halted`-аас гарах боломжгүй |
| AC-34, AC-35, AC-36 | wind-down урсгал, эрсдэл нэмэгдүүлэх order-ийн хориг, grace | `activate` нь breaker дээр татгалзана (`api_error_rate=1.0`) |

**Хэрэгтэй зүйл:** Alpaca paper API key **хос** —
`ALPACA_API_KEY=PK…` ба `ALPACA_API_SECRET=<40 тэмдэгтийн нууц>`. Хоёр дахь
утга ирмэгц дээрх 15 AC-ийн тест давтагдана (`docs/PERSONAL-3/uat/`-ийн
скриптүүд бэлэн).

---

## 8. Орчны төлөв (тестийн дараа)

- Системийн төлөв `halted` (reason: `UAT fan-out`) — аюулгүй анхны төлөв.
- Provider: `research=claude-mcp` (анхны утга сэргээгдсэн).
- Postgres/Redis контейнер, backend :8000, :8001, frontend :4173 ажиллаж
  байна.
