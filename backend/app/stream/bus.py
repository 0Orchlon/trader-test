"""Event bus — Redis pub/sub + WS fan-out-ийн суурь (T-04, LLD §12, AC-2, AC-14).

**Backpressure бодлого нь энд НЭГ газар тодорхойлогдоно** (asyncapi §description):

- `system`            — ХЭЗЭЭ Ч хаягдахгүй. Хязгааргүй дараалал.
- `orders`            — дарааллаараа хадгалагдана.
- `agent-decisions`   — дарааллаараа хадгалагдана.
- `ticks:{symbol}`    — ачаалал дор хаягдана (сүүлийнх нь ялна).

Яагаад `system` тусдаа: kill switch-ийн мэдэгдэл tick-ийн үерт живэх нь
«чимээгүй уналт» — operator зогссон гэдгээ мэдэхгүй үлдэнэ.

Redis нь СОНГОЛТ. `REDIS_URL` байвал ижил мессежийг Redis рүү давхар нийтэлнэ
(олон process-ийн fan-out); байхгүй бол process-дотоод bus дангаараа ажиллана.
Redis унах нь мессеж алдагдахаас өөр үр дагаваргүй — төлөв нь Postgres-д
(`plan.md` R-10).
"""
from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass
from itertools import count
from typing import Any
from uuid import uuid4

from app.util.time import now_utc, to_iso

CHANNEL_SYSTEM = "system"
CHANNEL_ORDERS = "orders"
CHANNEL_DECISIONS = "agent-decisions"
CHANNEL_TICKS = "ticks"

#: Хаягдаж БОЛОХ сувгууд. Бусад нь бүрэн хүргэгдэнэ.
DROPPABLE = (CHANNEL_TICKS,)

#: Redis-ийн утсан дээрх техник талбар — нийтлэгч instance-ийн тэмдэг.
#: Локал хүргэлтийн ӨМНӨ хасагдана: WS схемд (asyncapi) энэ талбар БАЙХГҮЙ.
SRC_FIELD = "_src"

DEFAULT_TICK_BUFFER = 256
#: Дахин холбогдоход сүүлийн хэдэн `system` мессежийг давтах вэ (AC-14 DoD б).
SYSTEM_REPLAY = 1


@dataclass(frozen=True, slots=True)
class Message:
    channel: str
    payload: dict[str, Any]


def _as_text(value: Any) -> str:
    """redis-py нь `decode_responses`-ээс хамаарч bytes эсвэл str буцаана."""
    return value.decode() if isinstance(value, bytes) else str(value)


def _droppable(channel: str) -> bool:
    return channel.split(":", 1)[0] in DROPPABLE


class Subscriber:
    """Нэг WS клиентийн дараалал.

    Хоёр дараалалтай: `_priority` (`system`, хязгааргүй) ба `_normal`
    (хаягдаж болох). `get()` нь ҮРГЭЛЖ `system`-ийг эхэлж өгнө — ачаалал
    дор ч зогсоолтын мэдэгдэл түрүүлнэ.
    """

    def __init__(self, channels: list[str], tick_buffer: int) -> None:
        self.channels = tuple(channels)
        self._priority: deque[Message] = deque()
        self._normal: deque[Message] = deque(maxlen=tick_buffer)
        self._ordered: deque[Message] = deque()
        self._wake = asyncio.Event()
        self.dropped = 0

    def matches(self, channel: str) -> bool:
        for candidate in self.channels:
            if candidate == channel:
                return True
            # `ticks` захиалга нь `ticks:AAPL`-ийг хамарна.
            if channel.startswith(candidate + ":"):
                return True
        return False

    def offer(self, message: Message) -> None:
        if message.channel == CHANNEL_SYSTEM:
            self._priority.append(message)
        elif _droppable(message.channel):
            if len(self._normal) == self._normal.maxlen:
                self.dropped += 1
            self._normal.append(message)
        else:
            self._ordered.append(message)
        self._wake.set()

    def drain(self) -> list[Message]:
        out = list(self._priority) + list(self._ordered) + list(self._normal)
        self._priority.clear()
        self._ordered.clear()
        self._normal.clear()
        self._wake.clear()
        return out

    async def get(self) -> Message:
        while True:
            for queue in (self._priority, self._ordered, self._normal):
                if queue:
                    return queue.popleft()
            self._wake.clear()
            await self._wake.wait()


class EventBus:
    def __init__(self, *, tick_buffer: int = DEFAULT_TICK_BUFFER, redis: Any | None = None) -> None:
        self.tick_buffer = tick_buffer
        self.redis = redis
        #: Процессын дахин давтагдашгүй тэмдэг. Redis-ээр буцаж ирсэн ӨӨРИЙН
        #: мессежийг таньж хаяхад хэрэглэнэ — эс бөгөөс клиент бүрийг хоёр
        #: удаа мэдэгдэнэ.
        self.instance_id = uuid4().hex
        self._subscribers: list[Subscriber] = []
        self._seq = count(1)
        self._system_history: deque[Message] = deque(maxlen=SYSTEM_REPLAY)

    @property
    def dropped(self) -> int:
        return sum(s.dropped for s in self._subscribers)

    def subscribe(self, channels: list[str], *, replay_system: bool = False) -> Subscriber:
        sub = Subscriber(channels, self.tick_buffer)
        self._subscribers.append(sub)
        if replay_system:
            # Дахин холбогдсон клиент одоогийн төлөвийг ШУУД авна — «би юу ч
            # аваагүй тул бүх юм хэвийн» гэсэн таамаглал үүсэхгүй.
            for message in self._system_history:
                if sub.matches(message.channel):
                    sub.offer(message)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        if sub in self._subscribers:
            self._subscribers.remove(sub)

    def stamp(self, payload: dict[str, Any]) -> dict[str, Any]:
        """`seq` + `ts` — asyncapi нь хоёуланг ЗААВАЛ шаардана.

        WS-ээр bus-гүйгээр шууд илгээгддэг frame-ууд (snapshot, heartbeat)
        БАС энэ функцээр дамжина: тамга нэг газраас тавигдахгүй бол нэг
        гадаргуу дээр хоёр өөр хэлбэр үүснэ.
        """
        return {"seq": next(self._seq), "ts": to_iso(now_utc()), **payload}

    def deliver(self, message: Message) -> None:
        """Process-дотоод хүргэлт. Redis рүү ДАХИН нийтлэхгүй.

        `publish()` ба Redis-ээс ирсэн мессеж хоёулаа ЭНД нийлнэ — хүргэх
        дүрэм (system-ийн түүх, хаялт) нэг газарт л бичигдэнэ.
        """
        if message.channel == CHANNEL_SYSTEM:
            self._system_history.append(message)
        for sub in self._subscribers:
            if sub.matches(message.channel):
                sub.offer(message)

    async def publish(self, channel: str, payload: dict[str, Any]) -> Message:
        enriched = self.stamp(payload)
        message = Message(channel=channel, payload=enriched)
        self.deliver(message)
        if self.redis is not None:
            wire = {**enriched, SRC_FIELD: self.instance_id}
            await self.redis.publish(channel, json.dumps(wire, ensure_ascii=False))
        return message

    async def bridge(self) -> None:
        """Redis → локал fan-in. `REDIS_URL` тохируулсан үед л ажиллана.

        AC-14 нь «БҮХ холбогдсон клиент» гэж шаардана: олон worker/instance
        үед нэг instance-ийн kill switch нөгөөгийн WS клиентэд хүрэх цорын
        ганц зам нь энэ. Нийтлэх талыг эзэмшээд захиалах талыг эзэмшихгүй
        байх нь чимээгүй тасархай — kill switch зарлагдсан ч зарим operator
        харахгүй.
        """
        if self.redis is None:  # pragma: no cover - дуудагч шалгадаг
            return
        pubsub = self.redis.pubsub()
        await pubsub.psubscribe("*")
        try:
            async for raw in pubsub.listen():
                if raw.get("type") != "pmessage":
                    continue
                payload = json.loads(_as_text(raw["data"]))
                if payload.pop(SRC_FIELD, None) == self.instance_id:
                    continue  # өөрийн мессеж — аль хэдийн хүргэгдсэн
                self.deliver(Message(channel=_as_text(raw["channel"]), payload=payload))
        finally:
            await pubsub.aclose()


#: Процессын bus. `app.main`-д эхлүүлнэ; тест бүрт шинээр үүсгэнэ.
_BUS: EventBus | None = None


def get_bus() -> EventBus:
    global _BUS
    if _BUS is None:
        _BUS = EventBus()
    return _BUS


def set_bus(bus: EventBus | None) -> None:
    global _BUS
    _BUS = bus
