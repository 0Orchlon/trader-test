"""Local / fallback adapter — ЗӨВХӨН УНШИХ (INV-5, LLD §12.3).

`read_only=True` тул `propose_order` ба `propose_tuning_change` нь схемээс
БҮРЭН хасагдана: модель тэднийг харахгүй, тиймээс татгалзах ч шаардлагагүй.

Бүх provider унасан үед систем ЭНД унана — шинэ санал гарахаа болино,
харин Risk, Monitoring, kill switch, circuit breaker ажилласаар байна.
LLM-ээс хамааралгүй хэсэг нь LLM-ийн уналтад өртөхгүй.
"""
from __future__ import annotations

from typing import Any

from app.agents.adapters.base import BaseAdapter, ProviderSpec

SPEC = ProviderSpec(
    id="local-fallback",
    vendor="local",
    model="llama-3.1-70b",
    transport="stdio_json",
    read_only=True,
)


class LocalReadOnlyAdapter(BaseAdapter):
    def __init__(self, spec: ProviderSpec = SPEC) -> None:
        super().__init__(spec=spec)

    def tool_schema(self) -> list[dict[str, Any]]:
        return [
            {"name": tool["name"], "description": tool["description"],
             "input_schema": tool["input_schema"]}
            for tool in self.source_tools()
        ]
