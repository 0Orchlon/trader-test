"""Provider Router + hot-swap (T-21, LLD §12.2, AC-10, AC-11, FR-8).

**Restart БАЙХГҮЙ.** Солилт нь толгойн лавлагааг ДАХИН ОНООХ явдал —
нэг заалт, lock хэрэггүй (GIL).

**Нислэг дунд байгаа дуудалт хуучнаар дуусна.** Session нь эхлэхдээ
adapter-ийн лавлагааг барьж авдаг тул нэг харилцан яриа дунд provider
солигдохгүй; солилт нь ДАРААГИЙН session-д хүчинтэй. Энэ нь «нэг шийдвэр
хоёр модель» гэсэн будлиантай байдлаас сэргийлж, `agent_decisions.provider`
-ийг үргэлж нэг утгатай байлгана.

**Fallback (LLD §12.3):** идэвхтэй provider `PROVIDER_ERROR_THRESHOLD` удаа
дараалан унавал fallback руу шилжинэ. Fallback нь `read_only` бол шинэ
санал гарахаа болино. ХЭЗЭЭ Ч: Risk алгасах, кэшлэгдсэн саналыг гүйцэтгэх,
авто-батлах.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.agents.adapters.base import BaseAdapter
from app.util.time import now_utc, to_iso

#: v1-д ЗӨВХӨН `research` (спек A-3: бусад agent нь LLM биш).
ROLES = ("research",)


class UnknownProvider(LookupError):
    pass


class ProviderUnhealthy(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SwitchResult:
    role: str
    previous_provider_id: str
    new_provider_id: str
    in_flight_calls: int
    switched_at: datetime

    def to_json(self) -> dict:
        return {
            "role": self.role,
            "previous_provider_id": self.previous_provider_id,
            "new_provider_id": self.new_provider_id,
            "in_flight_calls": self.in_flight_calls,
            "switched_at": to_iso(self.switched_at),
        }


class ProviderRouter:
    def __init__(
        self,
        adapters: list[BaseAdapter],
        *,
        active: dict[str, str] | None = None,
        fallback_id: str | None = None,
        error_threshold: int = 3,
    ) -> None:
        self.adapters = {a.spec.id: a for a in adapters}
        self.fallback_id = fallback_id
        self.error_threshold = error_threshold
        first = next(iter(self.adapters), None)
        self._active = dict(active or ({"research": first} if first else {}))

    # --- унших ---

    def get(self, provider_id: str) -> BaseAdapter:
        try:
            return self.adapters[provider_id]
        except KeyError as exc:
            raise UnknownProvider(f"тохируулагдаагүй provider: {provider_id}") from exc

    def active_id(self, role: str) -> str | None:
        return self._active.get(role)

    def bind(self, role: str) -> BaseAdapter | None:
        """Session эхлэхэд дуудагдана — лавлагааг ЭНД барьж авна.

        Буцаасан объект нь дараа нь router-т солигдсон ч ӨӨРЧЛӨГДӨХГҮЙ:
        Python-ий объектын лавлагаа нь солилтоос хамаарахгүй.
        """
        provider_id = self._active.get(role)
        return self.adapters.get(provider_id) if provider_id else None

    def health(self) -> list[dict]:
        """`GET /health`-ийн `providers[]` (contracts.yaml `Dependency`)."""
        return [
            {"name": a.spec.id, "reachable": a.healthy, "detail": a.last_error}
            for a in self.adapters.values()
        ]

    def to_json(self) -> dict:
        return {
            "providers": [a.to_json() for a in self.adapters.values()],
            "active": dict(self._active),
        }

    def any_writable(self) -> bool:
        """Санал гаргах чадвартай эрүүл provider байна уу.

        Байхгүй бол шинэ санал гарахгүй — байгаа position / order хөндөгдөхгүй
        (T-21 DoD г).
        """
        return any(
            a.healthy and not a.spec.read_only
            for role in ROLES
            if (a := self.bind(role)) is not None
        )

    # --- бичих ---

    async def switch(self, role: str, provider_id: str) -> SwitchResult:
        if role not in ROLES:
            raise UnknownProvider(f"v1-д ийм role байхгүй: {role}")
        adapter = self.get(provider_id)
        if not await adapter.health_check():
            # Унасан provider руу солихгүй — солилт нь 422, төлөв хэвээр.
            raise ProviderUnhealthy(f"{provider_id}: эрүүл мэндийн шалгалт унав")
        previous = self._active.get(role) or ""
        in_flight = self.adapters[previous].in_flight if previous in self.adapters else 0
        self._active[role] = provider_id  # ← ганц заалт; restart БАЙХГҮЙ
        return SwitchResult(
            role=role,
            previous_provider_id=previous,
            new_provider_id=provider_id,
            in_flight_calls=in_flight,
            switched_at=now_utc(),
        )

    def record_error(self, provider_id: str, message: str) -> str | None:
        """Алдааг бүртгээд шаардлагатай бол fallback руу шилжинэ.

        Шилжсэн provider-ийн id-г буцаана (шилжээгүй бол `None`).
        """
        adapter = self.get(provider_id)
        adapter.record_error(message, threshold=self.error_threshold)
        if adapter.healthy or self.fallback_id is None:
            return None
        if provider_id == self.fallback_id:
            return None
        for role, active in list(self._active.items()):
            if active == provider_id:
                self._active[role] = self.fallback_id
        return self.fallback_id

    def record_success(self, provider_id: str) -> None:
        self.get(provider_id).record_success()

    def adopt(self, role: str, provider_id: str) -> bool:
        """Өөр instance-ийн (эсвэл өмнөх ажиллагааны) солилтыг хэрэгжүүлнэ.

        `switch()`-ээс ялгаатай нь health-check ХИЙХГҮЙ: солилтыг үүсгэсэн
        instance аль хэдийн шалгасан, энд дахин шалгах нь нэг үйлдлийн
        үр дүнг instance бүрд өөр болгоно. Танихгүй provider/role-ийг
        ЧИМЭЭГҮЙ алгасна — өөр тохиргоотой instance-ийн мессеж энэ
        process-ийн active-ыг хоослохгүй.
        """
        if role not in ROLES or provider_id not in self.adapters:
            return False
        self._active[role] = provider_id
        return True


def default_router(*, error_threshold: int) -> ProviderRouter:
    """v1-ийн тохиргоо. Шинэ provider нэмэх нь ЭНД нэг мөр."""
    from app.agents.adapters.claude_mcp import ClaudeMcpAdapter
    from app.agents.adapters.local_readonly import LocalReadOnlyAdapter
    from app.agents.adapters.openai_fc import OpenAiFcAdapter, XaiFcAdapter

    adapters = [
        ClaudeMcpAdapter(),
        OpenAiFcAdapter(),
        XaiFcAdapter(),
        LocalReadOnlyAdapter(),
    ]
    return ProviderRouter(
        adapters,
        active={"research": "claude-mcp"},
        fallback_id="local-fallback",
        error_threshold=error_threshold,
    )


async def follow_switches(bus, router: ProviderRouter) -> None:
    """`system` сувгийн `provider_switched`-ийг ЭНЭ process-д хэрэгжүүлнэ.

    U-3 (UAT): солилт нь зөвхөн хүсэлт хүлээн авсан process-д үйлчилдэг тул
    олон instance-тай байршуулалтад оператор provider сольсон ч хүсэлт аль
    instance-д унахаас хамаарч ХУУЧИН модель ажилласаар байв — AC-10 «ажлыг
    тасалдуулахгүйгээр солих» нь чимээгүй хагас биелдэг.

    Шинэ тээвэр НЭМЭХГҮЙ: солилт аль хэдийн Redis-ээр бүх instance-д
    түгээгддэг (LLD §12, AC-14), энэ нь тэр урсгалыг сонсоод router-т
    буулгана. Өөрийн мессеж эргэж ирэх нь idempotent.
    """
    from app.stream.bus import CHANNEL_SYSTEM

    sub = bus.subscribe([CHANNEL_SYSTEM])
    try:
        while True:
            payload = (await sub.get()).payload
            if payload.get("event") == "provider_switched":
                router.adopt(str(payload.get("role", "")), str(payload.get("new_provider_id", "")))
    finally:
        bus.unsubscribe(sub)


#: Дахин асаалтад хэдэн `provider_switched` мөр ухаж харах вэ. Хамгийн сүүлийн
#: мөр л чухал — хязгаар нь role бүрийн сүүлийнхийг олоход хангалттай бөгөөд
#: аудитын түүх өсөхөд query тогтмол үнэтэй үлдэнэ.
_RESTORE_SCAN = 200


async def restore_active(session, router: ProviderRouter) -> None:
    """Дахин асаахад идэвхтэй provider-ийг audit_log-оос сэргээнэ (U-3, AC-10).

    Тусдаа хүснэгт НЭМЭХГҮЙ: солилт аль хэдийн append-only, hash-chain-тай
    `audit_log`-д бичигддэг (LLD §14) — хоёр дахь эх сурвалж үүсгэх нь тэр
    хоёрыг зөрүүлэх боломж нээнэ. Түүх хоосон бол анхдагч хэвээр.
    """
    from sqlalchemy import select

    from app import models

    rows = (
        await session.execute(
            select(models.AuditLog.payload)
            .where(models.AuditLog.event_type == "provider_switched")
            .order_by(models.AuditLog.seq.desc())
            .limit(_RESTORE_SCAN)
        )
    ).scalars().all()

    seen: set[str] = set()
    for payload in rows:
        role = str((payload or {}).get("role", ""))
        if role in seen:
            continue  # илүү шинэ мөр аль хэдийн ялсан
        if router.adopt(role, str((payload or {}).get("new_provider_id", ""))):
            seen.add(role)
            if len(seen) == len(ROLES):
                return
