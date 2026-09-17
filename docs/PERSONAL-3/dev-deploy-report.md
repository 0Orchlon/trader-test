<!-- PERSONAL-3 · DEV байршуулалтын тайлан · DEV_DEPLOY · 2026-09-17 -->

# PERSONAL-3 — DEV байршуулалтын тайлан

Орчин: локал DEV (VPN/корпорацийн сүлжээгүй — зөвхөн local cache + Docker Hub
public image ашигласан).

## Амжилттай ажилласан

| Service | Арга | Порт / URL | Health |
|---|---|---|---|
| Postgres 16 | Docker Hub `postgres:16-alpine` | `localhost:25432` | `healthy` (`pg_isready`) |
| Redis 7 | Docker Hub `redis:7-alpine` | `localhost:26379` | `healthy` (`redis-cli ping`) |
| Frontend | `npm ci --prefer-offline` (cache-ээс бүрэн шийдэгдсэн) → `npm run build` → `nginx:alpine`-аар static serve | `http://localhost:18080/` | `curl` → `200` |
| Contracts | `npm ci --prefer-offline` (cache-ээс бүрэн шийдэгдсэн, зөвхөн validate зорилготой, тусад нь service болгож асаагаагүй) | — | — |

`docker-compose.dev.yml`-д `frontend` service (Docker Hub `nginx:alpine`,
`./frontend/dist`-ийг зөвхөн-унших volume) нэмэгдсэн — Postgres/Redis-ийн
дэд бүтцийн зэрэгцээ frontend-ийн статикийг мөн адил compose-оор удирдах
боломжтой болгосон. Энэ бол савлалтын (packaging) өөрчлөлт, бизнес логик
хөндөөгүй.

## Cache дутуу тул алгассан

- **Backend (`python -m uvicorn app.main:build --factory`)** — `pip cache list`
  дээр зөвхөн `junit_xml` байсан бөгөөд `requirements.lock`-ийн 50+
  хамааралт бүрэн байхгүй (`asyncpg`, `fastapi`, `sqlalchemy`, `uvicorn`
  гэх мэт). `pip install --no-index` шалгалт бүгдийг «олдсонгүй» гэж
  буцаасан тул backend процессыг DEV-д асаах боломжгүй байлаа.
  ⚠ Энэ нь блоклогч алдаа биш — VPN/Nexus ирэх хүртэлх мэдэгдэж буй
  хязгаарлалт (task-ийн зааврын дагуу).

## Дүгнэлт

Дор хаяж нэг бүлэг (dэд бүтэц: Postgres + Redis, мөн frontend static) DEV
орчинд бүрэн ажиллаж, health шалгагдсан тул энэ алхмыг **амжилттай**
гэж үзнэ. Backend зөвхөн python dependency cache дутуу тул алгассан.
