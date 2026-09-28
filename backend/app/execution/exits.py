"""Детерминистик exit manager (T-99, хувийн төсөл).

Систем позиц НЭЭЖ чаддаг ч ХААЖ чаддаггүй байсан — хаалтгүй бол realized
тоо гарахгүй, «сургалт» гэдэг ч утгагүй.

ЯГААД `risk.agent.evaluate()`-ээр явуулахгүй вэ (ил тэмдэглэв, нуугаагүй):
R1 (halted) ба R8 (өдрийн алдагдлын хязгаар) нь ЧИГЛЭЛ ЯЛГАДАГГҮЙ бөгөөд
`app/risk/*.py` нь ХӨЛДӨӨСӨН. Тиймээс эдгээрээр дамжуулбал ЯГ stop-loss
хэрэгтэй тэр өдөр exit нь хамт хоригдоно. Энэ модуль `ValidatedOrder`-ыг
ӨӨРӨӨ угсарна. Үүнийг review-ээр БИШ, бүтцээр барина: статик хаалга R-6
нь `ValidatedOrder(`-ыг зөвхөн `app.risk.agent` ба `app.execution.exits`
хоёрт зөвшөөрнө. Аюулгүй байдал нь зөвхөн БАГАСГАХ шинжээс гарна: qty нь
АГЕНТЫН ӨӨРИЙН цэвэр bielelt-ээр таслагдана (позицийн хэмжээ нь ОПЕРАТОРЫН
тоо — түүгээр таслах нь операторын ширхгийг зарна), холимог гаралтай symbol
огт хөндөгдөхгүй, side албадан эсрэг, зөвхөн market, ба ExecutionAgent-ийн
HALTED дахин шалгалт хэвээр. Давхар илгээлтээс хамгаалах нь `client_order_id`
дедуп БИШ (доорх тайлбарыг хар) — нээлттэй order-ын хаалга ба цэвэр bielelt.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app import models
from app.api.attribution import LIVE_STATUSES
from app.broker.alpaca import is_crypto_symbol
from app.broker.models import (
    BrokerRejected,
    BrokerUnavailable,
    Money,
    Origin,
    OrderSide,
    OrderType,
    PositionSide,
    Qty,
    Quote,
    SystemState,
    TimeInForce,
    ValidatedOrder,
)
from app.execution.agent import ExecutionAgent
from app.system.state import StateMachine
from app.util.time import now_utc

HUNDRED = Decimal("100")
AGENT = Origin.RESEARCH_AGENT.value


@dataclass(frozen=True, slots=True)
class ExitIntent:
    symbol: str
    side: OrderSide
    qty: Qty
    price: Money
    reason: str


def evaluate_exits(
    positions: list,
    quotes: dict[str, Quote],
    agent_qty: dict[str, Qty],
    basis: dict[str, Money],
    entry_times: dict[str, datetime],
    now: datetime,
    *,
    stop_pct: Decimal,
    take_pct: Decimal,
    max_hold: timedelta,
    unverifiable_basis: frozenset[str] = frozenset(),
) -> list[ExitIntent]:
    """Цэвэр функц — I/O БАЙХГҮЙ. Бүх dict нь `position.symbol`-оор.

    `agent_qty` = агентын ӨӨРИЙН цэвэр bielelt. Түүнд байхгүй symbol нь
    хаагдахгүй: холимог гаралтай, эсвэл агент тэнд юу ч эзэмшдэггүй.

    `basis` = агентын ӨӨРИЙН өртөг. `position.avg_entry_price` нь операторын
    лоттой холилдсон дундаж — түүгээр trigger бодвол БУРУУ түвшинд буудна
    (өөрийн лот дээр -10% байхад ажиллахгүй, эсвэл ашигтай байхад stop идэгдэнэ).
    Өртгөө ОГТ мэдэхгүй symbol (`basis`-д ч, `unverifiable_basis`-д ч алга) нь
    хаагдахгүй — «мэдэхгүй нь зөвшөөрөл биш».

    `unverifiable_basis` = өртгөө ТООЦООД ч БАТАЛГААЖУУЛЖ чадаагүй symbol-ууд
    (`run_exits` тодорхойлно: Fill өгөгдөл дутуу, позиц БҮХЭЛДЭЭ ч манайх биш).
    Үүнийг «мэдэхгүй» шиг чимээгүй алгасвал яг тэр лот ХЭЗЭЭ Ч дахин
    шалгагдахгүй тул ЖИНХЭНЭ stop-loss мөнхөд дарагдана (round 4-ийн reconcile
    засвар үүнийг шинэ хаалгаар давтуулсан). Тиймээс энд алгасахгүй, харин
    хамгийн АЮУЛГҮЙ талыг сонгоно: false-positive stop-loss (шаардлагагүй
    хаалт) нь чимээгүй дарагдсан жинхэнэ stop-loss-ээс хамаагүй хямд —
    тиймээс ЗААВАЛ stop_loss-оор хаана (мөнгөнд, өөрөөр хэлбэл
    `entry_price`/`realized_pl`-д, ХЭРЭГЛЭХГҮЙ — зөвхөн trigger-т).
    """
    out: list[ExitIntent] = []
    for position in positions:
        quote = quotes.get(position.symbol)
        mine = agent_qty.get(position.symbol)
        entry_price = basis.get(position.symbol)
        # Үнэ мэдэхгүй ч, хуучирсан ч (`run_exits` хаячихсан), ширхэггүй ч
        # хаахгүй: «мэдэхгүй нь зөвшөөрөл биш» (R4-ийн зарчим).
        if quote is None or not mine or not position.qty:
            continue
        long = position.side is PositionSide.LONG
        entry = entry_times.get(position.symbol)
        if entry_price is not None:
            change = (quote.last - entry_price) / entry_price * HUNDRED
            pnl_pct = change if long else -change
            if pnl_pct <= -stop_pct:
                reason = "stop_loss"
            elif pnl_pct >= take_pct:
                reason = "take_profit"
            elif entry is not None and now - entry >= max_hold:
                reason = "max_hold"
            else:
                continue
        elif position.symbol in unverifiable_basis:
            reason = "stop_loss"  # батлагдаагүй өртөг → хамгийн аюулгүй тал
        else:
            continue  # огт мэдээлэл алга — жинхэнэ «мэдэхгүй»
        out.append(
            ExitIntent(
                symbol=position.symbol,
                side=OrderSide.SELL if long else OrderSide.BUY,
                qty=min(abs(position.qty), mine),
                price=quote.last,
                reason=reason,
            )
        )
    return out


def _norm(symbol: str) -> str:
    return symbol.replace("/", "")


def _entry_side(position) -> str:
    """Позицийг НЭЭСЭН тал: long → buy, short → sell."""
    return OrderSide.BUY.value if position.side is PositionSide.LONG else OrderSide.SELL.value


def _is_real_agent_fill(row) -> bool:
    """Мөр ЖИНХЭНЭ ширхэг/мөнгө хөдөлгөсөн эсэх (round 9).

    Эцсийн `status`-аар (`canceled`/`expired`/`failed` ч гэсэн) БИШ, `net`/
    эзэмшлийн loop-той (дээр/доор) АДИЛ зарчмаар — `filled_qty`-гаар шүүнэ.
    Хэсэгчлэн биелээд дараа нь цуцлагдсан (DAY order зах хаагдахад), эсвэл
    submit timeout-д `failed` гэж бичигдсэн ч Alpaca дээр биелсэн мөр БОДИТ
    ширхэг/үнээр хөдөлсөн — `status not in FILLED_STATUSES`-оор шүүвэл тэр
    мөр лотын хилээс (`lot_events`) ба сүүлийн ОРОЛТЫН цагаас (`latest`)
    ил алга болж, дараагийн лот хуучинтайгаа буруугаар пулддаг байсан."""
    return row.origin == AGENT and bool(row.filled_qty)


def _hidden_zero_crossing(net_before: Decimal, group: list[Decimal]) -> bool:
    """Ижил `filled_at`-тай бүлгийн ДОТОР лотын хил (цэвэр bielelt яг 0)
    нуугдаж болзошгүй эсэхийг шалгана (round 8). Зөвхөн бүлгийн НИЙТ дельта 0
    БИШ үед дуудагдана — 0 бол дотоод дараалал ямар ч байсан төгсгөлд 0 гэдэг
    аль хэдийн тодорхой (дуудагчид шалгасан).

    ЯГААД дотоод дараалал ТААМАГЛАХГҮЙ (жишээ нь Fill.id/Order.id-ээр
    эрэмбэлэхийг ОРХИСОН): `Fill.id` бол `mapped_column(SAUuid,
    default=uuid.uuid4)` (models.py) — санамсаргүй, бодит гүйцэтгэлийн
    дарааллыг ЗААХГҮЙ. Түүгээр эрэмбэлбэл өнөөдрийн ДЕТЕРМИНИСТИК "үргэлж
    алддаг" алдааг "санамсаргүй UUID-аас хамаарч заримдаа зөв, заримдаа буруу"
    болгоно — энэ нь ДООР, дээрдэлт БИШ.

    Тиймээс: бүлгийн аль нэг ХООСОН БУС, БҮХЭЛ БИШ дэд олонлог (subset) нь
    яг `-net_before`-тэй тэнцэх эсэхийг шалгана — тэнцвэл тэр дэд олонлогийг
    ЯМАР Ч дотоод дарааллаар эхэлж боловсруулсан ч (нийлбэр дараалалгүй тул
    адилхан) running яг 0 дайрна гэсэн үг, өөрөөр хэлбэл ЗАРИМ (үл мэдэгдэх)
    дараалал дор 0 нуугдаж байна. Бүлэг бага (нэг судалгааны мөчлөгийн
    хэдхэн захиалга) тул 2^n бүрэн хайлт хангалттай, тусгай сан хэрэггүй."""
    n = len(group)
    target = -net_before
    for mask in range(1, (1 << n) - 1):
        if sum((group[idx] for idx in range(n) if mask & (1 << idx)), Decimal(0)) == target:
            return True
    return False


async def run_exits(sessionmaker, settings, broker, publisher) -> None:
    """APScheduler-ийн job. Аль ч алдаа scheduler-ийг унагаах ёсгүй."""
    async with sessionmaker() as session:
        machine = StateMachine(
            session, wind_down_grace=settings.WIND_DOWN_GRACE, publisher=publisher
        )
        state = await machine.current()
        # Kill switch = ЗОГСОХ.
        if state.state is SystemState.HALTED:
            return
        try:
            positions = (await broker.get_positions()).data
        except BrokerUnavailable:
            return

        # Төлөвөөр ШҮҮХГҮЙ: хэсэгчлэн биелээд `canceled`/`expired` болсон, эсвэл
        # timeout-д `failed` гэж бичигдээд дараа нь fill нь ирсэн мөр нь БОДИТ
        # ширхэг хөдөлгөсөн. Тэднийг хаявал доорх цэвэр bielelt нь агентын
        # эзэмшлийг ИЛҮҮ харуулж, операторын ширхэг рүү халина.
        rows = (
            (await session.execute(select(models.Order))).scalars().all() if positions else []
        )
        # ЭЗЭМШИЛ нь ТҮҮХЭЭР БИШ, ЯГ ОДООГИЙН цэвэр bielelt-ээр тогтоно.
        # `Attribution` нь тухайн symbol дээр ХЭЗЭЭ НЭГЭН ЦАГТ fill хийсэн БҮХ
        # гаралтыг нэрлэдэг — түүгээр шүүвэл операторын аль эрт ХААГДСАН (цэвэр
        # 0, өнөөдөр нэг ч ширхэггүй) round-trip тэр symbol-ын stop-loss-ыг
        # ҮҮРД унтраана. Асуулт нь «ОДОО барьж буй ширхэг хэнийх вэ» — түүнд
        # гаралт тус бүрийн цэвэр bielelt л хариулна. UI-ийн түүхэн задаргаа
        # (`Attribution.mixed`/`pairs`) хэвээрээ, тэр өөр асуултын хариу.
        net: dict[tuple[str, str], Decimal] = {}
        for row in rows:
            # `filled_qty` нь broker-ийн БИЕЛСЭН тоо — арилжаагүй мөрд 0.
            key = (_norm(row.symbol), row.origin)
            delta = row.filled_qty if row.side == "buy" else -row.filled_qty
            net[key] = net.get(key, Decimal(0)) + delta
        agent_qty: dict[str, Qty] = {}
        for p in positions:
            symbol = _norm(p.symbol)
            own = net.get((symbol, AGENT), Decimal(0))
            own = own if p.side is PositionSide.LONG else -own
            # ЭЗЭМШИЛ нь ТҮҮХЭЭР (тухайн symbol дээр хэзээ нэгэн цагт fill хийсэн
            # БҮХ origin) БИШ, ЯГ ОДООГИЙН цэвэр bielelt-ээр: аль эрт ХААГДСАН
            # (цэвэр 0) операторын round-trip тэр symbol-ын stop-loss-ыг ҮҮРД
            # унтраах ёсгүй. Бусад origin бүрийн ОДООГИЙН цэвэр 0 бол л манайх.
            others_flat = all(
                qty == 0
                for (sym, origin), qty in net.items()
                if sym == symbol and origin != AGENT
            )
            if own > 0 and others_flat:
                agent_qty[p.symbol] = min(abs(p.qty), own)
        mine = [p for p in positions if p.symbol in agent_qty]
        if not mine:
            return

        # Нээлттэй order байгаа symbol-ыг хөндөхгүй — давхар хаалт. Локал
        # `orders` таблиц ГАНЦААРАА хангалтгүй: submit_order timeout-д орж
        # `failed` гэж бичигдсэн мөр Alpaca дээр амьд байж болно, мөн UI-аас
        # шууд тавьсан order локалд огт байхгүй. Тиймээс broker-ийн өөрийн
        # харцыг нэмнэ. Локал шүүлт нь ТЕРМИНАЛ БИШ БҮХ төлөвөөр явна:
        # `ExecutionAgent.submit` нь broker руу залгахаасаа ӨМНӨ `pending_risk`
        # мөрийг commit хийдэг тул тэр цонхонд унасан процесс мөрийг үүрд
        # `pending_risk`-д үлдээнэ — түүнийг «нээлттэй биш» гэвэл дараагийн
        # мөчлөг дахин зарна.
        open_symbols = {_norm(r.symbol) for r in rows if r.status in LIVE_STATUSES}
        try:
            open_symbols |= {_norm(o.symbol) for o in (await broker.get_open_orders()).data}
        except BrokerUnavailable:
            return  # нээлттэй order-ыг харж чадахгүй бол хаахгүй
        mine = [p for p in mine if _norm(p.symbol) not in open_symbols]
        if not mine:
            return

        # Позиц `BTCUSD` гэж ирдэг ч order/quote тал `BTC/USD` шаарддаг —
        # watchlist-ээр буцааж буулгана (T-99, эмпирик ажиглалт).
        # Буулгаж чадаагүй symbol-ыг ХӨНДӨХГҮЙ: `BTCUSD` хэвээр үлдвэл
        # `is_crypto_symbol` таньдаггүй тул crypto order DAY TIF-тэй явна —
        # системийг зогсоосон амьд ослын ЯГ хэлбэр.
        watch = {_norm(s): s for s in settings.research_symbols}
        mine = [p for p in mine if _norm(p.symbol) in watch]
        if not mine:
            return
        trade_symbol = {p.symbol: watch[_norm(p.symbol)] for p in mine}

        # ЛОТЫН ЭХЛЭЛ (round 7, round 10-д Fill рүү шилжсэн): symbol тус бүрээр
        # агентын ӨӨРИЙН биелэлтүүдийг цаг хугацаагаар дараалуулж, СҮҮЛД цэвэр
        # bielelt яг 0 болсон мөчийг ол. Symbol хаагдаад (цэвэр 0) ДАХИН
        # нээгдэхэд хуучин лотын Fill үнэ шинэ лотын жигнэсэн дундажид
        # холилдож, БУРУУ trigger өгдөг байсан нь round 7-ийн алдаа — тэр
        # мөчөөс ӨМНӨх ЮУГ Ч доор пул хийхгүй.
        #
        # round 10: дарааллыг `Order.filled_at`-аар (`rows`) БИШ, `Fill.filled_at`
        # -аар барина. `ingest.TradeUpdateIngestor.apply` `Order.filled_at`-ыг
        # ЗӨВХӨН ТЕРМИНАЛ статус (filled/canceled/expired) хүрэхэд бичдэг —
        # ХЭСЭГЧЛЭН биелэх БОДИТ мөчид БИШ. Хуучин лотыг ХААХ order ЭРТ
        # хэсэгчлэн биелээд гэвч ХОЖИМ (жишээ нь зах хаагдахад `canceled`)
        # терминал болвол `Order.filled_at` ХУДАЛ, ХОЖИМДСОН цагтай үлдэнэ —
        # тэр хоорондох мөчид шинэ лот бүрэн биелвэл дараалал БУРУУ болж, лотын
        # хил алга болно/буруу цэгт олдоно (round 7/8/9-ийг өөр хэлбэрээр
        # давтана). `Fill.filled_at` нь эцсийн статусаас үл хамааран ЯГ БОДИТ
        # гүйцэтгэлийн мөчид бичигддэг (`ingest._record_fill`, багана
        # `nullable=False`) — лотын дараалал ЗӨВХӨН үүгээр.
        fill_rows = (
            await session.execute(
                select(
                    models.Order.symbol,
                    models.Order.side,
                    models.Order.id,
                    models.Fill.qty,
                    models.Fill.price,
                    models.Fill.filled_at,
                )
                .join(models.Fill, models.Fill.order_id == models.Order.id)
                .where(models.Order.origin == AGENT)
            )
        ).all()
        covered_order_ids = {order_id for _, _, order_id, _, _, _ in fill_rows}

        lot_events: dict[str, list[tuple[datetime, Decimal]]] = {}
        for symbol, side, _order_id, qty, _price, filled_at in fill_rows:
            key = _norm(symbol)
            delta = qty if side == "buy" else -qty
            lot_events.setdefault(key, []).append((filled_at, delta))

        # `filled_qty>0` ч ЯМАР Ч Fill мөргүй захиалга (round 4-ийн reconcile
        # засвар — `BrokerOrder` нь fill бүрийн үнийг агуулдаггүй тул Fill мөр
        # үүсгэж ЧАДАХГҮЙ) энэ Fill-суурьтай дараалалд ОГТ ОРОХГҮЙ. Чимээгүй
        # орхивол лотын хил алдагдаж, хуучин/шинэ лот дахин холилдоно.
        # Түүнийг «Fill-ээр цаг тогтоох боломжгүй» гэдгээрээ шууд лотын хил
        # ТОДОРХОЙГҮЙ (round 8-ийн яг тэр аюулгүй зам) гэж үзнэ — доорх
        # zero-crossing огт оролдохгүй.
        ambiguous_lot: set[str] = {
            _norm(row.symbol)
            for row in rows
            if _is_real_agent_fill(row) and row.id not in covered_order_ids
        }
        lot_start: dict[str, datetime] = {}
        # round 8: дараах бүлэглэлт зөвхөн бүлгийн ТӨГСГӨЛийн НИЙТ дельта 0 мөн
        # эсэхийг шалгадаг байсан — хуучин лот ХААГДАХ БОЛОН шинэ лот НЭЭГДЭХ
        # хоёул ЯГ нэг `filled_at`-тай (жинхэнэ tie) үед бүлгийн нийт дельта
        # ихэвчлэн 0 БИШ (шинэ лотын хэмжээ) тул 0 хэзээ ч бүртгэгдэхгүй,
        # хуучин лотын Fill шинэ лоттой чимээгүй холилддог байсан (round 7-ийн
        # ЯГ ТЭР алдааг давтана). Доор тийм tie-г ТОДОРХОЙГҮЙ (`ambiguous_lot`)
        # гэж ялгаж, лот-scoped Fill дундаж ОГТ бодохгүй — round 5/6-ийн
        # батлагдаагүй fallback-руу унана.
        for symbol, events in lot_events.items():
            if symbol in ambiguous_lot:
                continue  # дээрх Fill-гүй coverage шалгалт аль хэдийн татгалзсан
            events.sort(key=lambda e: e[0])
            running = Decimal(0)
            last_zero: datetime | None = None
            ambiguous = False
            i = 0
            while i < len(events):
                ts = events[i][0]
                j = i
                group: list[Decimal] = []
                # Ижил ЦАГ бүхий мөрүүдийг НЭГ бүлэг болгож ЦУГ боловсруулна:
                # тэдгээрийн ДОТООД (аль нь эхэлж биелсэн бэ) дараалал
                # мэдэгдэхгүй.
                while j < len(events) and events[j][0] == ts:
                    group.append(events[j][1])
                    j += 1
                group_sum = sum(group, Decimal(0))
                if running + group_sum == 0:
                    # Бүлгийн НИЙТ дельта яг 0 → дотоод дараалал ямар ч байсан
                    # энэ цаг мөчийн ТӨГСГӨЛД цэвэр bielelt яг 0 — ЭНЭ
                    # тодорхой, өмнөх ямар ч тодорхойгүй байдлыг (хэрэв байсан)
                    # ардаа орхино (одоогийн лот ЭНЭ мөчөөс хойш эхэлнэ).
                    last_zero = ts
                    ambiguous = False
                elif _hidden_zero_crossing(running, group):
                    # Нийт дельта 0 БИШ ч дотоод дараалал мэдэгдэхгүй тул ЗАРИМ
                    # дараалал дор 0 нуугдаж байж болзошгүй (round 7-ийн жинхэнэ
                    # алдаа — доорх `_hidden_zero_crossing` docstring-д яагаад
                    # UUID-аар "шийдэхгүй" болохыг тайлбарлав).
                    ambiguous = True
                running += group_sum
                i = j
            if ambiguous:
                ambiguous_lot.add(symbol)
            elif last_zero is not None:
                lot_start[symbol] = last_zero

        # МАНАЙ өртөг: агентын ӨӨРИЙН оролтын биелэлтүүдийн жигнэсэн дундаж.
        # `position.avg_entry_price` нь операторын лоттой холилдсон — trigger-ыг
        # түүгээр бодвол өөрийн лот дээрх алдагдал stop-д хүрэхгүй, эсвэл ашигтай
        # байхад stop идэгдэнэ. `fills` нь Alpaca-ийн мэдээлсэн бодит үнэ (AC-1).
        cost: dict[tuple[str, str], list[Decimal]] = {}
        # `fill_net` = ГАНЦ symbol-оор (тал харгалзахгүй), ОДООГИЙН лотод
        # хамаарах Fill-үүдийн цэвэр нийлбэр — `agent_qty`-г бодсон яг тэр л
        # buy(+)/sell(-) конвенц. Өртгийн `cost` (доор) зөвхөн ОРОЛТЫН тал
        # (buy/long, sell/short) — тэр хэвээрээ ЗӨВ (дундаж өртөг зарсны дараа
        # ч өөрчлөгддөггүй), ГАГЦХҮҮ бүрэн бүтэн эсэхийг шалгах харьцуулалт
        # GROSS байсан нь round 5-ийн алдаа. round 10: дээрх lot_events-тэй ЯГ
        # ТЭР `fill_rows`-ийг дахин хэрэглэнэ — шинэ query ХЭРЭГГҮЙ.
        fill_net: dict[str, Decimal] = {}
        for symbol, side, _order_id, qty, price, filled_at in fill_rows:
            norm_symbol = _norm(symbol)
            if norm_symbol in ambiguous_lot:
                # Лотын хил ТОДОРХОЙГҮЙ (дээр) — энд ЯМАР Ч Fill цуглуулбал
                # хуучин/шинэ лот дахин холилдоно. Fill өгөгдлийг бүр мөсөн
                # ДУТУУ мэт үзнэ: доорх `cost.get(...)` нь `None` буцааж,
                # round 5/6-ийн батлагдаагүй fallback (бүхэл позиц бол broker
                # дундаж, эс бөгөөс unverifiable force-stop) руу унана —
                # тусдаа зэрэгцээ зам ШИНЭЭР зохиохгүй.
                continue
            start = lot_start.get(norm_symbol)
            if start is not None and filled_at <= start:
                # `start` бол хуучин лот ЯГ 0 болсон (хаагдсан) мөчийн БОДИТ
                # Fill цаг — тэр мөчийн ӨӨРИЙН fill (хаах гараа) ХАМААРАХГҮЙ,
                # ЗӨВХӨН ДАРАА нь ирэх fill-үүд л шинэ лотынх (`<=` — эх мөчийг
                # хассанаар цэвэр bielelt-ийн шалгалт бохирдохгүй). Энд
                # хүрсэн symbol нь `ambiguous_lot`-д ОРООГҮЙ (дээр аль хэдийн
                # `continue`-дсэн) тул `start` (хэрэв тогтсон бол) ямар ч
                # ижил цагийн tie-гүй, ганц утгатай хил мөн.
                continue
            acc = cost.setdefault((norm_symbol, side), [Decimal(0), Decimal(0)])
            acc[0] += qty
            acc[1] += qty * price
            delta = qty if side == "buy" else -qty
            fill_net[norm_symbol] = fill_net.get(norm_symbol, Decimal(0)) + delta
        basis: dict[str, Money] = {}
        unverifiable: set[str] = set()
        for p in mine:
            symbol = _norm(p.symbol)
            acc = cost.get((symbol, _entry_side(p)))
            net_fill = fill_net.get(symbol, Decimal(0))
            net_fill = net_fill if p.side is PositionSide.LONG else -net_fill
            # Fill-ээр бүрхэгдсэн ЦЭВЭР (buy-sell) тоо ЯГ агентын одоогийн
            # цэвэр bielelt-тэй (`agent_qty`, дээр аль хэдийн бодогдсон) тэнцэх
            # ёстой — GROSS buy-тоогоор (round 5-ийн алдаа) БИШ: агент өмнө нь
            # ХЭСЭГЧИЛЖ гарсан (жинхэнэ, зохион байгуулалттай ажиллагаа) бол
            # GROSS нь NET-ээс үргэлж их тул бүрэн бүтэн Fill өгөгдлийг ч
            # буруугаар «дутуу» гэж үзнэ. Тэнцэхгүй бол (жишээ нь: reconcile
            # broker-ийн үнэнээр `filled_qty`-г засаад ч харгалзах Fill мөр
            # үүсгэж чадаагүй лот — `BrokerOrder` нь нэг fill-ийн дундаж үнэ
            # агуулдаггүй тул ЧАДАХГҮЙ) Fill өгөгдөл ДУТУУ — хэсэгчилсэн
            # дундаж чимээгүй ХЭРЭГЛЭХГҮЙ, учир нь дутуу лотыг орхигдуулж
            # жинхэнэ дундажаас БУРУУ тал руу гажина.
            if acc and net_fill == agent_qty[p.symbol]:
                basis[p.symbol] = acc[1] / acc[0]
            elif agent_qty[p.symbol] == abs(p.qty) and p.avg_entry_price:
                # Fill бүрхэлгүй ч позиц БҮХЭЛДЭЭ манайх бол broker-ийн дундаж
                # ЯГ манай өртөг мөн.
                basis[p.symbol] = p.avg_entry_price
            else:
                # Аль ч арга батлагдсангүй — өртөг ТОДОРХОЙГҮЙ. `entry_price`/
                # `realized_pl`-д хэзээ ч хэрэглэхгүй (доор `basis.get`), гэхдээ
                # `evaluate_exits` үүнийг чимээгүй алгасахгүй — `unverifiable`.
                unverifiable.add(p.symbol)
        mine = [p for p in mine if p.symbol in basis or p.symbol in unverifiable]
        if not mine:
            return

        # Барьсан хугацаа: ӨӨРСДИЙН сүүлийн ОРОЛТООС хойш (лотын FIFO бүтцийг
        # мэдэхгүй тул хамгийн сүүлийн бодит оролт л баримт). Операторын худалдан
        # авалт, эсвэл манай ӨӨРИЙН хэсэгчилсэн ГАРАЛТ нь оролт БИШ — тэднийг
        # тоовол max_hold цаг нь мөчлөг бүрт урагшилж, хугацаат хаалт хэзээ ч
        # ажиллахгүй.
        #
        # round 10 audit: дээрх лотын хилийн ЯГ АДИЛ шалтгаанаар (`Order.filled_at`
        # нь `ingest.apply`-д ЗӨВХӨН ТЕРМИНАЛ статус дээр бичигддэг, ХЭСЭГЧЛЭН
        # биелсэн БОДИТ мөчид БИШ) энд ч мөн адил `Order.filled_at`-аар «сүүлийн
        # оролт» тогтоовол ХОЖИМДСОН статус (жишээ нь зах хаагдахад хожим
        # `canceled`) ирэхэд max_hold цаг ХУДЛААР шинэчлэгдэж, жинхэнэ хугацаат
        # хаалт ХЭЗЭЭ Ч ажиллахгүй байх аюултай. Тиймээс Fill-ээр бүрхэгдсэн
        # order-уудад дээрх `fill_rows`-ийн ЯГ БОДИТ `Fill.filled_at`-ыг
        # хэрэглэнэ (шинэ query ХЭРЭГГҮЙ); Fill МӨРГҮЙ (round 4 reconcile shape)
        # order-д л хуучин fallback (`filled_at or submitted_at`) үлдэнэ — тэдэнд
        # илүү сайн мэдээлэл байхгүй.
        latest: dict[str, datetime] = {}
        entry_sides = {_norm(p.symbol): _entry_side(p) for p in mine}
        for symbol, side, _order_id, _qty, _price, filled_at in fill_rows:
            key = _norm(symbol)
            if side != entry_sides.get(key):
                continue
            latest[key] = max(filled_at, latest[key]) if key in latest else filled_at
        for row in rows:
            if row.id in covered_order_ids:
                continue  # дээр Fill.filled_at-аар аль хэдийн орсон
            key = _norm(row.symbol)
            if not _is_real_agent_fill(row) or row.side != entry_sides.get(key):
                continue
            ts = row.filled_at or row.submitted_at
            latest[key] = max(ts, latest[key]) if key in latest else ts
        entry_times = {
            p.symbol: latest[_norm(p.symbol)] for p in mine if _norm(p.symbol) in latest
        }

        quotes: dict[str, Quote] = {}
        for p in mine:
            try:
                result = await broker.get_quote(trade_symbol[p.symbol])
            except BrokerUnavailable:
                continue  # энэ symbol л алгасна — үнийг ХЭЗЭЭ Ч таамаглахгүй
            # Хуучирсан үнэ = үнэгүй. Зогссон тикер/амралтын өдөр/гацсан feed
            # дээр market stop-loss нь байхгүй үнийн эсрэг буудна (r4-ийн адил).
            if result.stale:
                continue
            quotes[p.symbol] = result.data

        now = now_utc()
        intents = evaluate_exits(
            mine,
            quotes,
            agent_qty,
            basis,
            entry_times,
            now,
            stop_pct=settings.STOP_LOSS_PCT,
            take_pct=settings.TAKE_PROFIT_PCT,
            max_hold=timedelta(hours=settings.MAX_HOLD_HOURS),
            unverifiable_basis=frozenset(unverifiable),
        )
        if not intents:
            return

        agent = ExecutionAgent(session, broker, machine, mode=settings.mode.value)
        for intent in intents:
            symbol = trade_symbol[intent.symbol]
            order = ValidatedOrder(
                symbol=symbol,
                side=intent.side,
                qty=intent.qty,
                order_type=OrderType.MARKET,
                time_in_force=(
                    TimeInForce.GTC if is_crypto_symbol(symbol) else TimeInForce.DAY
                ),
                limit_price=None,
                stop_price=None,
                # Цагаар түлхүүрлэсэн нь САНААТАЙ: мөчлөг бүр ШИНЭ id авна.
                # Санаагаар (reason+qty) түлхүүрлэвэл нэг удаа татгалзсан stop-
                # loss дахин ХЭЗЭЭ Ч оролдохгүй. Давхар илгээлтийг ExecutionAgent
                # -ийн дедуп биш, нээлттэй order-ын хаалга ба bielelt барина.
                client_order_id=f"exit-{_norm(symbol)}-{int(now.timestamp()) // 60}",
                risk_evaluation={"reduce_only_exit": intent.reason},
            )
            try:
                # `entry_price` нь submit-ЭЭС ӨМНӨ мөртэй хамт commit хийгдэнэ:
                # crypto market order-ын fill нь broker-ийн round trip дотор
                # ирж чаддаг тул дараа нь бичвэл `ingest` хоцорно. `realized_pl`
                # -ыг ЗӨВХӨН `ingest` бодит fill дээр бичнэ (тооцоо ≠ мөнгө).
                await agent.submit(
                    order,
                    origin=Origin.RESEARCH_AGENT,
                    origin_detail=f"exit:{intent.reason}",
                    actor="system:exits",
                    # МАНАЙ ӨӨРИЙН өртөг (дээр бодсон) — `avg_entry_price` БИШ.
                    # Тиймээс хэсэгчилсэн эзэмшил дээр ч realized_pl нь бодитой:
                    # манай лотын үнээс манай лотын гаралт хасагдана. `unverifiable`
                    # symbol-д `basis`-д огт орохгүй тул `.get` нь `None` буцаана —
                    # батлагдаагүй өртгөөр `entry_price`/`realized_pl` ХЭЗЭЭ Ч
                    # бичихгүй (зөвхөн trigger дээр force stop_loss хэрэглэсэн).
                    entry_price=basis.get(intent.symbol),
                )
            except (BrokerRejected, BrokerUnavailable):
                continue  # нэг symbol унах нь бусдын хаалтыг зогсоохгүй
