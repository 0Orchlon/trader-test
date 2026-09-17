<!-- PERSONAL-3 · UAT байршуулалтын тайлан (2-р ажиллалт) · UAT_DEPLOY · 2026-09-18 -->

# PERSONAL-3 — UAT байршуулалтын тайлан (2-р ажиллалт)

Орчин: UAT (энэ machine дээрх Docker daemon, compose project `personal3-uat`).
Энэ ажиллалт нь `uat-deploy-report.md`-д бүртгэгдсэн 1-р байршуулалтаас хойш
орсон савлалтын өөрчлөлтийг (U-1 reverse proxy, `b6d29af`) тусгаж дахин
байршуулав — өмнөх тайланг НЭМЭЛТ баталгаажуулах зорилготой, орлуулахгүй.

## Harbor-тай холбоотой олдвор

`uat-deploy-report.md`-д бүртгэсэнтэй яг адил: энэ репод (`trader-test`,
GitHub, GitLab CI биш) Harbor руу image нийтэлдэг CI pipeline, Dockerfile,
registry credential алга хэвээр — өөрчлөлт гараагүй. Тиймээс DEV-тэй ижил
аргаар (локал build/Docker Hub public image) continue хийсэн.

## Юу шинээр өөрчлөгдсөн (66c528c → HEAD)

`b6d29af` (UAT U-1/U-3 засвар) нь `ci/nginx.conf`-г шинээр нэмж,
`docker-compose.dev.yml`-ийн `frontend` service-д холбосон:
`/api`, `/health`, `/ws` → `${BACKEND}` руу proxy, бусад → `index.html`
(SPA deep link). Энэ бол САВЛАЛТЫН (deployment infra) өөрчлөлт тул энэ
шатанд шалгах ёстой зүйл — код засаагүй, зөвхөн шалгав.

## Амжилттай ажилласан (compose project `personal3-uat`, `docker-compose.dev.yml`)

| Service | Арга | Порт / URL | Health |
|---|---|---|---|
| Postgres 16 | Docker Hub `postgres:16-alpine` | `localhost:25432` | `pg_isready` → accepting connections |
| Redis 7 | Docker Hub `redis:7-alpine` | `localhost:26379` | `redis-cli ping` → `PONG` |
| Frontend | `npm ci --prefer-offline` → `vite build` → `nginx:alpine` + `ci/nginx.conf` (envsubst) | `http://localhost:18080/` | `curl /` → `200`, `curl /approvals` → `200` (SPA fallback), `curl /settings` → `200` |

`frontend/dist` энэ ажиллалтад дахин build хийгдсэн (эх код өөрчлөгдөөгүй,
ижил commit-ийн эх сурвалжаас deterministic гарсан static артефакт).

U-1 reverse proxy (`ci/nginx.conf`) зөв mount, envsubst хийгдэж, deep-link
route (`/approvals`, `/settings`) 404 биш `index.html` руу унаж байгааг
шууд `curl`-аар баталгаажуулав.

## Cache/орчин дутуу тул алгассан (өөрчлөгдөөгүй хязгаарлалт)

- **Backend (`python -m uvicorn app.main:build --factory`)** — DEV болон
  1-р UAT ажиллалттай адил: `pip cache list` дээр зөвхөн `junit_xml`,
  `requirements.lock`-ийн 50+ хамааралт байхгүй; локал Python 3.14.6
  (`>=3.12,<3.13` шаарддаг). VPN/Nexus ирэх хүртэл backend процессыг ямар ч
  орчинд асаах боломжгүй хэвээр.
- `/health` руу `curl` хийхэд `404` буцсан нь backend-ээс БИШ: host дээр
  `:8000` порт дээр энэ ажиллалттай холбоогүй, өмнөх/өөр процессын үлдэгдэл
  `python -m http.server` (`SimpleHTTP/0.6`) сонсож байсныг илрүүлэв. Энэ нь
  манай `nginx` reverse proxy эсвэл backend-ийн гэм биш тул устгаагүй —
  холбогдох хэрэглэгч/процессыг мэдэхгүй байхад хөндөх нь эрсдэлтэй гэж үзэв.

## Дүгнэлт

Дэд бүтэц (Postgres + Redis) болон frontend static + U-1 reverse proxy
UAT-д (`personal3-uat` compose project) DEV-тэй ижил түвшинд ажиллаж,
health болон SPA deep-link шалгагдсан. Backend болон Harbor-based татан
авалт хоёулаа орчны нэг ижил дутагдлаас (Nexus/VPN/Harbor хараахан
холбогдоогүй) шалтгаалан алгассан хэвээр — код эсвэл савлалтын гэм биш.
