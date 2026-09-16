"""Claude adapter — MCP (T-19, хавсралт 05).

Tool Contract v1 → MCP-ийн `tools/list` формат. MCP нь `name`,
`description`, `inputSchema` гэсэн гурван талбар хүлээнэ; схем нь эх
файлаас ЯГ хуулагдана — adapter нь схем ЗОХИОХГҮЙ (T-22 round-trip).

`tool_use` / `tool_result` блокууд нь Gateway-ийн `result_envelope`-ыг
ӨӨРЧЛӨЛТГҮЙ дамжуулна: envelope-ийн `tool_call_id`, `timestamp`,
`source`, `system_state` нь LLM-д хүрэх ёстой (INV-2, AC-34).
"""
from __future__ import annotations

import json
from typing import Any

from app.agents.adapters.base import BaseAdapter, ProviderSpec

SPEC = ProviderSpec(
    id="claude-mcp", vendor="anthropic", model="claude-opus-5", transport="mcp"
)


class ClaudeMcpAdapter(BaseAdapter):
    def __init__(self, spec: ProviderSpec = SPEC) -> None:
        super().__init__(spec=spec)

    def tool_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool["name"],
                "description": tool["description"],
                "inputSchema": tool["input_schema"],
            }
            for tool in self.source_tools()
        ]

    def tool_result_block(self, tool_use_id: str, envelope: dict) -> dict:
        """MCP-ийн `tool_result`. Envelope нь БҮТНЭЭР дотор нь орно."""
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "is_error": not envelope["ok"],
            "content": [{"type": "text", "text": json.dumps(envelope, ensure_ascii=False)}],
        }

    @staticmethod
    def parse_tool_use(block: dict) -> tuple[str, dict]:
        return block["name"], dict(block.get("input", {}))
