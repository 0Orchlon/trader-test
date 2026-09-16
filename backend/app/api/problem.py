"""RFC 9457 Problem Details (contracts.yaml `Problem`).

Алдааны `code` нь гэрээний enum-аас — чөлөөт текст БИШ. Frontend нь `code`-оор
салаалдаг тул шинэ код нэмэх нь гэрээний өөрчлөлт.
"""
from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

BASE = "https://personal-3.invalid/problems/"

TITLES = {
    "confirmation_required": "Баталгаажуулалт шаардлагатай",
    "system_halted": "Систем зогссон",
    "winding_down_increase_blocked": "Wind-down үед эрсдэл нэмэгдүүлэхийг хориглов",
    "risk_rejected": "Risk Agent татгалзав",
    "grounding_failed": "Үндэслэл өгөгдөлд тулгуурлаагүй",
    "idempotency_conflict": "Idempotency-Key давхардсан боловч бие өөр",
    "breaker_still_tripped": "Circuit breaker унасан хэвээр",
    "already_active": "Аль хэдийн идэвхтэй",
    "approval_expired": "Хугацаа дууссан",
    "version_conflict": "Хувилбарын зөрүү",
    "broker_unavailable": "Broker хүрэхгүй байна",
    "provider_unavailable": "Provider хүрэхгүй байна",
    "not_found": "Олдсонгүй",
}


class ProblemError(Exception):
    def __init__(self, code: str, status: int, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.code = code
        self.status = status
        self.detail = detail
        self.extra = extra

    def body(self) -> dict[str, Any]:
        return {
            "type": BASE + self.code,
            "title": TITLES.get(self.code, self.code),
            "status": self.status,
            "code": self.code,
            "detail": self.detail,
            **{k: v for k, v in self.extra.items() if v is not None},
        }

    def response(self) -> JSONResponse:
        return JSONResponse(status_code=self.status, content=self.body())


def problem(code: str, status: int, detail: str, **extra: Any) -> ProblemError:
    return ProblemError(code, status, detail, **extra)
