<!-- PERSONAL-3 · засварын тайлан (7-р тойрог) · DEVELOPMENT · 2026-09-18 -->

# PERSONAL-3 — Засварын тайлан (7-р тойрог)

- **Суурь:** `3b45ac1` (UAT_TEST 2-р ажиллалт, `docs/PERSONAL-3/uat-test-report-round2.md` §8)
- **Хамрах хүрээ:** тэр §8-ийн буцаалтын жагсаалт — U-4, U-2, O-1 (+ O-2)
- **Юу засаагүй:** пайплайны цэг (Alpaca paper түлхүүрийг UAT_TEST-д тогтмол
  хүргэх) — код биш, орчны шийдвэр

---

## 1. Юуг яагаад засав

UAT гурван ажиллалт дараалан ижил хоёр шалтгаанаар унав. Хоёулаа
«байршуулалтын алдаа» гэж бүртгэгдсэн боловч **үндэс нь репод байсан**:
байршуулах ЗАМ өөрөө байгаагүй — Dockerfile алга, compose-д backend service
алга. Тиймээс байршуулагч бүр гараар угсарч, гараар mount хийж, өөр өөрөөр
буруу хийж байв. Энэ тойрог тэр замыг репод оруулав.

| ID | Юу байсан | Юу болов |
|---|---|---|
| **U-2** (блоклогч, 3 удаа давтагдсан) | `frontend/dist` нь host-ийн ажлын хавтаснаас bind mount — `Temp/task-NNN` устмагц бүх зам `500` | `frontend/Dockerfile` — `npm ci && npm run build` нь image ДОТОР, статик image-д шатсан. compose-д bind mount БАЙХГҮЙ |
| **U-4** (блоклогч) | backend байршуулах зам репод алга; `BACKEND` анхдагч нь `host.docker.internal:8000` — UAT-д тэнд ГАДНЫ `SimpleHTTP` процесс сонсож, `/api/v1/*` бүр чимээгүй `404` | `backend/Dockerfile` (Python 3.12 + `requirements.lock`, эхлэхдээ `python -m app.migrate`), compose-д `backend` service, `BACKEND` анхдагч нь `backend:8000` |
| **O-1** (DEVELOPMENT) | `enforce_breaker` 5s тутам, харин `get_account` нь httpx-ийн 10s timeout хүртэл барьдаг тул ажиллалт интервалаас урт болж `max_instances=1`-ээр алгасагдана — логт 101 удаа | `breaker.BROKER_PROBE_TIMEOUT = 2.0` (`asyncio.timeout`); `scheduler`-т `max_instances`/`coalesce`/`misfire_grace_time` ИЛ |
| **O-2** (ажиглалт) | `nginx.conf`-ийн `location /health` нь backend дээр БАЙХГҮЙ зам руу дамжуулж `404` | `location = /health` → `http://${BACKEND}/api/v1/health` |

**O-2-ыг яагаад устгаагүй вэ:** location-ыг устгавал `/health` нь
`location /`-д унаж SPA-ийн `index.html`-ийг `200`-аар буцаана — monitor-д
худал ногоон. Дамжуулах зам нь ганц мөрөөр үнэнийг хэлдэг.

**O-1-д яагаад timeout-ыг сонгов:** `max_instances`-ыг өсгөх нь давхардлыг
зөвшөөрөх — breaker нь идемпотент тул аюулгүй боловч шалтгааныг (хязгааргүй
broker дуудлага) арилгахгүй. Timeout нь шалтгааныг арилгана; метрик нь
«хэмжигдээгүй» хэвээр үлдэнэ (худал ногоон болохгүй), broker-ийн уналт нь
`api_error_rate`-ээр баригдана. `max_instances` нь ил бичигдсэн хоёр дахь
давхарга.

---

## 2. Эхлээд унасан тест

| Тест | Юу унаж байсан |
|---|---|
| `tests/static/test_deploy_artifacts.py` (4) | Dockerfile алга; compose-д `backend` service алга; frontend нь `dist`-ээс mount; `BACKEND` анхдагч нь `backend:8000` БИШ |
| `tests/unit/test_breaker.py::test_hanging_broker_does_not_outlive_the_probe_timeout` | `AttributeError: … has no attribute 'BROKER_PROBE_TIMEOUT'` (timeout байхгүй тул 3600s унтдаг broker нь `measure()`-ыг мөнхөд барина) |

Дараа нь код бичиж 5/5 ногоон.

---

## 3. Хэмжсэн зүйл

| Шалгалт | Үр дүн |
|---|---|
| `pytest --cov` (Python 3.12.13, `requirements.lock`) | **388 passed / 0 failed**, coverage gate ногоон (`app/risk/**` 100%) |
| `npm test` (frontend: `check:api` + lint + typecheck + vitest) | **66 passed** |
| `docker compose build backend frontend` | хоёулаа амжилттай |
| Бүтэн стек (`up -d --build`, өөр порт дээр) | `GET :38000/api/v1/health` `200` · proxy `GET :38080/api/v1/health` `200` · `GET :38080/` `200` · deep link `/approvals` `200` · `GET :38080/health` `200` (JSON, HTML БИШ) |
| Байршуулсан backend-ийн migration | контейнер эхлэхэд өөрөө ажиллаж `Application startup complete` |
| `enforce_breaker` давхцал | 90 секундын ажиллалтад `maximum number of running instances` **0 удаа** (өмнө 101) |

---

## 4. Ил тодорхойлолт (хамрах хүрээнээс гадуур)

- **Alpaca paper түлхүүр** энэ ажиллалтад ч олгогдоогүй — контейнерт
  `broker.reachable=false`. Арилжааны гол зам (AC-31, AC-5, AC-34/35, AC-30)
  нь `uat-test-report.md`-ийн амьд ажиллалтад тэнцсэн хэвээр; энэ тойргийн
  өөрчлөлт order-ийн замын кодыг ХӨНДӨӨГҮЙ (`breaker`-ийн probe timeout,
  scheduler-ийн job тохиргоо, байршуулалтын файлууд).
- **O-3** (WS `seq` нь process тус бүрдээ) — гэрээнд `seq` нь глобал дараалал
  гэж заагаагүй; клиент нь дарааллыг сувгийн дотор л ашиглана. Өөрчлөлт хийх
  бол AsyncAPI-ийн семантик тодорхойлолт хэрэгтэй — гэрээний шат.
- **O-4** (агент дуудах endpoint байхгүй) — LLD §12.2-ийн дагуу **зориудын**:
  MCP горимд LLM нь Gateway-ийн tool-уудыг өөрөө дууддаг, backend нь LLM-ийг
  дуудахгүй. Endpoint нэмэх нь `contracts/openapi.yaml`-ийн өөрчлөлт болох
  тул энэ шатны эрхээс гадуур.
- **Harbor / registry** — image-ууд одоо угсрагдана, гэхдээ push хийх
  бүртгэл (registry, tag, credential) энэ репод тодорхойлогдоогүй. UAT нь
  `docker compose … up -d --build`-аар локал угсарна.
