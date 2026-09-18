"""`LiveEgressGuard` (LLD §17.3, AC-12).

Тестийн үед live host руу гарах дуудалтыг ЗААВАЛ AssertionError болгоно.
`conftest.py`-д autouse — opt-out БАЙХГҮЙ.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from app.config.mode import LIVE_HOST


class LiveEgressViolation(AssertionError):
    pass


class LiveEgressGuard:
    """Идэвхтэй үед live host руу хандах бүх оролдлогыг барина."""

    def __init__(self, forbidden_host: str = LIVE_HOST) -> None:
        self.forbidden_host = forbidden_host
        self.blocked: list[str] = []

    def check(self, url: str) -> None:
        # Хостыг ЯГ тааруулна: `api.alpaca.markets` нь
        # `paper-api.alpaca.markets`-ийн дэд мөр — дэд мөрөөр шалгавал paper ч
        # хоригдоно.
        if urlsplit(url).hostname == self.forbidden_host:
            self.blocked.append(url)
            raise LiveEgressViolation(
                f"тестийн явцад live Alpaca руу дуудалт хоригтой: {url}"
            )


ACTIVE_GUARD: LiveEgressGuard | None = None


def check_egress(url: str) -> None:
    if ACTIVE_GUARD is not None:
        ACTIVE_GUARD.check(url)
