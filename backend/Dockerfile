# PERSONAL-3 · backend image (UAT U-4).
#
# UAT-д backend огт байршуулагдаагүй шалтгаан нь репод угсрах зам БАЙГААГҮЙ:
# host дээрх Python нь 3.14, төсөл нь `>=3.12,<3.13` шаарддаг. Image нь тэр
# хамаарлыг өөртөө агуулна — host-ийн Python хувилбар хамаарахгүй болно.
#
# Хамаарал нь ЗӨВХӨН `requirements.lock`-оос суудаг (T-1-ийн pin; давтагдах
# build-ийн нөхцөл). `pyproject.toml`-оор суулгавал pin тойрогдоно.
#
# Build context нь РЕПОГИЙН ҮНДЭС (frontend/Dockerfile-тай ижил зарчим,
# docker-compose.yml `context: .`) — `app.agents.contract.load()` нь
# `contracts/tool-contract.v1.yaml`-ыг эхийн эх сурвалж гэж ХАРДАГ бөгөөд
# `./backend` дотор л build context байсан үед энэ файл image-д ОГТ
# ороогүй тул анхны real tool dispatch (research loop) дээр
# `FileNotFoundError` өгч байсныг эндээс олж засав.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY backend/requirements.lock ./
RUN pip install -r requirements.lock

COPY backend/app ./app
COPY backend/migrations ./migrations
COPY contracts /contracts

# Migration нь идемпотент (`app/migrate.py`) — эхлэх бүрд ажиллана, ингэснээр
# байршуулалт нь «схем гараар шинэчил» гэсэн далд алхамгүй болно.
CMD ["sh", "-c", "python -m app.migrate && exec python -m uvicorn app.main:build --factory --host 0.0.0.0 --port 8000"]
