"""OpenAI / ChatGPT adapter — function calling (T-20, хавсралт 05).

Tool Contract v1 → OpenAI-ийн `tools[]` формат 1:1. `strict: True` нь
схемийг заавал дагуулна: дутуу `grounded_in`-тай дуудалт модель талд л
унана, backend хүртэл ирэхгүй (T-18 DoD в-ийн хоёр дахь давхарга).

Grok (xAI) нь ижил function-calling гэрээтэй тул `XaiFcAdapter` нь зөвхөн
`ProviderSpec`-ээрээ ялгаатай — орчуулгын хоёр дахь хувилбар БАЙХГҮЙ.
"""
from __future__ import annotations

import json
from typing import Any

from app.agents.adapters.base import BaseAdapter, ProviderSpec

SPEC = ProviderSpec(
    id="openai-fc", vendor="openai", model="gpt-5", transport="function_calling"
)
XAI_SPEC = ProviderSpec(
    id="xai-fc", vendor="xai", model="grok-4", transport="function_calling"
)
#: T-99 (хувийн төсөл): `local-fallback`-аас ЗОРИУДААР ТУСДАА — тэр нь
#: `read_only=True` аюулгүй байдлын хаалга (INV-5), санал ХЭЗЭЭ Ч гаргахгүй.
#: Local загвар бодит арилжаа хийхийг хүсвэл ЭНД, шинэ id-аар.
LOCAL_FC_SPEC = ProviderSpec(
    id="local-fc", vendor="local", model="local", transport="function_calling"
)


class OpenAiFcAdapter(BaseAdapter):
    def __init__(self, spec: ProviderSpec = SPEC) -> None:
        super().__init__(spec=spec)

    def tool_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                    "strict": True,
                },
            }
            for tool in self.source_tools()
        ]

    def tool_result_message(self, tool_call_id: str, envelope: dict) -> dict:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps(envelope, ensure_ascii=False),
        }

    @staticmethod
    def parse_tool_call(call: dict) -> tuple[str, dict]:
        function = call["function"]
        raw = function.get("arguments") or "{}"
        return function["name"], json.loads(raw) if isinstance(raw, str) else dict(raw)


class XaiFcAdapter(OpenAiFcAdapter):
    def __init__(self, spec: ProviderSpec = XAI_SPEC) -> None:
        super().__init__(spec=spec)


class LocalFcAdapter(OpenAiFcAdapter):
    """Local model (Ollama/LM Studio-төрлийн OpenAI-нийцтэй сервер) — БИЧИХ
    эрхтэй (`read_only=False`), `local-fallback`-аас ялгаатай."""

    def __init__(self, spec: ProviderSpec = LOCAL_FC_SPEC) -> None:
        super().__init__(spec=spec)
