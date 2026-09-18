<!-- PERSONAL-3 · засварын тайлан · DEVELOPMENT · 2026-09-18 -->

# PERSONAL-3 — UAT 4-р ажиллалтын засвар (6-р тойрог)

Суурь: `docs/PERSONAL-3/uat-test-report.md` (commit `9eff2b2`). UAT нь гурван
зөрчил буцаасан: **U-1** (блоклогч, байршуулсан UI backend-д хүрэхгүй),
**U-2** (устсан ажлын хавтас руу mount), **U-3** (provider hot-swap зөвхөн нэг
process-д).

## 1. U-3 — hot-swap бүх instance-д, restart-ыг давна (AC-10)

**Юу байсан.** `ProviderRouter._active` нь process-ийн дотоод dict, ба
`default_router()` үргэлж `{"research": "claude-mcp"}`-ээр эхэлдэг. Тиймээс
`:28000`-д хийсэн солилт `:28001`-д хүрэхгүй, дахин асаахад мартагддаг.
Оператор provider сольсон гэж бодох атлаа хүсэлт аль instance-д унахаас
хамаарч ХУУЧИН модель шийдвэр гаргасаар байв.

**Юу хийсэн** (шинэ хадгалалт, шинэ суваг НЭМЭЭГҮЙ):

| Нэмэлт | Байршил | Үүрэг |
|---|---|---|
| `ProviderRouter.adopt(role, provider_id)` | `app/agents/router.py` | Гаднаас ирсэн солилтыг хэрэгжүүлнэ. Health check ДАХИН хийхгүй (үүсгэсэн instance аль хэдийн шалгасан — дахин шалгах нь нэг үйлдлийн үр дүнг instance бүрд өөр болгоно). Танихгүй provider/role → чимээгүй алгасна. |
| `follow_switches(bus, router)` | `app/agents/router.py`, `_start_background` дотор асна | `system` сувгийн `provider_switched`-ийг сонсоод `adopt` хийнэ. Тээвэр нь байгаа Redis pub/sub (LLD §12, AC-14). Өөрийн мессеж эргэж ирэх нь idempotent. |
| `restore_active(session, router)` | `app/agents/router.py`, lifespan-д дуудагдана | Дахин асаахад `audit_log`-ийн сүүлийн `provider_switched`-ээс идэвхтэйг сэргээнэ. |

**Яагаад тусдаа хүснэгт биш.** Солилт аль хэдийн append-only, hash-chain-тай
`audit_log`-д бичигддэг (LLD §14) — хоёр дахь эх сурвалж нь тэр хоёрыг зөрүүлэх
боломж нээнэ. Түүх хоосон бол анхдагч (`claude-mcp`) хэвээр.

LLD §12.2-т засварыг ил бичив (репо доторх `lld.md`).

**Тест** (эхлээд улаан):

| Тест | Юу барина |
|---|---|
| `tests/unit/test_provider_sync.py::test_switch_on_one_instance_reaches_the_other` | Хоёр bus + хуурамч Redis fan-out: A-д сольсон нь B-ийн `bind("research")`-ыг БОДИТООР солино |
| `…::test_unknown_provider_in_event_leaves_active_untouched` | Өөр тохиргоотой instance-ийн мессеж active-ыг хоослохгүй |
| `…::test_restart_restores_last_switch_from_audit_log` | Хоёр дараалсан солилтоос ХАМГИЙН СҮҮЛИЙНХ сэргэнэ |
| `…::test_restart_without_history_keeps_default` | Түүхгүй бол `claude-mcp` |
| `…::test_unknown_role_is_ignored` | v1-д `research`-аас өөр role байхгүй |
| `tests/integration/test_agents.py::test_switch_survives_a_restart` | REST-ээр сольж, ижил DB дээр app-ыг дахин угсрахад `openai-fc` хэвээр |

Улаан болохыг батлав: `restore_active` дуудлагыг түр хасахад
`test_switch_survives_a_restart` унана; `follow_switches`/`restore_active`
байхгүй үед unit файл импортоор унана.

## 2. U-1 — reverse proxy + SPA fallback (байршуулалтын тохиргоо репод)

`ci/nginx.conf` нэмэв, `docker-compose.dev.yml`-ийн `frontend` service түүнийг
`/etc/nginx/templates/default.conf.template`-ээр авна:

- `/api/`, `/health`, `/ws` → backend (`BACKEND` орчны хувьсагч, анхдагч
  `host.docker.internal:8000`). `NGINX_ENVSUBST_FILTER=BACKEND` — эс бөгөөс
  envsubst нь nginx-ийн `$host`/`$uri`-г ч иднэ.
- `/ws` дээр `Upgrade`/`Connection` header дамжина: WS нь kill switch болон
  breaker-ийн мэдэгдлийн цорын ганц зам (AC-14).
- Бусад зам → `try_files $uri $uri/ /index.html` (deep link `/approvals`).

**Шалгасан** (nginx:alpine, dummy static + dummy upstream):

```
GET /              -> 200
GET /approvals     -> 200   (өмнө 404)
GET /api/v1/health -> 502 upstream байхгүй үед, upstream асаахад 404 нь
                      ТҮҮНЭЭС ирэв (nginx хүргэсэн, өөрөө 404 биш)
```

## 3. U-2 — байршуулалтын журам

Код талын шалтгаан БАЙХГҮЙ: compose нь аль хэдийн харьцангуй зам
(`./frontend/dist`) ашигладаг, зөрчил нь байршуулалтыг устсан `task-293`
хавтаснаас ажиллуулснаас үүссэн. `runbook.md` §0-д ил дүрэм нэмэв: түр
зуурын ажлын хавтаснаас mount хийхгүй.

## 4. Хэмжилт

| Багц | Үр дүн |
|---|---|
| `backend` `pytest -q --cov=app --cov-branch` (Python 3.12.13, `requirements.lock`) | **383 passed**, coverage gate **ногоон** |
| `frontend` `npm test -- --run` | check:api ✓ lint ✓ typecheck ✓ **66 passed** |

## 5. Хамрах хүрээнээс ГАДУУР

- UAT-ийн ажиглалт O-1…O-4 (центийн бөөрөнхийлөлт, equity хөдөлгөөн,
  process тус бүрийн WS `seq`, агент дуудах endpoint байхгүй) — зөрчил гэж
  бүртгэгдээгүй тул хөндөөгүй.
- Backend-ийг контейнерт байршуулах (UAT-ийн 2 дахь хүсэлт) нь DEPLOY шатны
  ажил: энд зөвхөн `BACKEND` хувьсагчаар ийм байршуулалтыг ЗӨВШӨӨРӨХ зам
  нээв (`BACKEND=backend:8000`).
