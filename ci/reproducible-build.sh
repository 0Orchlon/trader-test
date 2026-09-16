#!/usr/bin/env bash
# T-40 (ID=667) — давтагдах build-ийн нотолгоо (AC-28).
#
# Нэг commit-оос ХОЁР удаа build хийж артефактын агуулгыг харьцуулна.
# Зөрвөл release унана: «энэ tag дээр яг юу гарсан бэ» гэдэг асуултын
# хариу давтагдахгүй бол audit нь утгагүй.
#
# Хамаарлын pin-ийг `backend/tests/static/test_pinned_dependencies.py`
# барина — энэ скрипт нь ГАРАЛТЫГ л шалгана.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT/frontend"

# Vite-ийн хэш нь агуулгаас гардаг. Цагийн тамга орохоос сэргийлж
# SOURCE_DATE_EPOCH-ийг commit-ийн цагт уяна.
export SOURCE_DATE_EPOCH="$(git log -1 --pretty=%ct)"

hash_dist() {
  # Файлын НЭР + АГУУЛГЫН хэш. Дараалал тогтмол (sort) — файлын системийн
  # дараалал нь build-ийн ялгаа биш.
  find dist -type f -print0 \
    | sort -z \
    | xargs -0 sha256sum \
    | sha256sum \
    | cut -d' ' -f1
}

echo "build #1…"
rm -rf dist
npm run build >/dev/null
FIRST="$(hash_dist)"

echo "build #2…"
rm -rf dist
npm run build >/dev/null
SECOND="$(hash_dist)"

echo "build #1: $FIRST"
echo "build #2: $SECOND"

if [ "$FIRST" != "$SECOND" ]; then
  echo "УНАВ: нэг commit-оос хоёр өөр артефакт гарлаа (AC-28)." >&2
  exit 1
fi

echo "давтагдах build: ногоон — $FIRST"
