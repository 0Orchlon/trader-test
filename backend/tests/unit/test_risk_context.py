"""`risk_context.build` — crypto symbol form must match order requests
(T-99, хувийн төсөл). Broker positions ирдэг `SOLUSD` (slash-гүй), харин
захиалга/эрсдэлийн шалгуур `SOL/USD` (slash-тэй) хүлээдэг тул frozen
`risk/rules.py`-ийн exact-match `position_for` олдохгүй байсан алдааг
шалгана (round: manual-take-profit-ийн шууд ажиллагаанаас илэрсэн)."""
from __future__ import annotations

from decimal import Decimal

from app.api import risk_context
from app.broker.models import SystemState
from tests.fakes import position


async def test_a_crypto_position_keeps_the_slash_form_symbol(broker, settings):
    """Broker `SOLUSD` (slash-гүй) буцаадаг ч, гарах RiskContext.positions
    нь `settings.RESEARCH_SYMBOLS`-ийн slash-тэй бичлэгтэй тохирно."""
    broker.positions = [position("SOLUSD", "10", "1000.00")]
    ctx = await risk_context.build(broker, settings, SystemState.ACTIVE, "SOL/USD")

    assert [p.symbol for p in ctx.positions] == ["SOL/USD"]


async def test_a_stock_position_symbol_is_left_unchanged(broker, settings):
    """Хувьцаа (slash огт байдаггүй) — normalize-ийн шаардлагагүй тул
    хэвээрээ үлдэнэ."""
    broker.positions = [position("AAPL", "5", "900.00")]
    ctx = await risk_context.build(broker, settings, SystemState.ACTIVE, "AAPL")

    assert [p.symbol for p in ctx.positions] == ["AAPL"]


async def test_an_unrecognized_bare_symbol_is_left_unchanged(broker, settings):
    """`settings.RESEARCH_SYMBOLS`-д огт байхгүй bare symbol-ыг ТААМАГЛАХГҮЙ
    — хэвээр нь дамжуулна (алдаатай илгээхээс дутуу мэдээлэлтэй байх нь дээр)."""
    broker.positions = [position("ZZZUSD", "1", "100.00")]
    ctx = await risk_context.build(broker, settings, SystemState.ACTIVE, "ZZZUSD")

    assert [p.symbol for p in ctx.positions] == ["ZZZUSD"]


async def test_closing_a_full_crypto_position_does_not_inflate_exposure(broker, settings):
    """ЯГ бодит буг: slash-гүй позиц дээр slash-тэй ХААХ order ирэхэд
    `position_for` (frozen) ОЛОХГҮЙ байсан тул `increases_exposure` "шинэ
    symbol" гэж үзээд бодит ХААЛТЫГ (exposure БАГАСГАХ ёстой) exposure
    НЭМЭГДЭЛТ мэт тооцдог байв. Засварын дараа `position_for` ОЛНО."""
    from app.risk.rules import position_for

    broker.positions = [position("SOLUSD", "10", "1000.00")]
    ctx = await risk_context.build(broker, settings, SystemState.ACTIVE, "SOL/USD")

    found = position_for(ctx.positions, "SOL/USD")
    assert found is not None
    assert found.qty == Decimal("10")
