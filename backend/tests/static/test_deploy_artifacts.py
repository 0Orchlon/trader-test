"""Байршуулалтын артефакт репод БАЙХ ёстой (UAT U-2, U-4).

UAT гурван ажиллалт дараалан ижил хоёр шалтгаанаар унав:

* **U-2** — байршуулсан frontend нь ТҮР ЗУУРЫН ажлын хавтас
  (`Temp/task-NNN/repo/frontend/dist`) руу bind mount хийгдсэн. Тэр хавтас
  даалгавар дуусмагц устдаг тул байршуулалт нь дараагийн алхам эхлэхэд
  өөрөө `500` болно.
* **U-4** — backend-ийг байршуулах зам репод БАЙХГҮЙ (Dockerfile алга), тул
  proxy-ийн `BACKEND` анхдагч нь host дээрх ГАДНЫ процесс руу зааж, UI-аас
  ирэх `/api/v1/*` бүр чимээгүй `404` авч байв.

Хоёулаа «деплойгийн алдаа» биш — репод байршуулах БОЛОМЖ байгаагүй.
Энэ тест тэр боломжийг хаалга болгоно: image дотор шатаасан static, репоос
угсрагддаг backend, compose-ийн дотоод сүлжээгээр заасан анхдагч.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
COMPOSE = REPO / "docker-compose.yml"


def _services() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]


def test_backend_and_frontend_dockerfiles_exist() -> None:
    assert (REPO / "backend" / "Dockerfile").is_file()
    assert (REPO / "frontend" / "Dockerfile").is_file()


def test_backend_service_is_built_from_this_repo() -> None:
    """Build context нь РЕПОГИЙН ҮНДЭС байх ёстой (frontend-тэй ижил зарчим):

    `app.agents.contract.load()` нь `contracts/tool-contract.v1.yaml`-ыг эх
    сурвалж гэж уншдаг тул зөвхөн `./backend`-ийг context болговол энэ файл
    image-д ОГТ ордоггүй — эхний бодит tool dispatch (research loop) дээр
    `FileNotFoundError`-оор унадаг байсныг эндээс олж засав.
    """
    backend = _services()["backend"]
    assert "image" not in backend or "build" in backend
    assert backend["build"]["context"] in (".", "./")
    assert backend["build"]["dockerfile"] == "backend/Dockerfile"


def test_frontend_static_is_baked_into_the_image_not_bind_mounted() -> None:
    """U-2: host-ийн хавтас алга болбол байршуулалт үхэх ёсгүй."""
    frontend = _services()["frontend"]
    assert "build" in frontend, "frontend нь Dockerfile-аас угсрагдана"
    for volume in frontend.get("volumes", []):
        source = volume["source"] if isinstance(volume, dict) else volume.split(":")[0]
        assert "dist" not in source, f"түр зуурын хавтаснаас mount: {volume}"


def test_proxy_backend_default_points_at_the_compose_service() -> None:
    """U-4: анхдагч нь host дээрх санамсаргүй процесс биш, өөрийн backend."""
    default = _services()["frontend"]["environment"]["BACKEND"]
    assert "backend:8000" in default
