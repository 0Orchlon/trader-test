<!-- PERSONAL-3 · code-review · CODE_REVIEW (6-р тойрог) · 2026-09-18 -->

# PERSONAL-3 — Кодын хяналт, 6-р тойрог

**Ажил:** PERSONAL-3 · **Салбар:** `issue/personal-3` · **Хянасан commit:** `b6d29af`
**Хэмжүүр:** `docs/PERSONAL-3/lld.md` (LLD v1.0, §19-ийн 15 шалгах цэг),
`docs/PERSONAL-3/contracts.yaml` / `contracts/*.yaml`, `spec.md`-ийн AC.
**Өмнөх тойрог:** `code-review-round5.md` (commit `2e6e825`, ногоон).
**Энэ тойргийн хамрах хүрээ:** `2e6e825..b6d29af` бүрэн (UAT 4-р ажиллалтын
засвар: U-3 provider hot-swap, U-1 reverse proxy, U-2 runbook дүрэм) + §19-ийн
15 цэгийн дахин шалгалт + хянагчийн буцаасан R-1/R-2 хоёрын дахин баталгаа.

> **Хамрах хүрээний гэрээ (LLD §19):** «Энэ загварыг дагасан эсэхийг дараах
> жагсаалтаар л шалгана. Энд байхгүй зүйлээр код буруутгахгүй.» Загварт байгаа
> атлаа алгассан зүйлийг тусад нь (§5) шалгав.

---

## 1. Хэмжилт (энэ тойрогт өөрөө ажиллуулсан)

| Гадаргуу | Команд | Үр дүн |
|---|---|---|
| backend | `pytest -q -rw --cov=app --cov-branch` (Python 3.12.13, шинэ venv, `requirements.lock`) | **383 passed**, 0 failed · TOTAL **90%** · `app/risk/**` 100% |
| backend | `pytest -q -rw` (сэрэмжлүүлгийн жагсаалттай) | **383 passed, 1 warning** — цорын ганц warning нь гуравдагч талынх: `starlette/testclient.py:40 … anyio.abc.BlockingPortal alias is deprecated`. `coroutine … never awaited` БАЙХГҮЙ |
| backend | Шинэ тестийн нотолгоо (mutation) | `ProviderRouter.adopt`-ыг `return False` болгож мутац хийхэд `test_switch_on_one_instance_reaches_the_other`, `test_restart_restores_last_switch_from_audit_log`, `test_switch_survives_a_restart` **унав** (3 failed / 3 passed) — тестүүд зан төлөвт үнэхээр наалдсан, эх кодыг сэргээв |
| contracts | `npm ci && npm test` | `redocly lint` valid · `bundle шалгалт OK` · `дуурайлтын шалгалт OK — 10 зам, 5 үл хөдлөх дүрэм` |
| frontend | `npm ci && npm test -- --run` | `check:api` ✓ · `eslint` ✓ · `tsc --noEmit` ✓ · **66 passed / 6 файл** |
| deploy cfg | `docker run nginx:alpine` дээр `ci/nginx.conf`-ийн template render | `envsubst` зөвхөн `BACKEND`-ийг орлуулж, `$host`/`$uri` бүтэн үлдэв (`proxy_pass http://backend:8000;`, `try_files $uri $uri/ /index.html;`). `nginx -t` нь compose-ийн сүлжээнээс гадуур `host not found in upstream "backend"` гэж унасан — энэ нь хүлээгдсэн (DNS байхгүй), тохиргооны синтаксийн алдаа биш |

Ажлын мод цэвэр, `origin/issue/personal-3` нь `b6d29af` дээр — хянасан код
бодитоор түлхэгдсэн.

---

## 2. Хянагчийн буцаасан хоёр зүйл — дахин баталгаа

| # | Хянагчийн үг | Байдал | Нотолгоо |
|---|---|---|---|
| R-1 | `build()` нь `settings.REDIS_URL`-ийг EventBus-руу дамжуулдаггүй | **Хаагдсан хэвээр** (`03b49ba`) | `app/main.py:216` — `bus = EventBus(redis=_make_redis(settings.REDIS_URL))`; `app/main.py:174-175` — Redis тохируулагдсан үед `bus.bridge()` task болж асна (AC-14-ийн «бүх холбогдсон клиент»); `app/api/routes_read.py:46-56` — health нь бодитоор `ping()` хийнэ, «тохируулсан»-ыг «хүрэх боломжтой» гэж таамаглахгүй |
| R-2 | `app/stream/ingest.py:211` — `stream_trade_updates() coroutine never awaited` | **Хаагдсан хэвээр** (`03b49ba`) | `app/stream/ingest.py:45-59` `_close()` нь `aclose`/`close` хоёуланг барина, `run_forever()`-ийн `finally` (`ingest.py:236-240`) мөчлөг ямар ч замаар дуусахад дуудагдана. Бүтэн багц дээр `-rw`-ээр дахин шалгав — `never awaited` warning гараагүй (§1) |

---

## 3. §19-ийн 15 шалгах цэг (бүгд дахин шалгагдав)

| # | Цэг | Үр дүн | Нотолгоо |
|---|---|---|---|
| 1 | `submit_order`-ийн дуудагч зөвхөн `app/execution` | ✅ | `app/execution/agent.py:89` цорын ганц дуудалт; бусад тохиолдол нь тайлбар. `tests/static/test_import_gates.py` хаалга |
| 2 | `ValidatedOrder` нь Risk-ийн APPROVE салаанаас л | ✅ | `app/risk/agent.py:127` — эх кодод өөр үүсгэлт алга |
| 3 | `orders.origin` NOT NULL, анхдагчгүй | ✅ | `app/models.py:67` (`nullable=False`, default алга) + `ck_orders_origin` шалгалт |
| 4 | `system_state` Postgres-д, startup УНШИНА | ✅ | `app/main.py` lifespan → `machine.ensure_initialised()`, эхлүүлэхгүй |
| 5 | `halted → winding_down` шилжилт кодод байхгүй | ✅ | `app/system/state.py:4` заалт, шилжилтийн хүснэгтэд алга |
| 6 | `activate` нь breaker-ийг ДАХИН хэмжинэ | ✅ | `app/api/routes_system.py:108-123` — `CircuitBreaker(...).tripped()`, хадгалсан туг алга |
| 7 | Гарын order нь `agent_decisions` мөр үүсгэхгүй | ✅ | `app/api/routes_orders.py:210-211` — зөвхөн `origin=MANUAL_OPERATOR`, decision бичилт алга |
| 8 | Position-ийн origin — олдохгүй бол `external` | ✅ | `app/api/attribution.py:67-68` — `origins.get(symbol, EXTERNAL)`, «ойрын» order-т наагдахгүй. Мөн `app/stream/ingest.py` WS payload дээр `known_locally` ил |
| 9 | `tool_calls` бичилт нь LLM-д хариу буцахаас ӨМНӨ | ✅ | `app/agents/gateway.py:137-165` — INSERT+flush → handler → response/latency бичээд commit, дараа нь envelope |
| 10 | Tool result бүрд `system_state`, schema-д `required` | ✅ | `contracts/tool-contract.v1.yaml:35` — `required: [tool_call_id, timestamp, source, system_state, ok]` |
| 11 | Grounding унавал Risk хүртэл очихгүй | ✅ | `app/agents/tools.py:330-345` — `passed=false` бол `grounding_failed`-аар буцна; `evaluate()` нь :353 дээр, дараа нь |
| 12 | `audit_log` дээр UPDATE/DELETE татгалзах trigger | ✅ | `backend/migrations/postgres_append_only.sql` — UPDATE/DELETE/TRUNCATE гурвуулаа `RAISE EXCEPTION` |
| 13 | §7-ийн хязгаарууд кодод анхдагчгүй | ✅ | `app/risk/limits.py` — `RiskLimits` дээр default талбар алга, `from_settings` л дүүргэнэ |
| 14 | Нэг хүснэгтэд хоёр `source` зэрэг харагдахгүй | ✅ | Backend `MixedSourceError` → 500 (`app/main.py`), frontend `ModeBanner` нь `source`-оос л уншина (`src/app/ModeBanner.tsx`), `StateBar.test.tsx` хаалга |
| 15 | Settings дэлгэцэд хязгаар засах талбар байхгүй | ✅ | `src/features/settings/SettingsPage.tsx` — `<input>`/`onChange` огт алга |

---

## 4. Энэ тойргийн өөрчлөлт — загвартай тулгасан дүгнэлт

### 4.1 U-3 — provider hot-swap бүх instance-д, restart-ыг давна

| Шалгасан зүйл | Дүгнэлт |
|---|---|
| `ProviderRouter.adopt()` (`app/agents/router.py:154-166`) | `switch()`-ийн төлөвийн нөлөө нь ганц заалт (`self._active[role] = provider_id`) — `adopt()` ЯГ түүнийг давтаж, health check ба `SwitchResult`-ийн бүртгэлийг л орхиж байна. Өөр далд төлөв хуваалцахгүй тул instance-ууд зөрөхгүй. Танихгүй role/provider → `False`, active хэвээр. LLD §12.2-ийн «atomic reference swap»-тай нийцнэ |
| `follow_switches()` (`router.py:189-211`) | `system` сувгийг сонсоод `provider_switched`-ийг буулгана. **Шинэ тээвэр нэмээгүй** — LLD §12-ийн Redis pub/sub-ыг ашигласан нь загварын гаднах хоёр дахь суваг үүсгээгүй гэсэн үг. `finally: bus.unsubscribe(sub)` — таслагдахад захиалга үлдэхгүй. `_start_background`-д task болж асдаг тул зөвхөн prod (`background=True`) замд ажиллана, тест цаг хамааралгүй хэвээр |
| `restore_active()` (`router.py:218-246`) | `audit_log`-оос сэргээнэ. Query нь `event_type == 'provider_switched'` дээр шүүж, `seq` буурахаар 200 мөр авдаг тул бусад үйл явдал шахаж гаргахгүй. Role бүрийн ХАМГИЙН СҮҮЛИЙНХ ялна (`seen` олонлог). LLD §14-ийн append-only, hash-chain аудитыг эрх бүхий эх сурвалж болгосон нь зөв — хоёр дахь хүснэгт нь зөрүү үүсгэх байсан |
| Гэрээ | `system` сувгийн `SystemEvent` (`contracts/asyncapi.yaml:160-176`) нь `provider_switched`-ийг enum-д агуулсан, `additionalProperties` хаагаагүй тул `role`/`new_provider_id` талбар гэрээ зөрчихгүй |
| Нислэг дунд байгаа дуудалт | `bind()` нь session эхлэхэд лавлагааг атгах загвар өөрчлөгдөөгүй (§12.2) — `adopt` нь зөвхөн `_active`-ыг хөндөнө |
| LLD шинэчлэлт | §12.2-т засвар ил бичигдсэн (`lld.md:726-741`) — код ба загвар зөрөөгүй |

### 4.2 U-1 — `ci/nginx.conf` + compose

`/api/`, `/health`, `/ws` → backend; бусад → `index.html`. `/ws` дээр
`Upgrade`/`Connection` дамжина (AC-14-ийн мэдэгдлийн цорын ганц зам).
`NGINX_ENVSUBST_FILTER=BACKEND` нь nginx-ийн өөрийн хувьсагчдыг хамгаалсныг
контейнерт бодитоор шалгав (§1). Энэ нь LLD-д тодорхойлогдоогүй байршуулалтын
тохиргоо — загвар зөрчөөгүй, runbook-д баримтжсан.

### 4.3 U-2 — runbook §0

Түр зуурын хавтаснаас mount хийхгүй дүрэм нэмэгдсэн. Код талын өөрчлөлт
шаардаагүй нь зөв дүгнэлт (compose нь харьцангуй зам ашиглана).

---

## 5. «Загварт байгаа атлаа алгассан» шалгалт

- §12.3 **Fallback бодлого** — `ProviderRouter.record_error()` нь fallback руу
  шилжих логиктой боловч түүнийг дуудах **үйлдвэрлэлийн дуудагч алга**: эх
  кодод дуудалт зөвхөн `tests/`-д байна (`tests/integration/test_agents.py`,
  `tests/adversarial/test_chaos.py`). Загварын §12.1 нь урсгалыг `LLM → adapter
  → gateway.dispatch` (ирэх чиглэл) гэж тодорхойлсон тул process өөрөө
  provider-ийн уналтыг хэмжих цэггүй байгаа нь энэ архитектурын шууд үр дагавар.
  §19-ийн жагсаалтад ороогүй, AC-11 нь schema тэнцүүг шаарддаг (auto-fallback-
  ийг биш) тул **блоклогч биш**, гэвч дараагийн давталтад ил шийдэх ёстой
  цоорхой (доорх O-1).
- Бусад §19-ийн элемент бүрийн хэрэгжилт §3-т нотлогдов.

---

## 6. Ажиглалт (блоклогч БИШ)

| # | Ажиглалт | Санал |
|---|---|---|
| O-1 | §12.3 fallback нь зөвхөн тестээр хөдөлдөг — `record_error` дуудагч үйлдвэрлэлийн замд алга | Gateway-ийн `dispatch` дээр provider-ийн алдааг бүртгэх, эсвэл §12.3-ыг «operator гараар» гэж загварт нарийвчлах. Аль нэгийг сонгож ил бичих |
| O-2 | `restore_active` нь хамгийн сүүлийн солилтын provider энэ process-д тохируулагдаагүй бол чимээгүйгээр НЭГ ҮЕИЙН ӨМНӨХ солилт руу унана | Тохиргоо бүх instance-д ижил байх нь `default_router()`-оор баталгаажсан тул одоогоор эрсдэлгүй; провайдерын жагсаалт орчноос ирдэг болвол сэрэмжлүүлэг лог нэмэх |
| O-3 | `docker-compose.dev.yml`-ийн `frontend` дээр `depends_on` алга. nginx нь upstream host-ыг эхлэхдээ шийддэг тул `BACKEND=backend:8000` гэж дарж бичсэн үед backend хараахан байхгүй бол nginx **эхлэхээс татгалзана** (502 биш) | `depends_on: [backend]` эсвэл `resolver` + хувьсагчтай `proxy_pass`. DEPLOY шатны ажил |
| O-4 | `location /health` нь префикс тааралт тул `/healthz`, `/healthcheck`-ийг БАС дамжуулна | `location = /health` болговол нарийсна. Одоо backend-д өөр `/health*` зам байхгүй тул нөлөөгүй |
| O-5 | `follow_switches`-ийн subscriber нь `system` сувагт хязгааргүй дараалалтай (зориудаар, §12 backpressure бодлого). Task нь гэнэтийн exception-оор унавал дараалал хуримтлагдана | `while True` доторх `adopt` нь зөвхөн dict үйлдэл тул одоогоор боломжгүй; ирээдүйд логик нэмэгдвэл `try/except` хүрээлэл |

---

## 7. Энэ тойрогт ШАЛГААГҮЙ зүйлс (ногоон гэж тооцогдохгүй)

- **Бодит Alpaca `/stream` холболт** — тестэд хуурамч socket; сүлжээгээр дуудаагүй.
- **Бодит Redis дээрх хоёр процессын fan-out** — `FanoutRedis` хуурамчаар
  шалгагдсан. Бодит Redis дээрх hot-swap тархалт нь DEV_TEST/UAT-ийн хариуцлага.
- **Байршуулсан nginx ↔ backend бүтэн зам** — энд зөвхөн template render ба
  синтакс шалгав, амьд upstream-тай хүсэлт явуулаагүй.
- **Browser түвшний assert (Playwright)**, **backtest зам**, **30 хоногийн paper
  proving window**, **mutation тест (`mutmut`)** — энэ тойрогт ажиллуулаагүй.
- **LLM ↔ Gateway-ийн бодит гүйцэтгэл** (O-1-тэй холбоотой).

---

## 8. Дүгнэлт

**ӨНГӨРӨВ (ногоон).** `2e6e825..b6d29af` дэх гурван засвар (U-3 provider
hot-swap-ийн тархалт ба restart-ыг давах, U-1 reverse proxy, U-2 runbook дүрэм)
нь LLD §12.2, §12, §14-тэй нийцэж, шинэ хадгалалт ч, шинэ тээвэр ч нэмээгүй;
§19-ийн 15 шалгах цэг бүгд биелэв; хянагчийн буцаасан R-1/R-2 хоёр код дээр
хаагдсан хэвээр (бүтэн багц дээр `never awaited` warning алга); дөрвөн гадаргуу
өөрөө ажиллуулахад ногоон (backend 383 + coverage gate, frontend 66, contracts,
nginx template render).

Шинэ тестүүд зан төлөвт наалдсаныг мутацаар баталлаа — `adopt()`-ыг хоослоход
гурван тест унана.

Таван ажиглалтын аль нь ч аюулгүй байдлын хаалгыг (Risk, kill switch, breaker,
live egress, audit chain) сулруулаагүй. §7-ийн шалгаагүй жагсаалт нь хамрах
хүрээний ил заалт — ялангуяа бодит Redis дээрх олон instance тархалт нь
DEV_TEST/UAT шатанд батлагдах ёстой.
