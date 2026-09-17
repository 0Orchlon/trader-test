"""PERSONAL-3 UAT — 5-р тойрог: broker-ээс ХАМААРАХ арилжааны гол зам.

Ажиллах нөхцөл: `ALPACA_API_KEY` / `ALPACA_API_SECRET` бодитоор ажиллаж
байх ёстой (round4-ийн шалгалт тэнцсэн байх). Скрипт нь Alpaca paper
данс руу БОДИТ (paper) order илгээнэ.

    ALPACA_API_KEY=... ALPACA_API_SECRET=... python uat_round5.py

TLS interception хийдэг сүлжээнд `SSL_CERT_FILE`-ыг Windows-ийн үндэс
гэрчилгээний PEM рүү заа (тайлангийн §6).
"""
import asyncio
import json
import os
import sys
import time
import uuid
from decimal import Decimal

import httpx
import websockets

API = "http://127.0.0.1:8000"
API2 = "http://127.0.0.1:8001"
FE = "http://127.0.0.1:4173"
V1 = API + "/api/v1"
BROKER = "https://paper-api.alpaca.markets"
HDR = {
    "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
    "APCA-API-SECRET-KEY": os.environ["ALPACA_API_SECRET"],
}
R = []


def rec(ac, name, ok, detail=""):
    R.append((ac, name, ok, detail))
    tag = "PASS" if ok is True else "FAIL" if ok is False else "INFO"
    print(f"[{tag}] {ac} {name} :: {detail}"[:500], flush=True)


def key(tag):
    # `Idempotency-Key` нь гэрээгээр UUID — тэмдэгт мөр дамжуулбал 422.
    return str(uuid.uuid4())


ORDER = {"symbol": "AAPL", "side": "buy", "qty": "1",
         "order_type": "market", "time_in_force": "day"}


async def alpaca_orders(bc, status="all"):
    r = await bc.get(BROKER + "/v2/orders", params={"status": status, "limit": 200})
    return r.json()


async def activate(c):
    r = await c.post(V1 + "/system/activate", json={})
    b = r.json()
    tok = (b.get("confirmation") or {}).get("token")
    if not tok:
        return r.status_code, b
    r2 = await c.post(V1 + "/system/activate", json={"confirmation_token": tok})
    return r2.status_code, r2.json()


async def main():  # noqa: C901 - UAT скрипт, дараалал нь баримт
    async with httpx.AsyncClient(timeout=60.0) as c, \
            httpx.AsyncClient(timeout=60.0, headers=HDR) as bc:

        # Эхлэлийн цэвэрлэгээ: өмнөх ажиллалтын нээлттэй order үлдвэл Alpaca
        # wash-trade хамгаалалт дараагийн эсрэг талын order-ыг 403-аар
        # татгалзана (зах зээл хаалттай үед market order дараалалд үлддэг).
        await bc.delete(BROKER + "/v2/orders")
        await asyncio.sleep(3)

        # ---------- AC-1: унших нь Alpaca-ийн утгыг ӨӨРЧЛӨХГҮЙ ----------
        raw_acc = (await bc.get(BROKER + "/v2/account")).json()
        app_acc = (await c.get(V1 + "/account")).json()["account"]
        # Утгын харьцуулалт Decimal-аар: AC-25 нь API дээр тогтмол таслалтай
        # тэмдэгт мөр шаарддаг тул "99665.50" ↔ "99665.5" нь ЗӨРҮҮ БИШ.
        diffs = [f"{k}: app={app_acc.get(k)!r} alpaca={raw_acc.get(k)!r}"
                 for k in ("equity", "cash", "buying_power")
                 if Decimal(str(app_acc.get(k))) != Decimal(str(raw_acc.get(k)))]
        rec("AC-1", "/account нь Alpaca-ийн утгатай тэмдэгт тэмдэгтээр тэнцүү",
            not diffs,
            f"equity={app_acc.get('equity')} cash={app_acc.get('cash')} "
            f"buying_power={app_acc.get('buying_power')} " + ("; ".join(diffs)))

        raw_pos = (await bc.get(BROKER + "/v2/positions")).json()
        app_pos = (await c.get(V1 + "/positions")).json()["positions"]
        by_sym = {p["symbol"]: p for p in app_pos}
        pdiff = []
        for p in raw_pos:
            a = by_sym.get(p["symbol"])
            if a is None:
                pdiff.append(f"{p['symbol']} app-д байхгүй")
                continue
            for k in ("qty", "avg_entry_price"):
                if Decimal(str(a.get(k))) != Decimal(str(p.get(k))):
                    pdiff.append(f"{p['symbol']}.{k}: app={a.get(k)!r} alpaca={p.get(k)!r}")
        rec("AC-1", "/positions нь Alpaca-ийн qty/avg_entry_price-тай тэнцүү",
            not pdiff and len(app_pos) == len(raw_pos),
            f"alpaca={len(raw_pos)} app={len(app_pos)} "
            f"{[(p['symbol'], p['qty'], p['avg_entry_price']) for p in app_pos]} "
            + "; ".join(pdiff))

        # ---------- AC-29: локал бичлэггүй позиц = external ----------
        ext = [p for p in app_pos if p.get("origin") == "external"]
        rec("AC-29", "системээс гадуур нээгдсэн позиц `external` гэж шошгологдоно",
            len(raw_pos) > 0 and len(ext) == len(raw_pos),
            f"positions={len(app_pos)} external={len(ext)} "
            f"origins={[(p['symbol'], p.get('origin'), p.get('origin_detail')) for p in app_pos]}")

        # ---------- AC-30: attribution нь бодит мөрөөс ----------
        attr = (await c.get(V1 + "/attribution")).json()
        attr_syms = set()
        for grp in attr.get("groups", []) or []:
            for item in grp.get("symbols", []):
                attr_syms.add(item["symbol"])
        pos_syms = {p["symbol"] for p in app_pos}
        rec("AC-30", "attribution дахь symbol-ууд бодит позицтой тэнцүү",
            pos_syms <= attr_syms,
            f"attribution={sorted(attr_syms)} positions={sorted(pos_syms)} "
            f"body={json.dumps(attr, ensure_ascii=False)[:300]}")

        # ---------- AC-2 / AC-20: as_of + stale + source ----------
        q = await c.get(V1 + "/market/quote/AAPL")
        qb = q.json()
        rec("AC-2", "quote нь as_of + stale тугтай (зах зээл хаалттай үед stale)",
            q.status_code == 200 and "as_of" in qb and qb.get("stale") is True,
            f"{q.status_code} as_of={qb.get('as_of')} stale={qb.get('stale')} "
            f"last={qb.get('quote', {}).get('last')}")

        # ---------- AC-37 / AC-15: activate ----------
        # Эхлэлийн төлөвийг нэг мөр болгоно (скрипт давтан ажиллахад).
        await c.post(V1 + "/kill-switch", json={"reason": "UAT round5 reset"})
        r = await c.post(V1 + "/system/activate", json={})
        b = r.json()
        rec("AC-37", "баталгаажуулалтгүй activate татгалзана",
            r.status_code == 409 and b.get("code") == "confirmation_required",
            f"{r.status_code} code={b.get('code')}")
        rec("AC-15", "broker хүрэх үед breaker унасангүй",
            b.get("code") != "breaker_still_tripped",
            f"code={b.get('code')}")
        st, sb = await activate(c)
        rec("AC-37", "token-той activate → active", st == 200 and sb.get("state") == "active",
            f"{st} state={sb.get('state')}")
        if sb.get("state") != "active":
            rec("END", "active болоогүй тул цааш үргэлжлэх боломжгүй", False,
                json.dumps(sb, ensure_ascii=False)[:300])
            return 1

        # ---------- AC-31 / AC-32: гарын order бүрэн зам ----------
        before = await alpaca_orders(bc)
        k1 = key("uat5-ok")
        t0 = time.monotonic()
        r = await c.post(V1 + "/orders/manual", json=ORDER, headers={"Idempotency-Key": k1})
        el = time.monotonic() - t0
        b = r.json()
        order = b.get("order", {})
        rec("AC-31", "хязгаар доторх гарын order Risk→Execution→Alpaca дамжина",
            r.status_code == 202 and bool(order.get("broker_order_id")),
            f"{r.status_code} {el:.3f}s risk={json.dumps(b.get('risk'), ensure_ascii=False)[:150]} "
            f"status={order.get('status')} broker_order_id={order.get('broker_order_id')}")
        rec("AC-32", "гарын order-ийн origin = manual_operator",
            order.get("origin") == "manual_operator",
            f"origin={order.get('origin')} origin_detail={order.get('origin_detail')} "
            f"client_order_id={order.get('client_order_id')}")

        after = await alpaca_orders(bc)
        coid = order.get("client_order_id")
        at_broker = [o for o in after if o["client_order_id"] == coid]
        rec("AC-31", "order нь Alpaca дээр ижил client_order_id-тай бодитоор үүссэн",
            len(at_broker) == 1,
            f"alpaca_orders {len(before)}→{len(after)} "
            f"{[(o['symbol'], o['side'], o['qty'], o['status']) for o in at_broker]}")

        # idempotency — ижил key + ижил бие
        r = await c.post(V1 + "/orders/manual", json=ORDER, headers={"Idempotency-Key": k1})
        again = await alpaca_orders(bc)
        rec("AC-31", "idempotency: ижил key давхар submit үүсгэхгүй",
            r.status_code in (200, 202)
            and r.json()["order"]["id"] == order.get("id")
            and len(again) == len(after),
            f"{r.status_code} order id ижил={r.json()['order']['id'] == order.get('id')} "
            f"alpaca {len(after)}→{len(again)}")

        # ---------- AC-5: хязгаараас дээш → баталгаажуулалт ----------
        big = dict(ORDER, qty="20")  # ~6 650 USD > MAX_ORDER_NOTIONAL=5000
        n0 = len(await alpaca_orders(bc))
        r = await c.post(V1 + "/orders/manual", json=big, headers={"Idempotency-Key": key("uat5-big")})
        b = r.json()
        n1 = len(await alpaca_orders(bc))
        rec("AC-5", "хязгаараас дээш order баталгаажуулалт хүсэж, Alpaca руу 0 дуудалт",
            r.status_code == 409 and b.get("code") == "confirmation_required" and n0 == n1,
            f"{r.status_code} code={b.get('code')} risk={json.dumps(b.get('risk'), ensure_ascii=False)[:150]} "
            f"alpaca_orders {n0}→{n1}")
        tok = (b.get("confirmation") or {}).get("token")
        if tok:
            r = await c.post(V1 + "/orders/manual", json=dict(big, confirmation_token=tok),
                             headers={"Idempotency-Key": key("uat5-big2")})
            n2 = len(await alpaca_orders(bc))
            rec("AC-5", "баталгаажуулсны ДАРАА л илгээгдэнэ",
                r.status_code == 202 and n2 == n1 + 1,
                f"{r.status_code} alpaca_orders {n1}→{n2} "
                f"order={json.dumps(r.json().get('order', {}), ensure_ascii=False)[:180]}")
            r = await c.post(V1 + "/orders/manual", json=dict(big, confirmation_token=tok),
                             headers={"Idempotency-Key": key("uat5-big3")})
            rec("AC-5", "нэг token дахин хэрэглэгдэхгүй", r.status_code == 409,
                f"{r.status_code} code={r.json().get('code')}")

        # ---------- AC-34 / AC-35: wind-down ----------
        ws1 = await websockets.connect("ws://127.0.0.1:8000/ws?channels=system")
        ws2 = await websockets.connect("ws://127.0.0.1:8001/ws?channels=system")
        await asyncio.wait_for(ws1.recv(), 5)
        await asyncio.wait_for(ws2.recv(), 5)

        t0 = time.monotonic()
        r = await c.post(V1 + "/system/wind-down", json={"reason": "UAT round5"})
        b = r.json()

        async def wait_state(ws, want, budget=5):
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), budget))
                if m["payload"].get("state") == want:
                    return time.monotonic() - t0

        try:
            d1 = await wait_state(ws1, "winding_down")
            d2 = await wait_state(ws2, "winding_down")
        except asyncio.TimeoutError:
            d1 = d2 = None
        rec("AC-34", "wind-down 1 сек дотор + бүх instance-д WS түгээгдэнэ",
            r.status_code == 200 and b.get("state") == "winding_down"
            and d1 is not None and d2 is not None and max(d1, d2) < 1.0,
            f"{r.status_code} state={b.get('state')} seconds_remaining={b.get('seconds_remaining')} "
            f":8000={d1 if d1 is None else f'{d1:.3f}s'} :8001={d2 if d2 is None else f'{d2:.3f}s'}")

        n0 = len(await alpaca_orders(bc))
        r = await c.post(V1 + "/orders/manual", json=ORDER, headers={"Idempotency-Key": key("uat5-wd-buy")})
        n1 = len(await alpaca_orders(bc))
        rec("AC-35", "winding_down: exposure НЭМЭГДҮҮЛЭХ order татгалзана, Alpaca руу 0 дуудалт",
            400 <= r.status_code < 500 and n0 == n1,
            f"{r.status_code} code={r.json().get('code')} "
            f"detail={str(r.json().get('detail'))[:120]} alpaca {n0}→{n1}")

        # Alpaca-ийн wash-trade хамгаалалт: ижил symbol дээр нээлттэй ЭСРЭГ
        # талын market order байвал sell-ийг 403-аар татгалзана. Энэ нь
        # app-ийн зан БИШ тул шалгалтын өмнө нээлттэй order-ыг цэвэрлэнэ.
        await bc.delete(BROKER + "/v2/orders")
        await asyncio.sleep(3)

        sell = dict(ORDER, side="sell")
        r = await c.post(V1 + "/orders/manual", json=sell, headers={"Idempotency-Key": key("uat5-wd-sell")})
        n2 = len(await alpaca_orders(bc))
        rec("AC-35", "winding_down: позиц БАГАСГАХ order дамжина",
            r.status_code == 202 and n2 == n1 + 1,
            f"{r.status_code} code={r.json().get('code')} alpaca {n1}→{n2} "
            f"order={json.dumps(r.json().get('order', {}), ensure_ascii=False)[:160]}")

        # ---------- AC-36 / AC-16: kill-switch ----------
        pos_before = (await bc.get(BROKER + "/v2/positions")).json()
        open_before = await alpaca_orders(bc, "open")
        t0 = time.monotonic()
        rk = await c.post(V1 + "/kill-switch", json={"reason": "UAT round5"})
        el = time.monotonic() - t0
        try:
            k1t = await wait_state(ws1, "halted")
            k2t = await wait_state(ws2, "halted")
        except asyncio.TimeoutError:
            k1t = k2t = None
        rec("AC-36", "winding_down үед kill-switch → halted, WS бүх instance-д",
            rk.status_code == 200 and rk.json().get("state") == "halted"
            and k1t is not None and k2t is not None and max(k1t, k2t) < 1.0,
            f"{rk.status_code} state={rk.json().get('state')} HTTP={el:.3f}s "
            f":8000={k1t if k1t is None else f'{k1t:.3f}s'} :8001={k2t if k2t is None else f'{k2t:.3f}s'}")
        await ws1.close()
        await ws2.close()

        pos_after = (await bc.get(BROKER + "/v2/positions")).json()
        open_after = await alpaca_orders(bc, "open")
        rec("AC-16", "halt нь байгаа позицыг АВТОМАТААР хаахгүй",
            [(p["symbol"], p["qty"]) for p in pos_before] == [(p["symbol"], p["qty"]) for p in pos_after],
            f"өмнө={[(p['symbol'], p['qty']) for p in pos_before]} "
            f"дараа={[(p['symbol'], p['qty']) for p in pos_after]}")
        rec("AC-16", "halt нь нээлттэй order-ыг автоматаар цуцлахгүй",
            len(open_before) == len(open_after),
            f"нээлттэй order {len(open_before)}→{len(open_after)}")

        # ---------- AC-33: halted үед гарын order бүх зам хаалттай ----------
        n0 = len(await alpaca_orders(bc))
        codes = []
        for body, hdr in ((ORDER, key("uat5-h1")), (sell, key("uat5-h2")),
                          (dict(big, confirmation_token=tok or "x"), key("uat5-h3"))):
            r = await c.post(V1 + "/orders/manual", json=body, headers={"Idempotency-Key": hdr})
            codes.append(f"{r.status_code}/{r.json().get('code')}")
        n1 = len(await alpaca_orders(bc))
        rec("AC-33", "HALTED үед гарын order-ийн БҮХ зам хаагдана (Alpaca руу 0 дуудалт)",
            all(c_.startswith("409/system_halted") for c_ in codes) and n0 == n1,
            f"{codes} alpaca {n0}→{n1}")

        # ---------- AC-20: бүх 200 хариунд source ----------
        bad = []
        for p in ("/health", "/account", "/positions", "/orders", "/attribution",
                  "/system/state", "/market/quote/AAPL"):
            rr = await c.get(V1 + p)
            if rr.status_code == 200 and rr.json().get("source") != "alpaca_paper":
                bad.append(f"{p}={rr.json().get('source')}")
        rec("AC-20", "бодит арилжааны дараа ч бүх 200 хариу source=alpaca_paper", not bad, str(bad))

        # ---------- FE ----------
        fe = await c.get(FE + "/api/v1/positions")
        rec("FE", "frontend proxy нь бодит позицыг дамжуулна",
            fe.status_code == 200 and fe.json().get("source") == "alpaca_paper",
            f"{fe.status_code} positions={len(fe.json().get('positions', []))}")

    print("\n===SUMMARY===")
    for ac, name, ok, d in R:
        tag = "PASS" if ok is True else "FAIL" if ok is False else "INFO"
        print(f"{tag}\t{ac}\t{name}\t{d}")
    fails = [x for x in R if x[2] is False]
    print(f"\nTOTAL={len(R)} PASS={len([x for x in R if x[2] is True])} "
          f"FAIL={len(fails)} INFO={len([x for x in R if x[2] is None])}")
    return 1 if fails else 0


sys.exit(asyncio.run(main()))
