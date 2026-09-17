"""AsyncAPI гэрээний хаалга (B-2-ийн засвар).

`contracts/asyncapi.yaml` нь нийтлэгдсэн гэрээ — WS-ээр гарах payload бүр
түүний schema-г хангах ЁСТОЙ. Өмнө нь энэ гадаргууг шалгах тест БАЙХГҮЙ
байсан тул код ба гэрээ чимээгүй зөрж байв (`verify-mock.mjs` нь зөвхөн
OpenAPI-г шалгадаг).

Хаалга нь `ValidatingEventBus`-ээр ажиллана: `conftest`-ийн `bus` fixture
үүнийг буцаадаг тул **бүх API/integration тестийн бүх нийтлэл** шалгагдана.
Тусдаа «гэрээний тест» бичих шаардлагагүй — зөрчил гарсан замын тест өөрөө
унана.

`app/stream/bus.py`-ийн транспортын unit тест нь EventBus-ыг ШУУД үүсгэдэг
тул энэ шалгалтад ордоггүй: тэнд payload нь зориудаар дүр үзүүлсэн
(backpressure-ийг хэмжиж байгаа болохоос гэрээг биш).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from app.stream.bus import EventBus

ASYNCAPI = Path(__file__).resolve().parents[2] / "contracts" / "asyncapi.yaml"

#: bus-ийн суваг → asyncapi-ийн channel key
CHANNEL_KEYS = {
    "ticks": "ticks",
    "orders": "orders",
    "agent-decisions": "agentDecisions",
    "system": "system",
}


class ContractViolation(AssertionError):
    pass


@lru_cache(maxsize=1)
def _document() -> dict:
    return yaml.safe_load(ASYNCAPI.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _validators() -> dict[str, Draft202012Validator]:
    doc = _document()
    messages = doc["components"]["messages"]
    out: dict[str, Draft202012Validator] = {}
    for channel, key in CHANNEL_KEYS.items():
        (message,) = doc["channels"][key]["messages"].values()
        name = message["$ref"].rsplit("/", 1)[-1]
        out[channel] = Draft202012Validator(messages[name]["payload"])
    return out


def validate(channel: str, payload: dict[str, Any]) -> None:
    """Суваг + payload → гэрээний зөрчил бол `ContractViolation`."""
    validator = _validators().get(channel.split(":", 1)[0])
    if validator is None:  # гэрээнд байхгүй суваг — нийтлэх нь өөрөө зөрчил
        raise ContractViolation(f"asyncapi-д тодорхойлогдоогүй суваг: {channel}")
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.json_path)
    if errors:
        detail = "; ".join(f"{e.json_path}: {e.message}" for e in errors)
        raise ContractViolation(f"{channel} payload нь asyncapi-тай зөрчилдөв — {detail}")


class ValidatingEventBus(EventBus):
    """Нийтлэгдсэн мессеж бүрийг гэрээгээр шалгана. Зөвхөн тестэд."""

    async def publish(self, channel: str, payload: dict[str, Any]):
        message = await super().publish(channel, payload)
        validate(message.channel, message.payload)
        return message
