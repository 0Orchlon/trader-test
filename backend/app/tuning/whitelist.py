"""Auto-tuning-ийн whitelist + bounds (T-26, LLD §21, AC-24).

Муж нь `tuning_whitelist.yaml`-аас — **API-аар засах endpoint БАЙХГҮЙ**.
Энэ бол алдаа биш, шийдвэр: муж өргөсгөх нь бодлогын өөрчлөлт тул deploy
болон code review-ээр л явна. Энэ модулиас бичих функц ЭКСПОРТЛОГДОХГҮЙ.

`contains()` нь зөвхөн муж биш, `step`-ийг ч барина: 2.55 нь [1.0, 5.0]
дотор ч `step=0.1`-ийн сүлжээнд БАЙХГҮЙ. Алхмыг үл тоох нь «муж дотор л
шүү дээ» гэсэн үндэслэлээр тасралтгүй хайлт нээнэ.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import yaml

WHITELIST_PATH = Path(__file__).resolve().parent / "tuning_whitelist.yaml"


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    name: str
    description: str
    minimum: Decimal
    maximum: Decimal
    step: Decimal
    default: Decimal

    def contains(self, value: Decimal | None) -> bool:
        if value is None:
            return False
        if value < self.minimum or value > self.maximum:
            return False
        offset = value - self.minimum
        return offset % self.step == 0

    def grid(self) -> list[Decimal]:
        """Муж доторх БҮХ зөвшөөрөгдсөн утга. Хайлтын орон зай нь ХЯЗГААРТАЙ."""
        out: list[Decimal] = []
        value = self.minimum
        while value <= self.maximum:
            out.append(value)
            value += self.step
        return out

    def to_json(self) -> dict:
        return {"min": str(self.minimum), "max": str(self.maximum), "step": str(self.step)}


@lru_cache(maxsize=1)
def load() -> dict[str, ParameterSpec]:
    raw = yaml.safe_load(WHITELIST_PATH.read_text(encoding="utf-8"))
    return {
        entry["name"]: ParameterSpec(
            name=entry["name"],
            description=entry.get("description", ""),
            minimum=Decimal(str(entry["min"])),
            maximum=Decimal(str(entry["max"])),
            step=Decimal(str(entry["step"])),
            default=Decimal(str(entry["default"])),
        )
        for entry in raw["parameters"]
    }


def lookup(name: str) -> ParameterSpec | None:
    return load().get(name)


def names() -> list[str]:
    return list(load())


def bounds_json() -> list[dict]:
    return [
        {"name": spec.name, "description": spec.description, "bounds": spec.to_json()}
        for spec in load().values()
    ]
