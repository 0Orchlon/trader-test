"""Гэрээ ↔ маршрутын бүрэн тохирол (T-18 DoD а, AC-11).

`contracts/openapi.yaml`-ийн зам бүр хэрэгжсэн байх ёстой, УРВУУГААР Ч:
гэрээнд байхгүй `/api/v1` зам нь баримтлагдаагүй гадаргуу — frontend түүнийг
мэдэхгүй, хянагч түүнийг хараагүй.

Энэ нь `contracts/verify-mock.mjs`-ийг ОРЛОХГҮЙ: тэр нь дуурайлтын биеийг
шалгана, энэ нь бодит app-ийн гадаргууг.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
OPENAPI = REPO / "contracts" / "openapi.yaml"

#: Гэрээнд БАЙХГҮЙ байж болох дотоод зам. Жагсаалт БОГИНО байх ёстой —
#: урт болох нь «баримтлагдаагүй API» хуримтлагдаж байгаагийн шинж.
UNDOCUMENTED_ALLOWED = {
    "/ws",  # asyncapi.yaml-д тодорхойлогдсон, OpenAPI-д биш
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}


@pytest.fixture(scope="module")
def contract() -> dict:
    return yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))


def _fastapi_to_openapi(path: str) -> str:
    """`/api/v1/orders/{order_id}/cancel` → `/orders/{orderId}/cancel`.

    FastAPI нь snake_case параметр ашиглана, гэрээ нь camelCase. Замын
    БҮТЭЦ л чухал тул параметрийн нэрийг хэвийн болгоно.
    """
    import re

    trimmed = path.removeprefix("/api/v1")
    return re.sub(r"\{[^}]+\}", "{}", trimmed)


def _app_paths(app) -> set[str]:
    return {
        _fastapi_to_openapi(route.path)
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1")
    }


def _contract_paths(contract: dict) -> set[str]:
    import re

    return {re.sub(r"\{[^}]+\}", "{}", path) for path in contract["paths"]}


async def test_every_contract_path_is_implemented(app, contract):
    missing = _contract_paths(contract) - _app_paths(app)
    assert missing == set(), f"гэрээнд байгаа ч хэрэгжээгүй зам: {sorted(missing)}"


async def test_no_undocumented_api_surface(app, contract):
    """Баримтлагдаагүй зам нь frontend-д харагдахгүй, хянагчид ч харагдахгүй."""
    extra = _app_paths(app) - _contract_paths(contract)
    assert extra == set(), f"гэрээнд БАЙХГҮЙ зам нээлттэй байна: {sorted(extra)}"


async def test_operation_ids_are_unique_and_present(contract):
    ids: list[str] = []
    for methods in contract["paths"].values():
        for method, operation in methods.items():
            if method in ("get", "post", "put", "patch", "delete"):
                assert "operationId" in operation, f"{method}: operationId алга"
                ids.append(operation["operationId"])
    assert len(ids) == len(set(ids)), "operationId давхардсан — codegen унана"


async def test_the_websocket_route_exists_outside_the_rest_contract(app):
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/ws" in paths
    assert "/ws" in UNDOCUMENTED_ALLOWED
