"""PERSONAL-3 UAT — 3-р тойрог: олон instance Redis fan-out + frontend WS proxy."""
import asyncio
import json
import time

import httpx
import websockets


async def main():
    async with httpx.AsyncClient(timeout=30.0) as c:
        h2 = (await c.get("http://127.0.0.1:8001/api/v1/health")).json()
        print("instance-2 health:", json.dumps(
            {k: h2[k] for k in ("source", "system_state", "redis")}, ensure_ascii=False))

        # instance-2 дээр WS сонсоно, instance-1 дээр kill-switch дарна
        async with websockets.connect("ws://127.0.0.1:8001/ws?channels=system") as ws2, \
                   websockets.connect("ws://127.0.0.1:4173/ws?channels=system") as wsfe:
            await asyncio.wait_for(ws2.recv(), 5)
            await asyncio.wait_for(wsfe.recv(), 5)
            t0 = time.monotonic()
            asyncio.create_task(
                c.post("http://127.0.0.1:8000/api/v1/kill-switch",
                       json={"reason": "UAT fan-out"}))
            try:
                m2 = json.loads(await asyncio.wait_for(ws2.recv(), 10))
                print(f"AC-14 instance-2 WS: {time.monotonic()-t0:.3f}s "
                      f"{json.dumps(m2['payload'], ensure_ascii=False)[:180]}")
            except asyncio.TimeoutError:
                print("AC-14 instance-2 WS: TIMEOUT — fan-out хүрсэнгүй")
            try:
                mf = json.loads(await asyncio.wait_for(wsfe.recv(), 10))
                print(f"AC-14 frontend proxy WS: {time.monotonic()-t0:.3f}s "
                      f"{json.dumps(mf['payload'], ensure_ascii=False)[:180]}")
            except asyncio.TimeoutError:
                print("AC-14 frontend proxy WS: TIMEOUT")

        fin = (await c.get("http://127.0.0.1:8001/api/v1/system/state")).json()
        print("instance-2 харсан төлөв:", fin["state"], "/", fin.get("reason"))


asyncio.run(main())
