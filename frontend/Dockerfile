# PERSONAL-3 · frontend image (UAT U-2).
#
# Static-ыг image ДОТОР шатаана. Өмнө нь `frontend/dist` нь host-ийн ажлын
# хавтаснаас bind mount хийгддэг байсан тул тэр хавтас устмагц байршуулсан
# UI бүх замд `500` буцааж байв (U-2, гурван UAT ажиллалтад давтагдсан).
#
# Build context нь РЕПОГИЙН ROOT — `ci/nginx.conf` (reverse proxy, U-1) болон
# `contracts/openapi.yaml` (frontend-ийн `check:api`) хоёулаа root-оос доош.
FROM node:22-alpine AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci --prefer-offline --no-audit --fund=false
COPY contracts ./contracts
COPY frontend ./frontend
RUN cd frontend && npm run build

FROM nginx:alpine
COPY --from=build /src/frontend/dist /usr/share/nginx/html
COPY ci/nginx.conf /etc/nginx/templates/default.conf.template
