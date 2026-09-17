"""PERSONAL-3 UAT — 2-р тойрог: нарийвчилсан хэмжилт."""
import asyncio
import json
import time
import uuid

import httpx
import websockets

V1 = "http://127.0.0.1:8000/api/v1"


async def main():
    async with httpx.AsyncClient(timeout=30.0) as c:
        # 1) AC-10 provider hot-swap
        before = (await c.get(V1 + "/providers")).json()
        active = before["active"]["research"]
        target = next(p["id"] for p in before["providers"]
                      if p["id"] != active and not p["read_only"])
        t0 = time.monotonic()
        r = await c.post(V1 + f"/providers/research/switch", json={"provider_id": target})
        el = time.monotonic() - t0
        after = (await c.get(V1 + "/providers")).json()
        print(f"AC-10 switch {active}->{target}: {r.status_code} {el:.3f}s "
              f"resp={json.dumps(r.json(), ensure_ascii=False)}")
        print(f"AC-10 active after = {after['active']} (хүлээгдэж буй {target})")
        # буцаах
        rb = await c.post(V1 + "/providers/research/switch", json={"provider_id": active})
        print(f"AC-10 restore: {rb.status_code} active={(await c.get(V1+'/providers')).json()['active']}")

        # 2) AC-10 read-only provider-ыг research-д оноох оролдлого
        ro = next(p["id"] for p in before["providers"] if p["read_only"])
        rr = await c.post(V1 + "/providers/research/switch", json={"provider_id": ro})
        print(f"AC-10 read-only({ro}) research-д: {rr.status_code} "
              f"{json.dumps(rr.json(), ensure_ascii=False)[:200]}")
        if rr.status_code == 200:
            await c.post(V1 + "/providers/research/switch", json={"provider_id": active})

        # 3) AC-10 мэдэгдэхгүй provider
        ru = await c.post(V1 + "/providers/research/switch", json={"provider_id": "does-not-exist"})
        print(f"AC-10 үл мэдэгдэх provider: {ru.status_code} {ru.json().get('code')}")

        # 4) AC-33 гарын order HALTED үед — ЗӨВ UUID Idempotency-Key-тэй
        key = str(uuid.uuid4())
        order = {"symbol": "AAPL", "side": "buy", "qty": "1",
                 "order_type": "market", "time_in_force": "day"}
        r = await c.post(V1 + "/orders/manual", json=order, headers={"Idempotency-Key": key})
        print(f"AC-33 halted гарын order: {r.status_code} "
              f"{json.dumps(r.json(), ensure_ascii=False)[:260]}")
        # header огт байхгүй
        r2 = await c.post(V1 + "/orders/manual", json=order)
        print(f"AC-33 Idempotency-Key-гүй: {r2.status_code} "
              f"{json.dumps(r2.json(), ensure_ascii=False)[:200]}")

        # 5) AC-14 kill-switch-ийн БОДИТ саатал: WS мэдэгдэл хүртэлх хугацаа
        async with websockets.connect("ws://127.0.0.1:8000/ws?channels=system") as ws:
            await asyncio.wait_for(ws.recv(), 5)  # snapshot
            t0 = time.monotonic()
            task = asyncio.create_task(c.post(V1 + "/kill-switch", json={"reason": "UAT latency"}))
            m = json.loads(await asyncio.wait_for(ws.recv(), 10))
            t_ws = time.monotonic() - t0
            resp = await task
            t_http = time.monotonic() - t0
            print(f"AC-14 kill-switch: WS мэдэгдэл {t_ws:.3f}s, HTTP хариу {t_http:.3f}s, "
                  f"payload={json.dumps(m['payload'], ensure_ascii=False)[:160]}")

            # order зам хаагдсан эсэх — kill-switch-ийн дараа шууд
            t0 = time.monotonic()
            ro2 = await c.post(V1 + "/orders/manual", json=order,
                               headers={"Idempotency-Key": str(uuid.uuid4())})
            print(f"AC-14 halted-ийн дараах order: {ro2.status_code} "
                  f"code={ro2.json().get('code')} ({time.monotonic()-t0:.3f}s)")

        # 6) /system/state-ийн саатал (breaker хэмжилт broker руу очдог эсэх)
        t0 = time.monotonic()
        await c.get(V1 + "/system/state")
        print(f"GET /system/state саатал: {time.monotonic()-t0:.3f}s")
        t0 = time.monotonic()
        await c.get(V1 + "/orders")
        print(f"GET /orders саатал: {time.monotonic()-t0:.3f}s")

        fin = (await c.get(V1 + "/system/state")).json()
        print(f"эцсийн төлөв: {fin['state']} / {fin.get('reason')}")


asyncio.run(main())
