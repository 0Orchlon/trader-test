"""Tool Contract v1 — **эх** схемийг уншина (T-18, хавсралт 03).

Схемийг Python-д ДАХИН бичихгүй: `contracts/tool-contract.v1.yaml` нь
нийтлэгдсэн гэрээ, энэ модуль түүнийг л уншина. Хоёр дахь тодорхойлолт
үүсгэх нь adapter-ууд «аль нь үнэн бэ» гэдгийг мэдэхгүй болгоно.

Adapter бүр (`claude_mcp`, `openai_fc`, …) ЭНЭ схемээс орчуулга хийнэ —
өөрийн жагсаалт барихгүй. T-22-ийн round-trip тест үүнийг барина.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

#: `backend/app/agents/contract.py` → репогийн үндэс → `contracts/`.
CONTRACT_PATH = Path(__file__).resolve().parents[3] / "contracts" / "tool-contract.v1.yaml"

READ = "read"
PROPOSE = "propose"

#: `read_only: true` provider-т БҮРЭН хаагдах tool-ууд (INV-5).
#: Татгалзал биш — схемээс огт хасагдана.
WRITE_TOOLS = ("propose_order", "propose_tuning_change")


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    if not CONTRACT_PATH.exists():  # pragma: no cover - deploy-ийн тохиргоо
        raise FileNotFoundError(
            f"Tool Contract олдсонгүй: {CONTRACT_PATH}. Энэ файл нь гэрээний ЭХ "
            "сурвалж — Python талд хуулбар үүсгэхгүй."
        )
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def version() -> str:
    return str(load()["contract_version"])


def tools(*, read_only: bool = False) -> list[dict[str, Any]]:
    """`read_only=True` бол бичих tool-ууд ОГТ харагдахгүй (INV-5)."""
    every = load()["tools"]
    if not read_only:
        return list(every)
    return [t for t in every if t["name"] not in WRITE_TOOLS]


def tool(name: str) -> dict[str, Any]:
    for candidate in load()["tools"]:
        if candidate["name"] == name:
            return candidate
    raise KeyError(f"Tool Contract v1-д ийм tool байхгүй: {name}")


def tool_names(*, read_only: bool = False) -> list[str]:
    return [t["name"] for t in tools(read_only=read_only)]


def result_envelope_schema() -> dict[str, Any]:
    return load()["result_envelope"]


def input_schema(name: str) -> dict[str, Any]:
    return tool(name)["input_schema"]
