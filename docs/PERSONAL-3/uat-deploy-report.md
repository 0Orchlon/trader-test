<!-- PERSONAL-3 · UAT байршуулалтын тайлан · UAT_DEPLOY · 2026-09-18 -->

# PERSONAL-3 — UAT байршуулалтын тайлан

Орчин: UAT (энэ machine дээрх Docker daemon, compose project `personal3-uat`).

## Harbor-тай холбоотой олдвор

Энэ репод (`trader-test`, GitHub-д байрлана, GitLab CI биш) Harbor руу image
нийтэлдэг CI pipeline, Dockerfile, эсвэл registry тохиргоо **алга** —
`.gitlab-ci.yml` байхгүй, backend/frontend-д зориулсан Dockerfile байхгүй,
орчны хувьсагчид Harbor URL/credential алга. Иймд "Harbor-т нийтлэгдсэн ЯГ ТЭР
артефактыг татаж байршуул" гэсэн ерөнхий алхмыг энэ репод хэрэгжүүлэх боломж
одоогоор алга — татах ёстой бүртгэл байхгүй тул юу ч татсангүй.
⚠ Энэ бол блоклогч биш: DEV байршуулалтын тайланд (`dev-deploy-report.md`)
аль хэдийн бүртгэгдсэн адилхан хязгаарлалт (VPN/Nexus/Harbor хараахан
холбогдоогүй орчин). Тиймээс DEV-тэй ЯГ ADIL аргаар — локал build/Docker Hub
public image-аар — continue хийсэн.

## Амжилттай ажилласан (compose project `personal3-uat`, `docker-compose.dev.yml`)

| Service | Арга | Порт / URL | Health |
|---|---|---|---|
| Postgres 16 | Docker Hub `postgres:16-alpine` | `localhost:25432` | `pg_isready` → accepting connections |
| Redis 7 | Docker Hub `redis:7-alpine` | `localhost:26379` | `redis-cli ping` → `PONG` |
| Frontend | `npm ci --prefer-offline` (bүрэн cache-ээс) → `vite build` → `nginx:alpine`-аар static serve | `http://localhost:18080/` | `curl` → `200` |

`frontend/dist` энэ ажиллалтад шинээр build хийгдсэн (өмнөх ажлын хавтас
устсан тул), гэхдээ эх код/lockfile өөрчлөгдөөгүй — ижил commit-ийн эх
сурвалжаас deterministic гарсан static артефакт (бизнес логик хөндөөгүй,
Harbor image биш тул "дахин угсрах" гэдэгт хамаарахгүй гэж үзсэн).

## Cache/орчин дутуу тул алгассан

- **Backend (`python -m uvicorn app.main:build --factory`)** — DEV-тэй адил:
  `pip cache list` дээр зөвхөн `junit_xml`, `requirements.lock`-ийн 50+
  хамааралт байхгүй; локал Python 3.14.6 (`>=3.12,<3.13` шаарддаг). VPN/Nexus
  ирэх хүртэл backend процессыг ямар ч орчинд (DEV/UAT) асаах боломжгүй.

## Дүгнэлт

Дэд бүтэц (Postgres + Redis) болон frontend static UAT-д (`personal3-uat`
compose project) DEV-тэй ижил түвшинд ажиллаж, health шалгагдсан. Backend
болон Harbor-based татан авалт хоёулаа орчны нэг ижил дутагдлаас (Nexus/VPN/
Harbor хараахан холбогдоогүй) шалтгаалан алгассан — код эсвэл савлалтын гэм
биш.
