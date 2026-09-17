"""PERSONAL-3 UAT — 6-р тойрог: UAT орчинд БАЙРШУУЛСАН хувилбарын шалгалт.

Онцлог: энэ ажиллалтад Alpaca paper түлхүүр орчинд ОЛГОГДООГҮЙ (`alpaca` MCP
server CONNECT_TIMEOUT, `ALPACA_API_KEY` env алга). Тиймээс broker-ээс
ХАМААРДАГ замуудыг (бодит order илгээх) шалгах боломжгүй — энэ скрипт нь
broker-ээс ХАМААРАХГҮЙ бүх хүлээн авалтын шалгуурыг, мөн broker унасан
үеийн ХАМГААЛАЛТЫН зан төлөвийг шалгана.

    python uat_round6.py            # :28000 / :28001 / nginx :18080
"""
import asyncio
import json
import os
import sys
import uuid

import httpx
import websockets

A = os.environ.get("UAT_A", "http://127.0.0.1:28000")
B = os.environ.get("UAT_B", "http://127.0.0.1:28001")
FE = os.environ.get("UAT_FE", "http://localhost:18080")
V1, V1B, V1FE = A + "/api/v1", B + "/api/v1", FE + "/api/v1"
SOURCES = {"alpaca_live", "alpaca_paper", "backtest"}
R = []


def ev(msg):
    """WS хүрээ нь `{channel, payload:{event,...}}` — event нь payload дотор."""
    body = msg.get("payload") if isinstance(msg.get("payload"), dict) else msg
    return body.get("event")


def rec(ac, name, ok, detail=""):
    R.append((ac, name, ok, detail))
    tag = "PASS" if ok is True else "FAIL" if ok is False else "INFO"
    print(f"[{tag}] {ac} {name} :: {detail}"[:400], flush=True)


async def envelope(c):
    """AC-20/21 — 200 хариу бүрд source/as_of/stale/system_state."""
    paths = ["/health", "/system/state", "/orders", "/attribution",
             "/agent-decisions", "/approvals", "/providers",
             "/tuning/parameters", "/account", "/positions"]
    ok, bad = 0, []
    for p in paths:
        r = await c.get(V1 + p)
        try:
            b = r.json()
        except Exception:
            b = {}
        if r.status_code != 200:
            bad.append(f"{p}:{r.status_code}:{b.get('code')}")
            continue
        miss = [k for k in ("source", "as_of", "stale", "system_state") if k not in b]
        if miss or b.get("source") not in SOURCES:
            bad.append(f"{p}:{miss or b.get('source')}")
        else:
            ok += 1
    only_broker = all("broker_unavailable" in x for x in bad)
    rec("AC-20/21", "хариу бүрд source/as_of/stale/system_state",
        not bad or only_broker, f"200-ийн {ok} зөв; бусад={bad}")


async def proxy(c):
    """U-1 — байршуулсан nginx: SPA deep link + /api reverse proxy."""
    deep = {}
    for p in ["/", "/approvals", "/settings", "/activity", "/providers", "/tuning"]:
        deep[p] = (await c.get(FE + p)).status_code
    rec("U-1", "SPA deep link (байршуулсан nginx)",
        all(v == 200 for v in deep.values()), json.dumps(deep))
    r = await c.get(V1FE + "/health")
    same = False
    if r.status_code == 200:
        direct = (await c.get(V1 + "/health")).json()
        same = r.json().get("system_state") == direct.get("system_state")
    rec("U-1", "/api/* → backend proxy", r.status_code == 200 and same,
        f"{r.status_code}, backend-тэй ижил төлөв={same}")


async def ws_through_proxy():
    """U-1 — /ws upgrade нь proxy-оор дамжина (AC-14-ийн цорын ганц зам)."""
    url = FE.replace("http://", "ws://") + "/ws?channels=system"
    try:
        async with websockets.connect(url, open_timeout=10) as ws:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            rec("U-1/AC-14", "WS upgrade nginx-ээр", True,
                str(ev(msg))[:80])
    except Exception as e:  # noqa: BLE001
        rec("U-1/AC-14", "WS upgrade nginx-ээр", False, repr(e)[:200])


async def fanout(c):
    """AC-14 / U-3 — :28000-д хийсэн үйлдэл :28001-ийн WS клиентэд хүрнэ.

    Broker унасан тул систем `halted` хэвээр — `kill-switch` идемпотент
    бөгөөд шинэ `state_changed` төрүүлэхгүй. Тиймээс Redis-ээр дамжих
    нотолгоог `provider_switched` (мөн `system` суваг) дээр авна.
    """
    got = []
    deadline = asyncio.get_event_loop().time() + 40

    async def listen():
        async with websockets.connect(
                B.replace("http://", "ws://") + "/ws?channels=system",
                open_timeout=10) as ws:
            while asyncio.get_event_loop().time() < deadline:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
                except asyncio.TimeoutError:
                    continue
                got.append(m)
                if ev(m) == "provider_switched":
                    return

    cur = (await c.get(V1 + "/providers")).json()
    active = cur["active"]["research"]
    target = next(p["id"] for p in cur["providers"]
                  if p["id"] != active and not p["read_only"])
    t = asyncio.create_task(listen())
    await asyncio.sleep(1.5)
    r = await c.post(V1 + "/providers/research/switch", json={"provider_id": target})
    try:
        await asyncio.wait_for(t, timeout=45)
    except asyncio.TimeoutError:
        t.cancel()
    hit = [m for m in got if ev(m) == "provider_switched"]
    rec("AC-14", ":28000-ийн үйлдэл → :28001-ийн WS клиент (Redis fan-out)",
        bool(hit) and r.status_code == 200,
        f"switch={r.status_code} → {target}; WS={hit[0] if hit else got[:2]}")
    k = await c.post(V1 + "/kill-switch", json={"reason": "uat6"})
    rec("AC-36", "kill-switch идемпотент", k.status_code == 200,
        f"{k.status_code} {k.json().get('state')}")


async def halted_paths(c):
    """AC-33/AC-36 — halted үед арилжааны бүх зам хаагдана."""
    st = (await c.get(V1 + "/system/state")).json()
    rec("AC-36", "kill-switch → halted", st.get("state") == "halted", str(st.get("state")))
    body = {"symbol": "AAPL", "side": "buy", "qty": "1", "order_type": "market",
            "time_in_force": "day"}
    r = await c.post(V1 + "/orders/manual", json=body,
                     headers={"Idempotency-Key": str(uuid.uuid4())})
    j = r.json()
    rec("AC-33", "halted үед гарын order",
        r.status_code == 409 and j.get("code") == "system_halted",
        f"{r.status_code} {j.get('code')}")
    r2 = await c.post(V1B + "/orders/manual", json=body,
                      headers={"Idempotency-Key": str(uuid.uuid4())})
    rec("AC-33", "halted нь нөгөө instance-д ч үйлчилнэ",
        r2.status_code == 409 and r2.json().get("code") == "system_halted",
        f"{r2.status_code} {r2.json().get('code')}")


async def breaker_guard(c):
    """AC-15 — broker унасан үед автоматаар асаахыг ЗӨВШӨӨРӨХГҮЙ."""
    r = await c.post(V1 + "/system/activate", json={})
    j = r.json()
    tripped = [m["metric"] for m in j.get("breaker_metrics", []) if m.get("tripped")]
    rec("AC-15", "breaker унасан үед activate татгалзана",
        r.status_code == 409
        and j.get("code") in {"breaker_still_tripped", "confirmation_required"},
        f"{r.status_code} {j.get('code')} tripped={tripped}")


async def problem_contract(c):
    """N-2 — алдааны хариу Problem схемтэй."""
    r = await c.post(V1 + "/orders/manual", json={"symbol": "AAPL"},
                     headers={"Idempotency-Key": str(uuid.uuid4())})
    j = r.json()
    need = {"type", "title", "status", "code", "detail"}
    rec("N-2", "422 нь Problem гэрээг дагана",
        r.status_code == 422 and need <= set(j) and "errors" in j,
        f"{r.status_code} талбар={sorted(set(j) & (need | {'errors'}))}")


async def providers(c):
    """AC-10 / U-3 — hot-swap нь бүх instance-д хүрнэ."""
    cur = (await c.get(V1 + "/providers")).json()
    active = cur["active"]["research"]
    target = next(p["id"] for p in cur["providers"]
                  if p["id"] != active and not p["read_only"])
    r = await c.post(V1 + "/providers/research/switch", json={"provider_id": target})
    await asyncio.sleep(2.0)
    a = (await c.get(V1 + "/providers")).json()["active"]["research"]
    b = (await c.get(V1B + "/providers")).json()["active"]["research"]
    rec("AC-10", "provider hot-swap (restart-гүй)", r.status_code == 200 and a == target,
        f"{r.status_code} {active} -> {a}")
    rec("U-3", "солилт нөгөө instance-д хүрнэ (Redis)", b == target,
        f":28001 active={b} (хүлээсэн {target})")
    return target


async def tuning_and_bounds(c):
    """AC-22 / AC-24 — bounds-ыг API-аас засах зам БАЙХГҮЙ, promote нь хүн-хаалттай."""
    spec = (await c.get(A + "/openapi.json")).json()["paths"]
    mut = [p for p, v in spec.items()
           if set(v) & {"post", "put", "patch", "delete"}
           and any(k in p for k in ("whitelist", "bounds", "limits", "risk-config"))]
    rec("AC-22", "whitelist/bounds засах endpoint алга", not mut,
        f"{len(spec)} зам, mutator={mut}")
    r = await c.post(V1 + "/tuning/promote", json={"tuning_history_ids": [str(uuid.uuid4())]})
    rec("AC-24", "token-гүй promote татгалзана",
        r.status_code in (409, 404)
        and r.json().get("code") in {"confirmation_required", "not_found"},
        f"{r.status_code} {r.json().get('code')}")


async def main():
    async with httpx.AsyncClient(timeout=60.0) as c:
        h = (await c.get(V1 + "/health")).json()
        rec("INFRA", "health", h.get("status") in {"ok", "degraded"},
            f"status={h['status']} db={h['database']['reachable']} "
            f"redis={h['redis']['reachable']} broker={h['broker']['reachable']}")
        rec("Хянагч-1", "redis.reachable", h["redis"]["reachable"] is True,
            json.dumps(h["redis"]))
        await envelope(c)
        await proxy(c)
        await ws_through_proxy()
        await fanout(c)
        await halted_paths(c)
        await breaker_guard(c)
        await problem_contract(c)
        await providers(c)
        await tuning_and_bounds(c)

    p = sum(1 for x in R if x[2] is True)
    f = sum(1 for x in R if x[2] is False)
    print(f"\n=== PASS={p} FAIL={f} ===")
    for x in R:
        if x[2] is False:
            print("FAIL:", x[0], x[1], x[3])
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
