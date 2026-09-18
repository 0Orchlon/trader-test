<!-- PERSONAL-3 · ci · CODE_TEST · 2026-09-16 -->

# CI тодорхойлолт

`github-workflow-ci.yml` нь `.github/workflows/ci.yml` болох ЁСТОЙ файл.

**Яагаад энд байна:** энэ салбарыг push хийж буй Personal Access Token-д
`workflow` эрх байхгүй тул `.github/workflows/` доор файл нэмэх нь push-ыг
бүхэлд нь татгалздаг. Тиймээс тодорхойлолтыг энд хадгалж, эрхтэй хүн нэг
удаа зөөнө:

```bash
mkdir -p .github/workflows
cp ci/github-workflow-ci.yml .github/workflows/ci.yml
```

Матриц нь гадаргуу тутам нэг job: `contracts` (`npm test`),
`backend` (`python -m pytest`, coverage gate-тэй), `frontend` (`npm test`).
Гурвуулаа өөрийн хавтас дотор ажиллана — репогийн root дээр нэгтгэсэн
build script БАЙХГҮЙ.
