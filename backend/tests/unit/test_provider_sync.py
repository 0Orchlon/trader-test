"""Provider hot-swap нь БҮХ instance-д хүрнэ, restart-ыг давна (U-3, AC-10).

UAT-д илэрсэн зөрчил: `ProviderRouter._active` нь process-ийн дотоод dict тул
`:28000`-д хийсэн солилт `:28001`-д хүрэхгүй, дахин асаахад `claude-mcp` руу
буцдаг байв. Оператор provider сольсон гэж бодох атлаа хүсэлт аль instance-д
унахаас хамаарч ХУУЧИН модель шийдвэр гаргасаар байна.

Шийдэл: солилт нь аль хэдийн `system` суваг + audit_log-д бичигддэг — өөр
хадгалалт НЭМЭХГҮЙГЭЭР тэр хоёрыг уншина.
"""
from __future__ import annotations

import asyncio

import pytest

from app.agents.router import default_router, follow_switches, restore_active
from app.stream.bus import CHANNEL_SYSTEM, EventBus
from tests.fakes import FanoutRedis


def _routers() -> tuple:
    return default_router(error_threshold=3), default_router(error_threshold=3)


async def test_switch_on_one_instance_reaches_the_other():
    """AC-10: нэг instance-д хийсэн солилт нөгөөгийн ШИЙДВЭРИЙН замд хүрнэ."""
    redis = FanoutRedis()
    bus_a, bus_b = EventBus(redis=redis), EventBus(redis=redis)
    router_a, router_b = _routers()
    tasks = [
        asyncio.create_task(bus_a.bridge()),
        asyncio.create_task(bus_b.bridge()),
        asyncio.create_task(follow_switches(bus_b, router_b)),
    ]
    await asyncio.sleep(0)

    result = await router_a.switch("research", "openai-fc")
    await bus_a.publish(CHANNEL_SYSTEM, {"event": "provider_switched", **result.to_json()})
    await asyncio.sleep(0.05)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    assert router_b.active_id("research") == "openai-fc"
    # `bind()` нь шийдвэрийн зам — идэвхтэй adapter БОДИТООР солигдсон байна.
    assert router_b.bind("research").spec.id == "openai-fc"


async def test_unknown_provider_in_event_leaves_active_untouched():
    """Өөр тохиргоотой instance-ийн мессеж нь энэ process-ийг эвдэхгүй."""
    bus = EventBus()
    router = default_router(error_threshold=3)
    task = asyncio.create_task(follow_switches(bus, router))
    await asyncio.sleep(0)

    await bus.publish(
        CHANNEL_SYSTEM,
        {"event": "provider_switched", "role": "research", "new_provider_id": "gemini-x"},
    )
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert router.active_id("research") == "claude-mcp"


async def test_restart_restores_last_switch_from_audit_log(db_session):
    """Дахин асаалт нь анхдагчид буцахгүй — audit_log нь эрх бүхий эх сурвалж."""
    from app.audit.chain import AuditChain

    chain = AuditChain(db_session)
    for provider_id in ("xai-fc", "openai-fc"):
        await chain.append(
            "provider_switched",
            "operator",
            {"role": "research", "previous_provider_id": "claude-mcp", "new_provider_id": provider_id},
        )
    await db_session.commit()

    router = default_router(error_threshold=3)
    await restore_active(db_session, router)

    assert router.active_id("research") == "openai-fc"  # ХАМГИЙН СҮҮЛИЙНХ


async def test_restart_without_history_keeps_default(db_session):
    router = default_router(error_threshold=3)
    await restore_active(db_session, router)
    assert router.active_id("research") == "claude-mcp"


@pytest.mark.parametrize("payload", [{"role": "auto_tuning", "new_provider_id": "openai-fc"}])
async def test_unknown_role_is_ignored(payload, db_session):
    """v1-д `research`-аас өөр role БАЙХГҮЙ — тэр мөрөөр active бохирдохгүй."""
    from app.audit.chain import AuditChain

    await AuditChain(db_session).append("provider_switched", "operator", payload)
    await db_session.commit()

    router = default_router(error_threshold=3)
    await restore_active(db_session, router)

    assert router.active_id("research") == "claude-mcp"
    assert router.active_id("auto_tuning") is None
