"""Provider adapter-ийн нийтлэг гэрээ (T-19, T-20, хавсралт 05).

Adapter-ийн ЦОРЫН ГАНЦ ажил бол Tool Contract v1-ийг тухайн vendor-ийн
форматад буулгах. Тэд өөрсдөө tool ЖАГСААЛТ БАРИХГҮЙ — `app.agents.contract`
нь эх сурвалж (T-22-ийн round-trip тест үүнийг барина).

**INV-4:** adapter-т API key, DB credential, «шууд гүйцэтгэ» чадвар
ОЛГОГДОХГҮЙ. Tool call бүр Gateway-ээр л дамжина.

**INV-5:** `read_only=True` adapter-ийн схемээс `propose_order` ба
`propose_tuning_change` БҮРЭН хасагдана — татгалзах биш, огт харагдахгүй.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.agents import contract


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    id: str
    vendor: str
    model: str
    transport: str
    read_only: bool = False


class ProviderAdapter(Protocol):
    spec: ProviderSpec

    def tool_schema(self) -> list[dict[str, Any]]: ...

    async def health(self) -> bool: ...


@dataclass
class BaseAdapter:
    """Нийтлэг төлөв. `tool_schema()`-ийг удам бүр өөрөө буулгана."""

    spec: ProviderSpec
    healthy: bool = True
    last_error: str | None = None
    #: Дараалсан алдааны тоо — `PROVIDER_ERROR_THRESHOLD`-той харьцуулагдана.
    consecutive_errors: int = 0
    in_flight: int = 0

    def source_tools(self) -> list[dict[str, Any]]:
        return contract.tools(read_only=self.spec.read_only)

    async def health_check(self) -> bool:
        """Сүлжээний дуудалт БАЙХГҮЙ (v1).

        `healthy` нь бодит ашиглалтын үр дүнгээс тавигдана (`record_error` /
        `record_success`). Хиймэл ping нь «эрүүл» гэсэн худал итгэл өгнө:
        ping амжилттай атлаа tool call унаж болно.
        """
        return self.healthy

    def record_error(self, message: str, *, threshold: int) -> None:
        self.consecutive_errors += 1
        self.last_error = message
        if self.consecutive_errors >= threshold:
            self.healthy = False

    def record_success(self) -> None:
        self.consecutive_errors = 0
        self.healthy = True
        self.last_error = None

    def to_json(self) -> dict:
        return {
            "id": self.spec.id,
            "vendor": self.spec.vendor,
            "model": self.spec.model,
            "transport": self.spec.transport,
            "healthy": self.healthy,
            "read_only": self.spec.read_only,
            "last_error": self.last_error,
        }
