"""PERSONAL-3 UAT — black-box acceptance tests against the deployed system."""
import asyncio
import json
import re
import subprocess
import sys
import time

import httpx
import websockets

API = "http://127.0.0.1:8000"
FE = "http://127.0.0.1:4173"
V1 = API + "/api/v1"
R = []
SOURCES = {"alpaca_live", "alpaca_paper", "backtest"}


def rec(ac, name, ok, detail=""):
    R.append((ac, name, ok, detail))
    tag = "PASS" if ok is True else "FAIL" if ok is False else "INFO"
    print(f"[{tag}] {ac} {name} :: {detail}"[:400], flush=True)


def get_pid():
    out = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "(Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess"],
        capture_output=True, text=True).stdout.strip()
    return out


def pick_switch(provs):
    try:
        roles = provs["roles"]
        items = roles.items() if isinstance(roles, dict) else [(r["role"], r) for r in roles]
        for role, info in items:
            avail = info.get("available") or info.get("candidates") or info.get("providers") or []
            cur = info.get("active") or info.get("provider_id")
            for p in avail:
                pid = p if isinstance(p, str) else (p.get("provider_id") or p.get("id"))
                if pid and pid != cur:
                    return role, pid
    except Exception:
        pass
    return None, None


async def main():
    async with httpx.AsyncClient(timeout=20.0) as c:
        bad, checked = [], []
        for path in ["/health", "/system/state", "/orders", "/attribution",
                     "/agent-decisions", "/approvals", "/providers",
                     "/tuning/parameters", "/account", "/positions"]:
            r = await c.get(V1 + path)
            try:
                body = r.json()
            except Exception:
                body = {}
            src = body.get("source")
            checked.append(f"{path}:{r.status_code}:{src}")
            if r.status_code == 200 and src not in SOURCES:
                bad.append(f"{path} source={src!r}")
        rec("AC-20", "source талбар бүх 200 хариунд", not bad,
            "; ".join(checked) + (" | BAD: " + ",".join(bad) if bad else ""))

        h = (await c.get(V1 + "/health")).json()
        rec("AC-21", "горимын заалт paper", h.get("source") == "alpaca_paper", f"source={h.get('source')}")

        st = (await c.get(V1 + "/system/state")).json()
        rec("AC-37", "restart-ийн дараа төлөв хадгалагдсан", st["state"] in ("halted", "winding_down"),
            f"state={st['state']} reason={st.get('reason')} changed_by={st.get('changed_by')}")

        r = await c.post(V1 + "/system/activate", json={})
        b = r.json()
        rec("AC-37", "баталгаажуулалтгүй activate татгалзана",
            r.status_code == 409 and b.get("code") == "confirmation_required",
            f"{r.status_code} {b.get('code')}")

        r = await c.post(V1 + "/system/activate",
                         json={"confirmation_token": "00000000-0000-0000-0000-000000000000"})
        rec("AC-37", "хуурамч token татгалзана", r.status_code >= 400,
            f"{r.status_code} {r.json().get('code')}")

        order = {"symbol": "AAPL", "side": "buy", "qty": "1",
                 "order_type": "market", "time_in_force": "day"}
        r = await c.post(V1 + "/orders/manual", json=order,
                         headers={"Idempotency-Key": f"uat-{time.time()}"})
        b = r.json()
        rec("AC-33", "HALTED үед гарын order хаагдана",
            400 <= r.status_code < 500,
            f"{r.status_code} code={b.get('code')} detail={str(b.get('detail'))[:120]}")

        r = await c.post(V1 + "/tuning/promote",
                         json={"tuning_history_ids": ["11111111-1111-1111-1111-111111111111"]})
        b = r.json()
        rec("AC-24", "token-гүй tuning promote татгалзана",
            r.status_code == 409 and b.get("code") == "confirmation_required",
            f"{r.status_code} {b.get('code')}")

        spec = (await c.get(API + "/openapi.json")).json()
        paths = spec["paths"]
        mutators = [f"{m.upper()} {p}" for p, ops in paths.items() for m in ops
                    if m in ("post", "put", "patch", "delete")
                    and re.search(r"whitelist|bounds|limit|risk-config|setting", p, re.I)]
        rec("AC-22", "whitelist/bounds засах endpoint байхгүй", not mutators,
            f"{len(paths)} path, mutator={mutators}")

        pid_before = get_pid()
        provs = (await c.get(V1 + "/providers")).json()
        rec("AC-10", "provider жагсаалт", bool(provs), json.dumps(provs, ensure_ascii=False)[:400])
        role, target = pick_switch(provs)
        if role:
            r = await c.post(V1 + f"/providers/{role}/switch", json={"provider_id": target})
            pid_after = get_pid()
            rec("AC-10", "hot-swap restart-гүй",
                r.status_code == 200 and pid_before == pid_after and pid_before != "",
                f"{r.status_code} role={role} -> {target} pid {pid_before}=={pid_after} "
                f"resp={json.dumps(r.json(), ensure_ascii=False)[:200]}")
        else:
            rec("AC-10", "hot-swap", None, "солих боломжтой хос олдсонгүй")

        async with websockets.connect("ws://127.0.0.1:8000/ws?channels=system") as ws:
            snap = json.loads(await asyncio.wait_for(ws.recv(), 5))
            rec("AC-14", "WS холбогдмогц snapshot",
                snap["payload"].get("event") == "state_changed",
                json.dumps(snap, ensure_ascii=False)[:200])

            t0 = time.monotonic()
            r = await c.post(V1 + "/kill-switch", json={"reason": "UAT test"})
            elapsed = time.monotonic() - t0
            body = r.json()
            rec("AC-14", "kill-switch halted 1 сек дотор",
                r.status_code == 200 and body["state"] == "halted" and elapsed < 1.0,
                f"{r.status_code} state={body.get('state')} {elapsed:.3f}s")

            got, seen = None, []
            try:
                while True:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 3))
                    seen.append(m)
                    if m["payload"].get("state") == "halted":
                        got = m
                        break
            except asyncio.TimeoutError:
                pass
            rec("AC-14", "kill-switch WS broadcast", got is not None,
                json.dumps(got, ensure_ascii=False)[:250] if got
                else f"ирсэн: {json.dumps(seen, ensure_ascii=False)[:200]}")

            t0 = time.monotonic()
            r = await c.post(V1 + "/system/wind-down", json={"reason": "UAT"})
            rec("AC-34", "HALTED-аас wind-down", r.status_code in (200, 409),
                f"{r.status_code} {json.dumps(r.json(), ensure_ascii=False)[:200]} {time.monotonic()-t0:.3f}s")

            r = await c.post(V1 + "/system/activate", json={})
            b = r.json()
            tok = (b.get("confirmation") or {}).get("token")
            if r.status_code == 409 and b.get("code") == "breaker_still_tripped":
                rec("AC-15", "breaker унасан үед activate татгалзана", True,
                    json.dumps(b.get("breaker_metrics"), ensure_ascii=False)[:300])
                rec("AC-34", "wind-down урсгал", None, "breaker унасан тул active руу орох боломжгүй")
            elif tok:
                r2 = await c.post(V1 + "/system/activate", json={"confirmation_token": tok})
                b2 = r2.json()
                rec("AC-37", "token-той activate active",
                    r2.status_code == 200 and b2.get("state") == "active",
                    f"{r2.status_code} state={b2.get('state')} {json.dumps(b2, ensure_ascii=False)[:200]}")
                if r2.status_code == 200:
                    t0 = time.monotonic()
                    rw = await c.post(V1 + "/system/wind-down", json={"reason": "UAT wind-down"})
                    el = time.monotonic() - t0
                    bw = rw.json()
                    rec("AC-34", "wind-down 1 сек дотор + grace тоолуур",
                        rw.status_code == 200 and bw.get("state") == "winding_down" and el < 1.0,
                        f"{rw.status_code} state={bw.get('state')} "
                        f"seconds_remaining={bw.get('seconds_remaining')} {el:.3f}s")
                    wd = None
                    try:
                        while True:
                            m = json.loads(await asyncio.wait_for(ws.recv(), 3))
                            if m["payload"].get("state") == "winding_down":
                                wd = m
                                break
                    except asyncio.TimeoutError:
                        pass
                    rec("AC-34", "wind-down WS broadcast", wd is not None,
                        json.dumps(wd, ensure_ascii=False)[:250] if wd else "мессеж ирсэнгүй")

                    r3 = await c.post(V1 + "/orders/manual", json=order,
                                      headers={"Idempotency-Key": f"uat-wd-{time.time()}"})
                    b3 = r3.json()
                    rec("AC-35", "winding_down үед exposure нэмэгдүүлэх order хаагдана",
                        400 <= r3.status_code < 500,
                        f"{r3.status_code} code={b3.get('code')} detail={str(b3.get('detail'))[:150]}")

                    t0 = time.monotonic()
                    rk = await c.post(V1 + "/kill-switch", json={"reason": "UAT restore"})
                    rec("AC-36", "winding_down kill-switch halted",
                        rk.status_code == 200 and rk.json()["state"] == "halted"
                        and time.monotonic() - t0 < 1.0,
                        f"{rk.status_code} state={rk.json().get('state')} {time.monotonic()-t0:.3f}s")

        for p in ["/account", "/positions", "/market/quote/AAPL"]:
            r = await c.get(V1 + p)
            rec("AC-1", f"broker унших {p}", None,
                f"{r.status_code} {json.dumps(r.json(), ensure_ascii=False)[:180]}")

        r = await c.get(V1 + "/attribution")
        rec("AC-30", "attribution харагдац", r.status_code == 200,
            f"{r.status_code} {json.dumps(r.json(), ensure_ascii=False)[:250]}")

        idx = await c.get(FE + "/")
        rec("FE", "frontend index", idx.status_code == 200 and 'id="root"' in idx.text,
            f"{idx.status_code} {len(idx.text)}B")
        prox = await c.get(FE + "/api/v1/health")
        ok = prox.status_code == 200 and prox.json().get("source") == "alpaca_paper"
        rec("FE", "frontend /api proxy", ok,
            f"{prox.status_code} {prox.text[:140]}")

        fin = (await c.get(V1 + "/system/state")).json()
        rec("END", "эцсийн төлөв halted", fin["state"] == "halted",
            f"state={fin['state']} reason={fin.get('reason')}")

    print("\n===SUMMARY===")
    for ac, name, ok, d in R:
        tag = "PASS" if ok is True else "FAIL" if ok is False else "INFO"
        print(f"{tag}\t{ac}\t{name}\t{d}")
    fails = [x for x in R if x[2] is False]
    print(f"\nTOTAL={len(R)} PASS={len([x for x in R if x[2] is True])} "
          f"FAIL={len(fails)} INFO={len([x for x in R if x[2] is None])}")
    return 1 if fails else 0


sys.exit(asyncio.run(main()))
