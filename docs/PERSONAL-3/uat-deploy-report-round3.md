<!-- PERSONAL-3 · UAT байршуулалтын тайлан (3-р ажиллалт) · UAT_DEPLOY · 2026-09-18 -->

# PERSONAL-3 — UAT байршуулалтын тайлан (3-р ажиллалт, commit `8d8628f`)

Орчин: UAT (энэ machine дээрх Docker daemon, compose project `personal3-uat`).
Энэ ажиллалт нь `6cde1aa` (UAT U-2/U-4 — Dockerfile/compose байршуулах зам
репод нэмэгдсэн) болон `dev-test-report-round3.md`-д амьд баталгаажсан R-1/R-2
засварын дараа хийгдэв — өмнөх 2 UAT байршуулалтыг (`uat-deploy-report.md`,
`-round2.md`) орлохгүй, тэдгээрийн блоклогч (backend байршуулах зам алга)
одоо арилсныг баталгаажуулна.

## Harbor-тай холбоотой олдвор (өөрчлөлт гараагүй)

`fix-round7.md` §4-т аль хэдийн тэмдэглэсэнтэй адил: энэ репод (`trader-test`,
GitHub, GitLab CI биш) Harbor руу image нийтэлдэг CI pipeline, registry
хаяг/credential алга хэвээр. Иймд "Harbor-т нийтлэгдсэн ЯГ ТЭР артефактыг
татаж байршуул" алхмыг үсэг үсэгчлэн хэрэгжүүлэх боломж энэ репод одоогоор
алга — татах ёстой бүртгэл байхгүй. DEV/UAT-ийн өмнөх 3 ажиллалттай ижил
хязгаарлалт тул блоклогч БИШ: `docker compose up -d --build`-аар (репогийн
эх сурвалжаас deterministic image угсарна, U-2/U-4-ийн Dockerfile-ууд) continue
хийв.

## Юу шинээр боломжтой болсон (66c528c/d790a91 → HEAD)

Өмнөх 2 UAT байршуулалтад **backend огт байршуулагдаагүй** (U-4: репод
Dockerfile/compose service алга, host Python 3.14 ≠ `>=3.12,<3.13`). `6cde1aa`
энэ замыг нэмсэн тул энэ удаа **бүх 4 сервис** (Postgres, Redis, backend,
frontend) байршуулагдав.

## Бэлтгэл

- Кожин порт `28000`/`25432` дээр өмнөх (өнөөдрийн DEV_TEST-ийн) орфан
  `uvicorn` процесс хоёр (`PID 37332`, `41508`) сонсож байсныг илрүүлж
  зогсоов — тэдгээр нь энэ байршуулалтын биш, хуучин туршилтын хог.
- `backend/.env` байхгүй байсан тул `backend/.env.example`-ийг хуулав
  (§7-ийн хязгаарууд + `ALPACA_KEY_REF` лавлагаа; бодит түлхүүр орчинд алга,
  `.gitignore`-д `.env` — commit хийгдээгүй).

## Амжилттай ажилласан (`docker compose -p personal3-uat -f docker-compose.dev.yml up -d --build`)

| Service | Арга | Порт | Health |
|---|---|---|---|
| Postgres 16 | `postgres:16-alpine` | `localhost:25432` | `healthy` (compose healthcheck) |
| Redis 7 | `redis:7-alpine` | `localhost:26379` | `healthy` |
| **Backend** (шинэ, U-4) | `backend/Dockerfile` (`python:3.12-slim` + `requirements.lock`, эхлэхдээ `python -m app.migrate`) | `localhost:28000` | `GET /api/v1/health` → `200`, `redis.reachable=true`, `database.reachable=true` |
| Frontend | `frontend/Dockerfile` (image дотор `npm run build`) + `ci/nginx.conf` | `localhost:18080` | `GET /` `200`, `/api/v1/health` (proxy) `200`, `/health` (O-2 зам) `200` JSON, `/approvals` (SPA deep link) `200` |

## Хянагчийн 2 саналын UAT дээрх баталгаа (DEV_TEST 3-р ажиллалтын дараа)

- **R-1** (`REDIS_URL` EventBus-т дамждаггүй): `redis.reachable=true` UAT
  backend-ийн `/api/v1/health`-д — DEV_TEST-тэй ижил.
- **R-2** (unawaited coroutine): `docker compose logs backend`-д
  `RuntimeWarning`/`never awaited`/`Traceback` илрээгүй.

## DB migration

`psql \dt` → 11 хүснэгт (`orders`, `fills`, `approvals`, `agent_decisions`,
`tool_calls`, `audit_log`, `breaker_events`, `system_state`, `accounts`,
`confirmations`, `tuning_history`) — контейнер эхлэхэд `app.migrate`
автоматаар үүсгэв.

## Breaker/kill-switch (Alpaca түлхүүргүй тул хүлээгдэж буй)

`POST /api/v1/system/activate` → `409 breaker_still_tripped`
(`api_error_rate=1.0000` > `0.05`, `ws_disconnects` > `5`) — Alpaca broker
хүрэхгүй үед хамгаалалт зөв ажиллаж байгааг харуулна, код/савлалтын гэм биш.

## Шалгаагүй / алгассан

- Alpaca-ийн бодит захиалга, position — API түлхүүр орчинд алга (DEV/UAT-ийн
  бүх өмнөх ажиллалттай ижил хязгаарлалт).
- Harbor-based image татан авалт — репод registry pipeline тодорхойлогдоогүй
  (дээрх бүлэг).

## Дүгнэлт

UAT-д (`personal3-uat` compose project) энэ удаа **бүх 4 сервис** (Postgres,
Redis, backend, frontend) амжилттай байршуулагдаж, health шалгагдав.
Хянагчийн R-1/R-2 санал UAT орчинд ч амьд баталгаажив. Backend байршуулах
замын блоклогч (U-4, 3 ажиллалт дараалан унасан) `6cde1aa`-гаар хаагдсаныг
энэ ажиллалт бодитоор баталгаажуулав. Стек ажиллаж үлдээв (цэвэрлэгээ
хийгээгүй — UAT орчин).
