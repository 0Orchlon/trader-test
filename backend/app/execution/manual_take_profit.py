"""Гар (operator) позицийг ЯМАР Ч эерэг ашигтай болмогц автоматаар хаах
toggle (T-99, хувийн төсөл, LLD-д тусгаагүй).

`exits.py`-ээс ЗОРИУДААР тусдаа модуль:
- `exits.py` нь `research_agent`-ийн ӨӨРИЙН cost basis-аа сэргээж тооцдог
  (10 үе шат шаардсан нарийн логик: lot-scoping, gross-vs-net, timestamp
  tie гэх мэт). Энд ХЭРЭГГҮЙ — бид ХЭСЭГЧЛЭН биш, ПОЗИЦИЙГ БҮХЭЛД нь
  хаадаг тул `Position.unrealized_pl`-ийг (Alpaca-ийн өөрийн тооцоолсон,
  AC-1-ийн дагуу шууд дамжуулсан утга) шууд ашиглана — дахин тооцоолохгүй
  тул exits.py-д олдсон 10 үе шатны АЛДААНЫ АНГИЛАЛ энд физикийн хувьд
  боломжгүй.
- Зөвхөн ЦЭВЭР `research_agent` гаралттай (holимоггүй) позицийг ХӨНДӨХГҮЙ
  — түүнийг `exits.py` өөрийн take-profit-оор аль хэдийн удирддаг тул
  давхар илгээлт үүсэхгүй. Бусад бүх гарал (`manual_operator`, `external`,
  холимог) энд хамаарна.
"""
from __future__ import annotations

from sqlalchemy import select

from app import models
from app.api.attribution import LIVE_STATUSES, attribute, position_origins
from app.broker.alpaca import is_crypto_symbol
from app.broker.models import (
    BrokerRejected,
    BrokerUnavailable,
    Origin,
    OrderSide,
    OrderType,
    PositionSide,
    SystemState,
    TimeInForce,
    ValidatedOrder,
)
from app.execution.agent import ExecutionAgent
from app.system.state import StateMachine
from app.util.time import now_utc

CONFIG_ID = 1


def _norm(symbol: str) -> str:
    return symbol.replace("/", "")


async def get_enabled(session) -> bool:
    row = await session.get(models.ManualTakeProfitConfig, CONFIG_ID)
    return bool(row and row.enabled)


async def set_enabled(session, enabled: bool) -> bool:
    row = await session.get(models.ManualTakeProfitConfig, CONFIG_ID)
    if row is None:
        row = models.ManualTakeProfitConfig(id=CONFIG_ID, enabled=enabled, updated_at=now_utc())
        session.add(row)
    else:
        row.enabled = enabled
        row.updated_at = now_utc()
    await session.commit()
    return enabled


async def run_manual_take_profit(sessionmaker, settings, broker, publisher) -> None:
    """APScheduler-ийн job. Аль ч алдаа scheduler-ийг унагаах ёсгүй."""
    async with sessionmaker() as session:
        if not await get_enabled(session):
            return
        machine = StateMachine(
            session, wind_down_grace=settings.WIND_DOWN_GRACE, publisher=publisher
        )
        state = await machine.current()
        if state.state is SystemState.HALTED:
            return  # kill switch = зогсох, exits.py-тэй адил
        try:
            positions = (await broker.get_positions()).data
        except BrokerUnavailable:
            return
        if not positions:
            return

        origins = await position_origins(session)
        targets = []
        for p in positions:
            attribution = attribute(p, origins)
            if attribution.origin is Origin.RESEARCH_AGENT and not attribution.mixed:
                continue  # цэвэр research_agent позицийг exits.py л удирдана
            if not p.qty or p.unrealized_pl is None or p.unrealized_pl <= 0:
                continue
            targets.append(p)
        if not targets:
            return

        # Нээлттэй order байгаа symbol-ыг хөндөхгүй — давхар хаалтаас
        # хамгаалах (exits.py-тэй адил зарчим): локал + broker-ийн өөрийн
        # харц хоёуланг шалгана.
        rows = (await session.execute(select(models.Order))).scalars().all()
        open_symbols = {_norm(r.symbol) for r in rows if r.status in LIVE_STATUSES}
        try:
            open_symbols |= {_norm(o.symbol) for o in (await broker.get_open_orders()).data}
        except BrokerUnavailable:
            return
        targets = [p for p in targets if _norm(p.symbol) not in open_symbols]
        if not targets:
            return

        watch = {_norm(s): s for s in settings.research_symbols}
        now = now_utc()
        agent = ExecutionAgent(session, broker, machine, mode=settings.mode.value)
        for p in targets:
            # `BTCUSD` → `BTC/USD` буцаах боломжгүй symbol-ыг ХӨНДӨХГҮЙ:
            # exits.py-ийн адил шалтгаанаар (буулгаагүй бол crypto order
            # DAY TIF-тэй явж, halted амьд ослыг давтана).
            symbol = watch.get(_norm(p.symbol))
            if symbol is None:
                continue
            side = OrderSide.SELL if p.side is PositionSide.LONG else OrderSide.BUY
            order = ValidatedOrder(
                symbol=symbol,
                side=side,
                qty=abs(p.qty),
                order_type=OrderType.MARKET,
                time_in_force=(
                    TimeInForce.GTC if is_crypto_symbol(symbol) else TimeInForce.DAY
                ),
                limit_price=None,
                stop_price=None,
                client_order_id=f"mtp-{_norm(symbol)}-{int(now.timestamp()) // 60}",
                risk_evaluation={"reduce_only_exit": "manual_take_profit"},
            )
            try:
                await agent.submit(
                    order,
                    origin=Origin.RESEARCH_AGENT,
                    origin_detail="auto_manual_take_profit",
                    actor="system:manual_take_profit",
                )
            except (BrokerRejected, BrokerUnavailable):
                continue  # нэг symbol унах нь бусдын хаалтыг зогсоохгүй
