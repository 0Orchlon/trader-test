<!-- PERSONAL-3 · plan · PLAN_TASK · 2026-09-16 -->

# PERSONAL-3 — Alpaca худалдааны системийн хэрэгжүүлэлтийн төлөвлөгөө (v1)

**Ажил:** PERSONAL-3 · **Салбар:** `issue/personal-3` · **Шат:** PLAN_TASK
**Эрх бүхий оролт:** `spec.md` (SPEC шат, commit `b6abb1b`) — AC-1…AC-28
**Хамт гарах баримт:** `tasks.md` (ажлын нэгж T-01…T-41)
**Дараагийн шат:** SPEC_APPROVE (§7 тоон хязгаар + OQ-1…OQ-5), дараа нь LLD

---

## 0. Энэ баримтын хамрах хүрээ

Энэ бол **PLAN_TASK** шатны гарц: батлагдсан спекийг ямар дараалалтай, ямар
milestone-оор, ямар хамаарлын дарааллаар хэрэгжүүлэхийг тодорхойлно.

Энд **БАЙХГҮЙ** зүйл (өөр шатны гарц):
- Модуль, класс, функцийн нарийвчилсан дизайн → `lld.md` (LLD шат)
- Contract-ын эцсийн, хувилбарласан хэлбэр → `contracts.yaml` (CONTRACT_PUBLISH шат)
- Код → DEVELOPMENT шат

Энд шинэ шаардлага **нэмээгүй**. Milestone-ийн гарах шалгуур бүр нь спекийн
AC-г шууд иш татна. Спект байхгүй шалгуур энэ төлөвлөгөөнд ороогүй.

---

## 1. Технологийн шийдэл ба репогийн хэлбэр

Спек §9 A-5-д тогтоосон шийдвэрийг үргэлжлүүлэв (хавсралт 02-оос):

| Хэсэг | Шийдэл |
|---|---|
| Backend | Python 3.12 · FastAPI (async) · uvicorn · `alpaca-py` SDK |
| DB | PostgreSQL (`accounts`, `orders`, `fills`, `agent_decisions`, `tool_calls`, `tuning_history`, `audit_log`) |
| Cache / pub-sub | Redis (tick fan-out, order-status fan-out, rate-limit тоолуур) |
| Хуваарь | APScheduler (EOD reconciliation, auto-tuning цикл) |
| Frontend | React + TypeScript + Vite · TanStack Query · Tailwind · `lightweight-charts` |
| Тест | pytest · Hypothesis · mutmut · testcontainers · Playwright |
| CI | GitHub Actions, гадаргуу тутам job (`backend/`, `frontend/`) |

**Репогийн хэлбэр** — нэг репо, хоёр гадаргуу:

```
backend/            Python 3.12 · FastAPI · pytest       (өөрийн lockfile)
frontend/           React + TS + Vite · Playwright        (өөрийн lockfile)
docs/PERSONAL-3/    spec.md · plan.md · tasks.md + дараагийн шатны баримт
.github/workflows/  ci.yml — matrix: backend, frontend
```

Шалтгаан: backend + frontend нь **нэг хүргэлтийн нэгж** (ганц operator, нэг
deployment, нэг release tag) тул ADR-0003-ийн логикоор нэг репо зөв.

⚠ Энэ репо **netos template БИШ** (`gitlabProjectPath` байхгүй, GitHub репо,
`pom.xml`/`compliance.yaml`/`.gitlab-ci.yml` алга). Тиймээс netos-ийн гадаргууны
хэлбэр (`java-service`/`bff`/`web-app`), `netos-core` parent pin, `compliance.yaml`
waiver механизм энд **хамаарахгүй** — байхгүй платформын дүрэм зохиохгүй.
Хэрэв SPEC_APPROVE-д «netos template дээр гаргана» гэж шийдвэл (OQ-4) энэ бүлэг
болон T-01 дахин бичигдэнэ; бусад task-ууд хүчинтэй хэвээр.

---

## 2. Хэрэгжүүлэлтийн дөрвөн үл хөдлөх зарчим

Доорх дөрөв нь milestone бүрийн code review-ийн байнгын шалгах зүйл. Task-ийн
DoD-д давхардан бичигдсэн ч эдгээр нь **системийн хэмжээний** үүрэг:

1. **LLM-ээс Alpaca-ийн order submit хүрэх зам БАЙХГҮЙ.** `BrokerPort.submit_order`
   зөвхөн Execution модулиас дуудагдана; статик шалгалтаар барина (AC-3).
2. **Хязгаар нь бодлого, код БИШ.** §7-ийн 9 тоо кодод анхдагчаар суухгүй — config-ээс
   ирнэ, тохиргоо дутуу бол систем эхлэхгүй (унтаа анхдагч руу унахгүй).
3. **Live анхдагч болох зам БАЙХГҮЙ.** Live нь ил env flag; тестийн туршид live host
   руу гарсан сүлжээний дуудалт = 0 байхыг network-level assert-аар барина (AC-12).
4. **Тоо бүр гарал үүсэлтэй.** Мөнгө = decimal, timestamp = UTC, өгөгдөлтэй хариу бүр
   `source` талбартай, санал бүр `grounded_in`-тай (AC-7, AC-20, AC-25, AC-26).

---

## 3. Milestone-ууд

Дараалал нь нэг зарчмаар тодорхойлогдов: **аюулгүйн хаалт нь LLM-ээс ӨМНӨ бэлэн
болно.** Research Agent (LLM) M3-д л орж ирнэ — Risk Agent, kill switch,
approval queue M2-д аль хэдийн ажиллаж, тестлэгдсэн байна. Эсрэг дараалал нь
«хараахан хаалтгүй систем дээр AI санал гаргаж байна» гэсэн цонх үүсгэнэ.

### M1 — Суурь ба уншихын бодит байдал
**Task:** T-01 … T-07, T-09, T-29, T-30 (унших хэсэг), T-36
**Гарц:** paper данс холбогдсон, dashboard дээр бодит position/order/equity,
stale banner, mode заалт.
**Гарах шалгуур:** AC-1, AC-2, AC-12, AC-19, AC-20, AC-21, AC-25, AC-26, AC-28
нь CI-д ногоон.
**Энэ milestone-д order илгээх зам НЭЭГДЭХГҮЙ** — T-08 нь M2-т Risk-тэй хамт л
ажиллана.

### M2 — Аюулгүйн хаалт бүрэн
**Task:** T-08, T-10 … T-17, T-31, T-38 (kill/breaker хэсэг)
**Гарц:** Risk Agent (детерминистик, 100% хучилт), Execution Agent, kill switch,
circuit breaker, approval queue — бүгд LLM-гүйгээр, гараар үүсгэсэн саналаар
тестлэгдсэн.
**Гарах шалгуур:** AC-3, AC-4, AC-5, AC-6, AC-14, AC-15, AC-16, AC-27.
**Хаалга:** энэ milestone нь hard stop (хавсралт 08 — 9, 12, 16 дугаар шат).
Risk Agent-ийн mutation testing амьд mutant үлдээвэл M3 эхлэхгүй.

### M3 — AI давхарга: үндэслэлтэй, солигдох
**Task:** T-18 … T-22, T-24, T-32, T-33, T-37
**Гарц:** Tool Contract v1 хөлдсөн, 2 provider adapter, hot-swap, grounding
checker, шийдвэрийн feed түүхий payload-той.
**Гарах шалгуур:** AC-7, AC-8, AC-9, AC-10, AC-11.
**Урьдчилсан нөхцөл:** M2 бүрэн. LLM-ийн `propose_order` нь аль хэдийн байгаа
Risk хаалтад холбогдоно — шинэ зам гаргахгүй.

### M4 — Бүрмөсөн бүртгэл
**Task:** T-23, T-25, T-41
**Гарц:** hash-chained `audit_log`, chain verifier, зөвхөн лог дээрээс арилжаа
сэргээх скрипт, runbook.
**Гарах шалгуур:** AC-17, AC-18, AC-19 (бүтнээр).
**Тэмдэглэл:** T-05 (redaction) ба T-23 (audit writer) нь M1/M2-д аль хэдийн
бичигдэнэ — audit бол дараа нэмэх давхарга биш, бичилтийн зам дээр байх ёстой.
M4 нь түүний **баталгаажуулалт** (verifier, reconstruction).

### M5 — Хязгаартай auto-tuning
**Task:** T-26, T-27, T-28, T-34, T-35
**Гарц:** whitelist + bounds, walk-forward validation, `tuning_history`,
human-gated promote.
**Гарах шалгуур:** AC-22, AC-23, AC-24.
**Эрэмбэ:** хамгийн доор. M5-гүйгээр систем бүрэн ажиллана (хавсралт 09-ийн
дарааллын зөвлөмжтэй тохирно). Хугацаа шахвал энэ milestone хойшилно, бусад нь
хойшлохгүй.

### M6 — Нотолгоо ба live-ийн хаалга
**Task:** T-39, T-40, T-25 (бодит гүйцэтгэл), T-38 (бүтнээр)
**Гарц:** 30+ хоногийн paper proving window тайлан, chaos тестийн үр дүн,
давтагдах build-ийн нотолгоо, audit reconstruction-ийг нэг удаа бүтнээр
гүйцэтгэсэн нотолгоо.
**Гарах шалгуур:** AC-13, AC-18 (гүйцэтгэсэн), AC-28.
**Хаалга:** хавсралт 06 §5-ийн 5 нөхцөл бүгд хангагдтал live flag эргэхгүй.
Paper-ийн 4 метрикийн аль нэг > 0 болвол тоолуур 0-ээс дахин эхэлнэ (AC-13) —
энэ нь календарийн хугацаа биш, **нөхцөлт** хаалга.

---

## 4. Критик зам ба параллель ажил

```
T-01 суурь/CI ─┬─ T-02 DB schema ─┬─ T-06 BrokerPort ─ T-07 read API ─ T-09 WS ─ T-30 dashboard
               │                  │
               ├─ T-03 config/mode┤   T-11 Risk ─ T-12 Risk тест ─ T-13 Execution ─ T-08 submit
               ├─ T-04 Redis      │        │           (T-14 статик хаалт)
               └─ T-05 redaction  └─ T-23 audit writer
                                           ├─ T-15 kill switch ─ T-16 breaker
                                           └─ T-17 approvals ─ T-31 approval UI

T-18 Tool Contract (LLD / CONTRACT_PUBLISH-ийн дараа) ─┬─ T-19 Claude adapter ─┐
                                                       ├─ T-20 OpenAI adapter ─┴─ T-21 router ─ T-33 UI
                                                       └─ T-22 contract / replay тест
T-24 grounding checker ─ T-32 activity log UI
T-26 / T-27 / T-28 auto-tuning ─ T-34 panel
```

**Критик зам:** T-01 → T-02 → T-06 → T-07 → T-11 → T-12 → T-13 → T-17 → T-18 →
T-22 → T-39.

T-39 (proving window) нь календарийн 30+ хоног эзлэх тул критик замын хамгийн
урт хэсэг — тиймээс M6-г хамгийн сүүлд БИШ, M2 дуусмагц **paper дээр гүйлгэж
эхлэх** нь зөв (T-39-ийн тоолуур M3/M5-ийн код өөрчлөлтөөр reset болж
магадгүйг ил ойлгож).

**Параллель боломж:** T-18 (Tool Contract) хөлдмөгц Epic D ба Epic G (frontend)
бие даан ажиллана — хавсралт 08-ийн 7-р шатны (CONTRACT_PUBLISH) гол ашиг тус
нь энэ.

---

## 5. Pipeline шатны харгалзаа (хавсралт 08)

| Шат | Энэ төлөвлөгөөний харгалзаа | Хаалга |
|---|---|---|
| 1 REPO_SETUP | T-01 | pre-commit secret scanner ажиллана, CI skeleton ногоон |
| 2 SPEC | `spec.md` (`b6abb1b`) — бэлэн | — |
| 3 PLAN_TASK | энэ баримт + `tasks.md` | нэгж бүр AC-тай, AC бүр нэгжтэй |
| 4 SPEC_APPROVE | §7-ийн 9 тоо + OQ-1…OQ-5 | **T-11-ийг DEV-д тохируулах урьдчилсан нөхцөл** |
| 5 LLD | `lld.md` — модулийн дизайн | LLM→submit зам байхгүйг дизайн дээр батлах |
| 6 LLD_APPROVE | — | дээрх нэг л зүйл (AC-3) |
| 7 CONTRACT_PUBLISH | T-18-ийн гарц `contracts.yaml` болж хөлдөнө | schema-д `v1` тэмдэг |
| 8 DEVELOPMENT | M1…M5 | task тутмын DoD |
| 9 CODE_REVIEW | §2-ийн 4 зарчим + хавсралт 08-ийн checklist | **hard stop** |
| 10 DEV_DEPLOY | зөвхөн paper endpoint | AC-12 |
| 11 DEV_TEST | T-36-ийн бүх түвшин ногоон | AC-27 |
| 12 DEV_APPROVE | хязгаарын зөрчил 0, барьцаагүй exception 0 | **hard stop** |
| 13 MR_CREATE | MR нь хэрэгжүүлсэн AC-г иш татна; Risk-ийн mutation job ногоон | — |
| 14 UAT_DEPLOY | зөвхөн paper endpoint | AC-12 |
| 15 UAT_TEST | T-38 chaos + T-22 multi-provider; T-39 тоолуур гүйж эхэлнэ | AC-13, AC-15 |
| 16 RELEASE_APPROVAL | зөвхөн live flag эргэх release-д; хавсралт 06 §5 бүтнээр | **hard stop** |
| 17 MERGE | tag + live flag эргэвэл нотолгооны линк release note-д | AC-28 |

---

## 6. Эпик → AC хучилтын матриц

Спек §12-ийн 12 нэгжийг task-ийн эпик болгож дэлгэв. Хучилт хоёр чиглэлд бүрэн:

| Эпик | Task | Хамрах AC |
|---|---|---|
| A — Суурь | T-01…T-05 | AC-7, AC-14, AC-19, AC-20, AC-25, AC-26, AC-28 |
| B — Broker | T-06…T-10 | AC-1, AC-2, AC-3, AC-12, AC-13, AC-20, AC-21, AC-27 |
| C — Risk / Execution | T-11…T-17 | AC-3, AC-4, AC-5, AC-6, AC-14, AC-15, AC-16, AC-27 |
| D — Agent Gateway | T-18…T-22 | AC-3, AC-10, AC-11 |
| E — Compliance / Audit | T-23…T-25 | AC-7, AC-8, AC-17, AC-18 |
| F — Auto-tuning | T-26…T-28 | AC-22, AC-23, AC-24 |
| G — Frontend | T-29…T-35 | AC-2, AC-5, AC-6, AC-9, AC-10, AC-16, AC-21, AC-22, AC-24 |
| H — Тест / QA | T-36…T-40 | AC-2, AC-5, AC-9, AC-13, AC-14, AC-15, AC-27, AC-28 |
| I — Баримт | T-41 | AC-15, AC-18 |

**AC-гүй task:** байхгүй. **Task-гүй AC:** байхгүй (бүрэн матриц `tasks.md` §11-д).

---

## 7. Эрсдэл ба хөнгөвчлөх

| # | Эрсдэл | Хөнгөвчлөх |
|---|---|---|
| R-1 | Risk Agent-ийн 100% line+branch хучилт нь тестийн **чанарыг** батлахгүй | mutation testing (mutmut) нь release-ийн урьдчилсан нөхцөл; амьд mutant = M2 дуусаагүй (T-12) |
| R-2 | Grounding checker-ийг rationale дотор тоог нэрлэхгүй бичиж тойрч болно («мэдэгдэхүйц өссөн») | Adversarial suite (T-24) нь тоогүй үнэлгээний кейсийг тусад нь тэмдэглэнэ. Grounding нь **тооны** баталгаа гэдгийг хавсралт 10 §3 аль хэдийн хязгаарлаж хэлсэн — спекийн хүрээнээс гаргахгүй |
| R-3 | Paper proving window код өөрчлөлт болгонд reset болж, 30 хоног хэзээ ч дуусахгүй | M5-ийг proving window-оос гадна үлдээх; window нь **M2–M4 хөлдсөний дараа** гүйнэ. Reset нөхцөлийг T-39-д ил бичнэ |
| R-4 | Alpaca-ийн rate limit нь WS + polling хамт ажиллахад давагдана | T-09-д Redis дээр rate-limit тоолуур; T-16-ийн error-rate breaker нь давсан тохиолдлыг halt болгоно |
| R-5 | Hot-swap үед нислэгт байсан tool call-ийн attribution алдах | T-21-д adapter reference-ийг session-д bind хийнэ; AC-10 нь яг үүнийг шалгана |
| R-6 | §7-ийн тоо SPEC_APPROVE-д хоцровол M2-ийн DEV_DEPLOY блоклогдоно | T-11-ийн код тоонд хамаарахгүй (config-ээс уншина) тул **бүтээх** ажил блоклогдохгүй; зөвхөн DEV тохиргоо хүлээнэ. Тоо дутуу бол систем эхлэхгүй (§2 зарчим 2) — чимээгүй анхдагч руу унахгүй |
| R-7 | 4 provider adapter бүгдийг бүтээх нь AC-11-ийн шаардлагаас (≥2) их ажил | v1-д Claude + OpenAI хоёрыг бүтээнэ (P-2 таамаг). Grok нь OpenAI-той нийцтэй тул хожим нэмэх нь base URL / auth-ийн ажил; opencode-ыг backlog-д үлдээв |

---

## 8. Ил таамаглалууд (энэ шатны)

Спек §9-ийн A-1…A-6 хүчинтэй хэвээр. Энэ шатанд нэмж тогтоосон:

| # | Таамаг | Үндэслэл | Эсрэг тохиолдол |
|---|---|---|---|
| P-1 | Нэг репо, `backend/` + `frontend/` хоёр гадаргуу | Нэг хүргэлтийн нэгж (ADR-0003-ийн логик); netos template хамаарахгүй (спек A-5) | OQ-4-ийн хариу netos бол T-01 дахин бичигдэнэ |
| P-2 | v1-д **2** provider adapter: Claude (MCP) + OpenAI (function calling) | AC-11 нь «≥2» шаардана; хавсралт 05-д Grok нь OpenAI-той нийцтэй гэж бичсэн тул хожмын нэмэлт нь тохиргооны ажил | OQ-3-ийн хариу «4 бүгд» бол backlog-ийн T-19a (Grok), T-19b (opencode) идэвхжинэ |
| P-3 | Secrets нь v1-д орчны хувьсагчаар инжектлэгдэнэ; тодорхой manager (Doppler / AWS / Vault) нь DEV_DEPLOY-д сонгогдоно | NFR-3 нь зөвхөн «secrets manager» гэж шаардана, брэнд заагаагүй. Орчны хувьсагч нь бүх manager-ийн ерөнхий гаралт тул нэмэлт abstraction шаардахгүй | OQ-5-ийн хариу нь T-03-ийн нэг дэд ажил болно, бусдад хамаарахгүй |
| P-4 | Хэмжээ: **S** ≈ 1 хүн-өдөр, **M** ≈ 2–3, **L** ≈ 4–5 | Хавсралт 09-ийн S/M/L-ийг тоон болгох шаардлагатай байв. Гүйцэтгэгч тодорхой болмогц дахин хэмжинэ | Хэмжээ зөрөх нь AC-ийн хучилтад хамаарахгүй |
| P-5 | Backtest engine нь v1-д Alpaca-ийн историк bar дээр ажиллах **хамгийн бага** хэлбэртэй (walk-forward цонх хуваах + метрик) — тусдаа backtest платформ БИШ | AC-23 нь зөвхөн walk-forward validation-ийг шаардана, стратегийн сан шаардахгүй; хавсралт 04 §5 «bounded local search» | Илүү өргөн backtest хэрэгцээ гарвал шинэ спек шаардана |

---

## 9. Нээлттэй асуулт — энэ шатны байдал

Спек §10-ийн OQ-1…OQ-5 **хариулагдаагүй хэвээр**. Энэ шатны гарцыг тэдгээр
ӨӨРЧЛӨХГҮЙ (дээрх P-1…P-3 таамгаар хаагдсан), тиймээс блоклосонгүй. Гэхдээ:

- **OQ-2 (§7-ийн 9 тоо)** нь **DEV_DEPLOY-ийн хаалга** — код бичихийг блоклохгүй,
  DEV-д гүйлгэхийг блоклоно. SPEC_APPROVE-аас хариу ирэхгүй бол M2-ийн 10-р шат
  тасална.
- **OQ-3** нь backlog-ийн T-19a / T-19b task-ыг идэвхжүүлэх эсэхийг шийднэ.
- **OQ-4** нь T-01-ийн хэлбэрийг (netos эсэх) шийднэ.
- **OQ-1** (kill switch байгаа position-ыг хаах эсэх) нь `lld.md`-ийн kill-switch
  урсгалыг өөрчилнө — **LLD шатны** блоклогч болж магадгүй. Энэ шатанд спекийн
  A-2 таамаг (зөвхөн шинэ order зогсоно) хүчинтэй, AC-16 түүнийг шалгана.

---

## 10. v1-д ХИЙХГҮЙ (спек §3.2-ийг үргэлжлүүлэв)

Доорх нь backlog — энэ төлөвлөгөөний task биш:

- Grok, opencode, local model adapter (P-2; OQ-3-ийн хариунаас хамаарна)
- Хоёр дахь broker adapter (FX) — `BrokerPort` нь боломжийг нээж үлдээнэ,
  хэрэгжүүлэхгүй
- Олон хэрэглэгч / role model (спек A-6)
- Татварын тайлан, нягтлан бодох бүртгэл
- Celery руу шилжих (APScheduler-ээр хүрэлцэхгүй болтол нэмэхгүй)
- Тусдаа backtest платформ (P-5)
