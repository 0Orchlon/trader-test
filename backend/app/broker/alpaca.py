"""`AlpacaAdapter` — `BrokerPort`-ийн цорын ганц хэрэгжүүлэлт (LLD §7).

Дүрмүүд:
- Alpaca-ийн хариу **зөвхөн буулгагдана**, дахин тооцогдохгүй (AC-1).
  `market_value` нь Alpaca-аас; `qty × price` ХЭЗЭЭ Ч тооцогдохгүй.
- Хүрэхгүй бол `BrokerUnavailable` — кэшээс хуучин утга буцаах зам БАЙХГҮЙ.
- Retry: зөвхөн УНШИХ дуудалтад (3 оролдлого). `submit_order` нь ЗӨВХӨН
  сүлжээний timeout дээр, ижил `client_order_id`-аар дахин илгээгдэнэ.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import httpx

from app.broker.models import (
    Account,
    BrokerOrder,
    BrokerRejected,
    BrokerUnavailable,
    Envelope,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionSide,
    Quote,
    Source,
    SystemState,
    Tick,
    TimeInForce,
    TradeUpdate,
    ValidatedOrder,
)
from app.config.egress import check_egress
from app.config.mode import TradingMode, broker_host
from app.util.time import now_utc, parse_iso

DATA_HOST = "data.alpaca.markets"
READ_ATTEMPTS = 3

#: Alpaca-ийн `POST /v2/orders`-д броker-ийн ТАТГАЛЗАЛ гэж үзэх статусууд.
#: 403 = wash trade / buying power, 422 = хүчингүй параметр. Бүгд «Alpaca
#: хариулсан» гэсэн үг тул `BrokerUnavailable` БИШ. 401 (түлхүүр), 429
#: (rate limit), 5xx нь ЖИНХЭНЭ хүрэхгүй байдал — тэднийг оруулахгүй.
REJECT_STATUSES = frozenset({400, 403, 409, 422})

#: Alpaca-ийн order статусыг домэйны статус руу буулгах хүснэгт. Таарахгүй
#: статусыг ТААМАГЛАХГҮЙ — `failed` гэж тэмдэглээд ил үлдээнэ.
_STATUS_MAP = {
    "new": OrderStatus.ACCEPTED,
    "accepted": OrderStatus.ACCEPTED,
    "pending_new": OrderStatus.ACCEPTED,
    "partially_filled": OrderStatus.PARTIALLY_FILLED,
    "filled": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELED,
    "cancelled": OrderStatus.CANCELED,
    "expired": OrderStatus.EXPIRED,
    "rejected": OrderStatus.REJECTED,
    "done_for_day": OrderStatus.EXPIRED,
}


def _alpaca_error(response: httpx.Response) -> tuple[str | None, str]:
    """Alpaca-ийн алдааны бие → `(code, message)`. Задлагдахгүй бол түүхийгээр."""
    try:
        payload = response.json()
    except ValueError:
        return None, response.text or f"HTTP {response.status_code}"
    if not isinstance(payload, dict):
        return None, str(payload)
    code = payload.get("code")
    return (str(code) if code is not None else None), str(payload.get("message", payload))


def _dec(value: Any) -> Decimal:
    if value is None:
        raise BrokerUnavailable("Alpaca-ийн хариунд шаардлагатай тоон талбар байхгүй")
    return Decimal(str(value))


class AlpacaAdapter:
    def __init__(
        self,
        *,
        mode: TradingMode,
        api_key: str | None,
        api_secret: str | None,
        client: httpx.AsyncClient | None = None,
        stale_after_seconds: int = 5,
        ws_connect=None,
    ) -> None:
        self.mode = mode
        self.host = broker_host(mode)
        self.base_url = f"https://{self.host}"
        self.stale_after_seconds = stale_after_seconds
        self._headers = {
            "APCA-API-KEY-ID": api_key or "",
            "APCA-API-SECRET-KEY": api_secret or "",
        }
        self._client = client
        self._owns_client = client is None
        self._ws_connect = ws_connect
        self._system_state_provider = lambda: SystemState.HALTED
        self._api_reporter = None

    # --- дэд бүтэц ---

    @property
    def source(self) -> Source:
        return Source.ALPACA_LIVE if self.mode is TradingMode.LIVE else Source.ALPACA_PAPER

    def bind_system_state(self, provider) -> None:
        """Envelope-д бичих `system_state`-ийн эх сурвалж (LLD §4)."""
        self._system_state_provider = provider

    def bind_api_reporter(self, reporter) -> None:
        """`api_error_rate`-ийн ЭХ СУРВАЛЖ (LLD §15.2, B-1).

        REST дуудалт БҮР (уншилт, `submit_order`, `cancel_order`) үр дүнгээ
        энд мэдэгдэнэ. Тоолуургүй метрик нь «0.0000 · унаагүй» гэж ногоон
        харагддаг байв — Alpaca бүрэн унасан үед ч.
        """
        self._api_reporter = reporter

    async def _report(self, ok: bool) -> None:
        """Нэг ЛОГИК дуудалт = нэг мөр (retry-ийн оролдлогууд БИШ)."""
        if self._api_reporter is not None:
            await self._api_reporter(ok)

    def _client_or_new(self) -> httpx.AsyncClient:
        if self._client is None:
            # ponytail: netcapital-ийн корпорацийн proxy нь paper-ийн
            # гадагш гарах HTTPS-ийг TLS inspection хийдэг тул PAPER
            # горимд verify унтраасан (dev-ийн зам БОЛОХ). LIVE горимд
            # ХЭЗЭЭ Ч унтраахгүй — жинхэнэ мөнгөтэй холбогдох тул MITM
            # эрсдэлийг зогсоох ёстой. Proxy-г уншсан бол унтраа.
            verify = self.mode is not TradingMode.PAPER
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=10.0, verify=verify)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()

    def _envelope(self, data, *, as_of=None, source=None, stale=False) -> Envelope:
        return Envelope(
            data=data,
            source=source or self.source,
            as_of=as_of or now_utc(),
            stale=stale,
            system_state=self._system_state_provider(),
        )

    async def _read(self, url: str, **kwargs) -> Any:
        """Унших дуудалт — exponential backoff, 3 оролдлого."""
        check_egress(url if url.startswith("http") else self.base_url + url)
        last_exc: Exception | None = None
        for attempt in range(READ_ATTEMPTS):
            try:
                response = await self._client_or_new().get(url, headers=self._headers, **kwargs)
                response.raise_for_status()
                payload = response.json(parse_float=Decimal)
            except (httpx.HTTPError, httpx.InvalidURL) as exc:
                last_exc = exc
                if attempt < READ_ATTEMPTS - 1:
                    await asyncio.sleep(0.01 * (2**attempt))
            else:
                await self._report(True)
                return payload
        await self._report(False)
        raise BrokerUnavailable(f"Alpaca хүрэхгүй: {url}") from last_exc

    # --- унших зам ---

    async def get_account(self) -> Envelope[Account]:
        raw = await self._read("/v2/account")
        account = Account(
            account_id=str(raw["id"]),
            equity=_dec(raw["equity"]),
            cash=_dec(raw["cash"]),
            buying_power=_dec(raw["buying_power"]),
            last_equity=_dec(raw["last_equity"]) if raw.get("last_equity") is not None else None,
            pattern_day_trader=bool(raw.get("pattern_day_trader", False)),
            day_trade_count=int(raw.get("daytrade_count", 0)),
            trading_blocked=bool(raw.get("trading_blocked", False)),
        )
        return self._envelope(account)

    async def get_clock(self) -> dict:
        """Зах зээл нээлттэй эсэх (`GET /v2/clock`). Risk/Tool contract-д
        БАЙХГҮЙ — зөвхөн `agents/runner.py`-ийн зардал хэмнэх урьдчилсан
        шалгалт, LLM-д харагдахгүй."""
        raw = await self._read("/v2/clock")
        return {"is_open": bool(raw.get("is_open", False))}

    async def get_positions(self) -> Envelope[list[Position]]:
        raw = await self._read("/v2/positions")
        positions = [
            Position(
                symbol=row["symbol"],
                qty=_dec(row["qty"]),
                side=PositionSide(row["side"]),
                avg_entry_price=_dec(row["avg_entry_price"]),
                # AC-1: Alpaca-ийн хэлснийг л авна.
                market_value=_dec(row["market_value"]),
                unrealized_pl=_dec(row["unrealized_pl"]),
            )
            for row in raw
        ]
        return self._envelope(positions)

    async def get_open_orders(self) -> Envelope[list[BrokerOrder]]:
        raw = await self._read("/v2/orders", params={"status": "open"})
        return self._envelope([self._map_order(row) for row in raw])

    async def get_quote(self, symbol: str) -> Envelope[Quote]:
        raw = await self._read(f"https://{DATA_HOST}/v2/stocks/{symbol}/snapshot")
        quote = raw.get("latestQuote")
        trade = raw.get("latestTrade")
        if not quote or not trade:
            # Байхгүйг ТААМАГЛАХГҮЙ — mid тооцох нь зохиосон үнэ болно.
            raise BrokerUnavailable(f"{symbol}: quote эсвэл trade байхгүй")
        quote_ts = parse_iso(quote["t"])
        stale = (now_utc() - quote_ts).total_seconds() > self.stale_after_seconds
        return self._envelope(
            Quote(
                symbol=raw.get("symbol", symbol),
                bid=_dec(quote["bp"]),
                ask=_dec(quote["ap"]),
                last=_dec(trade["p"]),
                quote_ts=quote_ts,
            ),
            as_of=quote_ts,
            stale=stale,
        )

    # --- бичих зам ---

    async def submit_order(self, req: ValidatedOrder) -> BrokerOrder:
        """ЭНЭ метод нь `app.execution`-аас л дуудагдана (статик хаалга R-1)."""
        check_egress(self.base_url + "/v2/orders")
        body: dict[str, Any] = {
            "symbol": req.symbol,
            "side": req.side.value,
            "qty": str(req.qty),
            "type": req.order_type.value,
            "time_in_force": req.time_in_force.value,
            "client_order_id": req.client_order_id,
        }
        if req.limit_price is not None:
            body["limit_price"] = str(req.limit_price)
        if req.stop_price is not None:
            body["stop_price"] = str(req.stop_price)
        try:
            response = await self._client_or_new().post(
                "/v2/orders", json=body, headers=self._headers
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            # Ижил `client_order_id` — Alpaca тал дээр давхардахгүй (LLD §9.2).
            try:
                response = await self._client_or_new().post(
                    "/v2/orders", json=body, headers=self._headers
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as retry_exc:
                # Дахин илгээлтэд Alpaca ХАРИУЛСАН — татгалзал ч байж болно.
                raise await self._submit_error(retry_exc) from retry_exc
            except httpx.HTTPError as retry_exc:
                await self._report(False)
                raise BrokerUnavailable("submit_order timeout, дахин илгээлт амжилтгүй") from (
                    retry_exc or exc
                )
        except httpx.HTTPStatusError as exc:
            # Alpaca ХАРИУЛСАН — түүнийг «хүрэхгүй» гэж хэлэх нь худал
            # оношилгоо (N-3). Retry энд ч БАЙХГҮЙ.
            raise await self._submit_error(exc) from exc
        except httpx.HTTPError as exc:
            # Сүлжээний давхарга — хариу огт ирээгүй.
            await self._report(False)
            raise BrokerUnavailable(f"submit_order амжилтгүй: {exc}") from exc
        await self._report(True)
        return self._map_order(response.json(parse_float=Decimal))

    async def _submit_error(self, exc: httpx.HTTPStatusError) -> Exception:
        """HTTP статус → татгалзал эсвэл уналт (N-3, LLD §15.2)."""
        status = exc.response.status_code
        if status not in REJECT_STATUSES:
            await self._report(False)
            return BrokerUnavailable(f"submit_order амжилтгүй: {exc}")
        # Хариулсан broker нь АМЬД: `api_error_rate` нь хүрэхгүй байдлын
        # метрик тул татгалзал түүнийг ахиулахгүй.
        await self._report(True)
        code, message = _alpaca_error(exc.response)
        return BrokerRejected(message, broker_code=code, status=status)

    async def cancel_order(self, broker_order_id: str) -> None:
        check_egress(self.base_url + f"/v2/orders/{broker_order_id}")
        try:
            response = await self._client_or_new().delete(
                f"/v2/orders/{broker_order_id}", headers=self._headers
            )
            if response.status_code not in (200, 204, 207):
                response.raise_for_status()
        except httpx.HTTPError as exc:
            await self._report(False)
            raise BrokerUnavailable(f"cancel_order амжилтгүй: {exc}") from exc
        await self._report(True)

    # --- буулгалт ---

    def _map_order(self, raw: dict) -> BrokerOrder:
        return BrokerOrder(
            broker_order_id=str(raw["id"]),
            client_order_id=str(raw.get("client_order_id", "")),
            symbol=raw["symbol"],
            side=OrderSide(raw["side"]),
            qty=_dec(raw["qty"]),
            filled_qty=Decimal(str(raw.get("filled_qty", "0"))),
            order_type=OrderType(raw.get("type", raw.get("order_type", "market"))),
            time_in_force=TimeInForce(raw.get("time_in_force", "day")),
            status=_STATUS_MAP.get(str(raw.get("status")), OrderStatus.FAILED),
            submitted_at=parse_iso(raw["submitted_at"]) if raw.get("submitted_at") else now_utc(),
            filled_at=parse_iso(raw["filled_at"]) if raw.get("filled_at") else None,
            limit_price=Decimal(str(raw["limit_price"])) if raw.get("limit_price") else None,
            stop_price=Decimal(str(raw["stop_price"])) if raw.get("stop_price") else None,
        )

    def map_trade_update(self, raw: dict) -> TradeUpdate:
        order = raw.get("order", {})
        return TradeUpdate(
            event=str(raw.get("event", "")),
            broker_order_id=str(order.get("id", "")),
            client_order_id=str(order.get("client_order_id", "")),
            status=_STATUS_MAP.get(str(order.get("status")), OrderStatus.FAILED),
            filled_qty=Decimal(str(order.get("filled_qty", "0"))),
            filled_avg_price=(
                Decimal(str(order["filled_avg_price"]))
                if order.get("filled_avg_price")
                else None
            ),
            ts=parse_iso(raw["timestamp"]) if raw.get("timestamp") else now_utc(),
            raw=raw,
        )

    # --- урсгалууд ---

    async def stream_market_data(self, symbols: list[str]) -> AsyncIterator[Tick]:  # pragma: no cover
        raise NotImplementedError("market-data урсгал энэ хувилбарт холбогдоогүй")
        yield  # энэ мөр нь методыг async generator болгоно (хүрэхгүй)

    @property
    def stream_url(self) -> str:
        return f"wss://{self.host}/stream"

    async def stream_trade_updates(self) -> AsyncIterator[TradeUpdate]:
        """Alpaca-ийн `trade_updates` суваг (docs «Websocket Streaming»).

        Дараалал: `auth` → `authorization`/`authorized` → `listen` →
        `listening` → үйл явдлууд. Гажсан аль ч алхам нь `BrokerUnavailable`
        — «чимээгүй хүлээх» холболт нь хамгийн аюултай хэлбэр (LLD §12).

        paper нь frame-ийг **binary**-ээр илгээдэг тул bytes ч, str ч
        ирж болно; `json.loads` хоёуланг нь уншина.
        """
        if not self._headers["APCA-API-KEY-ID"] or not self._headers["APCA-API-SECRET-KEY"]:
            raise BrokerUnavailable("Alpaca-ийн түлхүүр байхгүй — WS нээгдэхгүй")
        url = self.stream_url
        check_egress(url)
        async with self._connect(url) as socket:
            await socket.send(
                json.dumps(
                    {
                        "action": "auth",
                        "key": self._headers["APCA-API-KEY-ID"],
                        "secret": self._headers["APCA-API-SECRET-KEY"],
                    }
                )
            )
            listening = False
            async for frame in socket:
                message = json.loads(frame)
                if message.get("action") == "error":
                    raise BrokerUnavailable(
                        f"Alpaca WS алдаа: {message.get('data', {}).get('error_message')}"
                    )
                stream = message.get("stream")
                if stream == "authorization":
                    status = message.get("data", {}).get("status")
                    if status != "authorized":
                        raise BrokerUnavailable(f"Alpaca WS authorization: {status}")
                    if not listening:
                        listening = True
                        await socket.send(
                            json.dumps(
                                {"action": "listen", "data": {"streams": ["trade_updates"]}}
                            )
                        )
                elif stream == "trade_updates":
                    yield self.map_trade_update(message.get("data", {}))
                # Бусад суваг (`listening`, …) нь арилжааны үйл явдал БИШ —
                # ТААМАГЛАХГҮЙ, чимээгүй алгасна.

    def _connect(self, url: str):
        """WS холболт. Тест нь `ws_connect`-оор оронд нь тавина."""
        if self._ws_connect is not None:
            return self._ws_connect(url)
        from websockets.asyncio.client import connect  # pragma: no cover - сүлжээ

        # ponytail: REST-тэй ижил шалтгаанаар PAPER-т verify унтраана.
        if self.mode is TradingMode.PAPER:
            import ssl

            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return connect(url, ssl=ctx)  # pragma: no cover - сүлжээ
        return connect(url)  # pragma: no cover - сүлжээ
