"""Детерминист хаалгууд: crypto-ийн TIF засвар, мэдээ ≠ тоон нотолгоо.

Хоёул нэг зарчмын хоёр тал: prompt бол хяналт БИШ. Model юу ч бичсэн,
боломжгүй талбар кодоор засагдаж, буруу нотолгоо кодоор шүүгдэнэ.
"""
from __future__ import annotations

import pytest

from app import models
from app.agents.tools import ToolContext, propose_order
from app.broker.models import Source, SystemState, TimeInForce
from app.system.state import StateMachine
from app.util.time import now_utc
from tests.fakes import quote

SESSION_ID = "sess-guards"


@pytest.fixture
async def ctx(db_session, broker, settings, bus):
    machine = StateMachine(db_session, wind_down_grace=settings.WIND_DOWN_GRACE)
    await machine.ensure_initialised()
    await machine.transition(SystemState.ACTIVE, by="operator", reason="тест")
    broker.quotes["BTC/USD"] = quote("BTC/USD", "90000.00")
    broker.quotes["AAPL"] = quote("AAPL", "221.50")
    return ToolContext(
        session=db_session,
        broker=broker,
        settings=settings,
        machine=machine,
        bus=bus,
        provider_id="local-ollama",
        model="qwen3:4b-instruct",
        session_id=SESSION_ID,
    )


def args(**overrides) -> dict:
    base = {
        "symbol": "AAPL",
        "side": "buy",
        "qty": "10",
        "order_type": "limit",
        "limit_price": "221.50",
        "time_in_force": "day",
        "rationale": "Чиг хандлага дээшээ байна.",
        "grounded_in": [],
    }
    base.update(overrides)
    return base


# --- FIX I: crypto-д `day` нь Alpaca-ийн 422 ---


async def test_a_crypto_proposal_is_submitted_as_gtc_not_day(ctx, broker):
    result = await propose_order(
        ctx, args(symbol="BTC/USD", qty="0.005", order_type="market", limit_price=None)
    )

    assert result["stage"] == "approved_for_execution", result
    assert broker.submitted[0].time_in_force is TimeInForce.GTC


async def test_a_stock_proposal_keeps_day(ctx, broker):
    result = await propose_order(ctx, args())

    assert result["stage"] == "approved_for_execution", result
    assert broker.submitted[0].time_in_force is TimeInForce.DAY


# --- FIX H: мэдээний payload дахь тоо нь нотолгоо БИШ ---


async def _tool_call(session, tool_name: str, response: dict) -> str:
    row = models.ToolCall(
        session_id=SESSION_ID,
        tool_name=tool_name,
        request={},
        response=response,
        source=Source.ALPACA_PAPER.value,
        provider="local-ollama",
        called_at=now_utc(),
    )
    session.add(row)
    await session.flush()
    return str(row.id)


async def test_a_number_seen_only_in_news_does_not_ground_a_claim(ctx, db_session, broker):
    citation = await _tool_call(
        db_session,
        "get_news",
        {"ok": True, "data": {"news": [{"headline": "AAPL нь 999.99 хүрэв"}]}},
    )

    result = await propose_order(
        ctx, args(rationale="Үнэ 999.99 дээр орно.", grounded_in=[citation])
    )

    assert result["stage"] == "grounding_failed"
    assert result["unverified_claims"] == ["999.99"]
    assert broker.submitted == []


async def test_the_same_number_from_a_quote_does_ground_the_claim(ctx, db_session, broker):
    citation = await _tool_call(
        db_session, "get_quote", {"ok": True, "data": {"symbol": "AAPL", "last": "999.99"}}
    )

    result = await propose_order(
        ctx, args(rationale="Үнэ 999.99 дээр орно.", grounded_in=[citation])
    )

    assert result["stage"] == "approved_for_execution", result


# --- FIX: нотолгооны haystack нь ЗӨВХӨН энэ саналын symbol (T-99) ---
#
# Энэ шүүлт `_cited_payloads`-д, өөрөөр хэлбэл model-ийн ХОЁУЛАНГ нь (Anthropic
# ба local) зам дамждаг цорын ганц газарт байрлана. Тиймээс энд model өөрөө
# гараар бичсэн citation-ыг дуурайж шалгана.


async def test_a_quote_for_another_symbol_does_not_ground_the_claim(ctx, db_session, broker):
    citation = await _tool_call(
        db_session, "get_quote", {"ok": True, "data": {"symbol": "NVDA", "last": "402.15"}}
    )

    result = await propose_order(
        ctx, args(rationale="Үнэ 402.15 дээр орно.", grounded_in=[citation])
    )

    assert result["stage"] == "grounding_failed"
    assert result["unverified_claims"] == ["402.15"]
    assert broker.submitted == []


async def test_another_positions_entry_price_does_not_ground_the_claim(ctx, db_session, broker):
    citation = await _tool_call(
        db_session,
        "get_positions",
        {
            "ok": True,
            "data": {
                "positions": [
                    {"symbol": "NVDA", "avg_entry_price": "402.15"},
                    {"symbol": "AAPL", "avg_entry_price": "221.50"},
                ]
            },
        },
    )

    result = await propose_order(
        ctx, args(rationale="Орох үнэ 402.15.", grounded_in=[citation])
    )

    assert result["stage"] == "grounding_failed"
    assert result["unverified_claims"] == ["402.15"]
    assert broker.submitted == []
    # Тухайн symbol-ын ӨӨРИЙНХ нь тоо хэвээрээ ажиллана.
    ok = await propose_order(ctx, args(rationale="Орох үнэ 221.50.", grounded_in=[citation]))
    assert ok["stage"] == "approved_for_execution", ok


# --- ROOT CAUSE F: шүүлт нь ХААЛТТАЙ УНАНА (T-99) ---
#
# Өмнөх хувилбар «өөр symbol-ынхыг хас» гэсэн ЖАГСААЛТААР ажиллаж байсан тул
# жагсаалтад ороогүй бүтэц бүр (амжилтгүй дуудлага, өөр хэлбэрийн `data`,
# гүнд нуугдсан symbol) шүүлтгүй өнгөрч байв. Одоо «энэ symbol-ынх гэж
# батлагдсаныг л оруул».


async def test_a_failed_tool_call_grounds_nothing(ctx, db_session, broker):
    """Амжилтгүй дуудлагад хууль ёсны тоон нотолгоо ОГТ БАЙХГҮЙ — алдааны
    мессеж дэх үнэ ч haystack-д орох ёсгүй."""
    citation = await _tool_call(
        db_session,
        "get_quote",
        {
            "ok": False,
            "data": None,
            "error": {"code": "stale", "message": "NVDA: 402.15 quote хуучирсан"},
        },
    )

    result = await propose_order(
        ctx, args(rationale="Үнэ 402.15 дээр орно.", grounded_in=[citation])
    )

    assert result["stage"] == "grounding_failed"
    assert result["unverified_claims"] == ["402.15"]
    assert broker.submitted == []


@pytest.mark.parametrize(
    "data",
    (
        # Дээд түвшин нь ЗӨВ symbol ч гүнд нь өөрийнх нь БИШ тоо.
        {"symbol": "AAPL", "bars": [{"symbol": "NVDA", "c": "402.15"}]},
        # Танихгүй хэлбэр — `symbol`/`positions` түлхүүргүй тул хуучин
        # шүүлтээс бүхэлдээ чөлөөтэй өнгөрдөг байв.
        {"quotes": [{"symbol": "NVDA", "last": "402.15"}]},
    ),
)
async def test_a_foreign_symbol_at_any_depth_grounds_nothing(
    ctx, db_session, broker, data
):
    citation = await _tool_call(db_session, "get_bars", {"ok": True, "data": data})

    result = await propose_order(
        ctx, args(rationale="Үнэ 402.15 дээр орно.", grounded_in=[citation])
    )

    assert result["stage"] == "grounding_failed"
    assert result["unverified_claims"] == ["402.15"]
    assert broker.submitted == []


async def test_account_wide_numbers_still_ground_a_claim(ctx, db_session, broker):
    """`get_account` нь symbol-гүй — тэр нь аль ч саналд хүчинтэй нотолгоо."""
    citation = await _tool_call(
        db_session,
        "get_account",
        {"ok": True, "data": {"equity": "100000.00", "cash": "50000.00"}, "error": None},
    )

    result = await propose_order(
        ctx, args(rationale="Бэлэн мөнгө 50000.00 хүрэлцэнэ.", grounded_in=[citation])
    )

    assert result["stage"] == "approved_for_execution", result


async def test_a_crypto_quote_grounds_the_claim_despite_the_slash(ctx, db_session, broker):
    """`BTCUSD` ↔ `BTC/USD` нь НЭГ symbol — шүүлт үүнийг таслах ёсгүй."""
    citation = await _tool_call(
        db_session, "get_quote", {"ok": True, "data": {"symbol": "BTCUSD", "last": "90000.00"}}
    )

    result = await propose_order(
        ctx,
        args(
            symbol="BTC/USD",
            qty="0.005",
            order_type="market",
            limit_price=None,
            rationale="Үнэ 90000.00.",
            grounded_in=[citation],
        ),
    )

    assert result["stage"] == "approved_for_execution", result


# --- ROOT CAUSE F, ӨӨР ХААЛГА: `propose_tuning_change`-ийн нотолгоо ---
#
# `_narrowed` дэх «амжилтгүй дуудлага = нотолгоогүй» хаалга нь ЗӨВХӨН
# `symbol` дамжуулсан үед (өөрөөр хэлбэл `propose_order`-д) ажиллаж байв.
# `propose_tuning_change` нь symbol-гүй тул тэр хаалгыг бүхэлд нь тойрч,
# `{ok: false, data: null}` мөр «бодит backtest нотолгоо» гэж тоологдож
# байлаа. Хаалга нь одоо `_cited_payloads`-д — БҮХ зам дамждаг газарт.


async def test_a_failed_tool_call_is_not_backtest_evidence(ctx, db_session):
    from app.agents.gateway import ToolError
    from app.agents.tools import propose_tuning_change

    citation = await _tool_call(
        db_session,
        "get_backtest_result",
        {"ok": False, "data": None, "error": {"code": "no_data", "message": "2.6 алга"}},
    )

    with pytest.raises(ToolError):
        await propose_tuning_change(
            ctx,
            {"parameter": "STOP_LOSS_PCT", "new_value": "2.6", "backtest_evidence": citation},
        )


async def test_a_successful_tool_call_is_still_backtest_evidence(ctx, db_session):
    from app.agents.tools import propose_tuning_change

    citation = await _tool_call(
        db_session,
        "get_backtest_result",
        {"ok": True, "data": {"source": "backtest", "sharpe": "1.4"}, "error": None},
    )

    result = await propose_tuning_change(
        ctx,
        {"parameter": "STOP_LOSS_PCT", "new_value": "2.6", "backtest_evidence": citation},
    )

    assert result["accepted"] is True
