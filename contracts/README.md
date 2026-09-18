<!-- PERSONAL-3 · contracts · CONTRACT_PUBLISH · 2026-09-16 -->

# PERSONAL-3 — нийтлэгдсэн гэрээ v1.0.0

Энэ хавтас нь **гэрээний эх сурвалж**. Backend, frontend, Agent Gateway
гурав энэ файлуудаас хөгжинө — хэрэгжүүлэлт эхлэхээс ӨМНӨ гэрээ нь
хувилбартай, дуурайлттай, баримттай болсон байна.

| Файл | Юу | Хувилбар |
|---|---|---|
| `openapi.yaml` | Backend REST API (operator-facing) | OpenAPI 3.1 · `info.version: 1.0.0` |
| `asyncapi.yaml` | WebSocket сувгууд (`/ws`) | AsyncAPI 3.0 · `info.version: 1.0.0` |
| `tool-contract.v1.yaml` | Agent Gateway ↔ ямар ч LLM provider | `contract_version: 1.0.0` |
| `redocly.yaml` | Lint-ийн тохиргоо (хаалтууд ба тэдгээрийн шалтгаан) | — |
| `site/index.html` | Үүсгэсэн гэрээний баримт (REST) | `npm run docs`-оор дахин үүснэ |

`docs/PERSONAL-3/contracts.yaml` нь эдгээрээс **үүсдэг** (Hefesto-д
бүртгэгддэг нэгдсэн хувилбар). Гараар засахгүй — `npm run bundle`.

## Командууд

```bash
npm install
npm run lint         # redocly lint — 0 алдаа, 0 анхааруулга байх ёстой
npm run mock         # prism дуурайлт localhost:4010 дээр (жишээн өгөгдөлтэй)
npm run mock:dynamic # схемээс санамсаргүй өгөгдөл үүсгэх горим
npm run docs         # site/index.html баримтыг дахин үүсгэх
npm test             # lint + bundle шалгалт + дуурайлтын үл хөдлөх дүрмүүд
```

Дуурайлт руу хандах жишээ (session cookie ЗААВАЛ — гэрээ нь auth-ыг
дуурайлт дээр ч шаарддаг):

```bash
curl -s -H 'Cookie: session=mock' http://127.0.0.1:4010/attribution
curl -s -X POST -H 'Cookie: session=mock' http://127.0.0.1:4010/system/wind-down
```

`/system/wind-down` нь `winding_down`, `/kill-switch` нь `halted` төлөв
буцаадаг тул frontend нь backend-гүйгээр төлөвийн машиныг угсарч чадна.

## Хувилбарын бодлого

- `v1.0.0` = энэ commit-оор **царцаасан** гэрээ. Хэрэгжүүлэлтийн шатууд
  (ID 628…677) ЭНЭ хувилбарын эсрэг бичигдэнэ.
- **PATCH** — тайлбар, жишээ, баримт. Талбар нэмэхгүй.
- **MINOR** — нэмэлт талбар / нэмэлт зам (буцаж нийцтэй). Хэрэглэгч тал
  өөрчлөлтгүй ажиллана.
- **MAJOR** — талбар устгах, нэр солих, required болгох, enum-аас утга
  хасах. Гурван давхарга (backend · frontend · Agent Gateway) ЗЭРЭГ
  шинэчлэгдэнэ.
- Tool Contract-ийн `contract_version` нь REST-ээс ТУСДАА хөдөлнө —
  provider adapter-ууд зөвхөн түүнийг хардаг.

## Дуурайлтын үл хөдлөх дүрмүүд (`npm test` шалгана)

1. Хариу бүр `source` · `as_of` · `stale` · `system_state` дугтуйтай.
2. Мөнгө нь `^-?[0-9]+\.[0-9]{2}$` тэмдэгт мөр (float биш) — AC-25.
3. Timestamp бүр UTC `Z` — AC-26.
4. Позиц бүр `origin`-той; «хэн юунд арилжаа хийж байна» нь
   `research_agent` · `manual_operator` · `external` гурвыг тусад нь
   бүлэглэнэ — FR-11, AC-29, AC-30.
5. `wind-down` → `winding_down` + хугацааны хязгаар; `kill-switch` →
   `halted`; гарын order нь `manual_operator` origin ба Risk-ийн шалгалтын
   мөрүүдтэй буцна — FR-12, FR-13, AC-31…AC-37.

## WebSocket сувгууд (AsyncAPI, `asyncapi.yaml`)

| Суваг | Address | Мессеж | Хаягдаж болох уу |
|---|---|---|---|
| `ticks` | `ticks:{symbol}` | `Tick` | Тийм — ачаалалд сүүлийнх нь ялна |
| `orders` | `orders` | `OrderUpdate` | Үгүй — дараалал хадгалагдана |
| `agentDecisions` | `agent-decisions` | `AgentDecision` | Үгүй |
| `system` | `system` | `SystemEvent` (төлөв, breaker, heartbeat) | ХЭЗЭЭ Ч үгүй |

## Tool Contract v1 (`tool-contract.v1.yaml`)

| Tool | Хандалт | Тэмдэглэл |
|---|---|---|
| `get_account` · `get_positions` · `get_quote` · `get_bars` | read | Түүхий broker өгөгдөл, `source`-той |
| `get_backtest_result` · `get_tuning_bounds` | read | Backtest нь `source: backtest` |
| `propose_order` | propose | ЗӨВХӨН санал — Alpaca руу хүрэхгүй (INV-1) |
| `propose_tuning_change` | propose | Bounds дотор, walk-forward нотолгоотой |

`read_only: true` provider-т `propose_*` хоёр схемээс БҮРЭН хасагдана
(INV-5) — татгалзах биш, огт харагдахгүй.

## netos-contract-docs-ийн орлуулалт

Гэрээний баримтыг `netos-contract-docs` (хувийн npm сан) -аар гаргах
төлөвлөгөө байсан. Тухайн сан бүртгэлээс УНШИГДАХГҮЙ байсан тул
(`npm view netos-contract-docs` → 404) даалгаврын зөвшөөрсөн
орлуулалтаар явсан: REST баримт нь `@redocly/cli`-ийн үүсгэсэн статик
HTML (`site/index.html`), AsyncAPI ба Tool Contract нь энэ файлын
Markdown хүснэгтүүд. Сан бүртгэлд гарсан үед `npm run docs`-ийг солиход
хангалттай — гэрээний файлууд өөрчлөгдөхгүй.
