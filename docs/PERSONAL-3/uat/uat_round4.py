"""PERSONAL-3 UAT — 4-р тойрог: Alpaca credential-ийн шалгалт.

Ажиллуулах:
    ALPACA_API_KEY=... ALPACA_API_SECRET=... python uat_round4.py

TLS interception хийдэг сүлжээнд `SSL_CERT_FILE`-ыг Windows-ийн үндэс
гэрчилгээний PEM рүү заа (тайлангийн §6).
"""
import os
import sys

import httpx

KEY = os.environ.get("ALPACA_API_KEY", "")
SECRET = os.environ.get("ALPACA_API_SECRET", "")
BASE = "https://paper-api.alpaca.markets"

if not KEY or not SECRET:
    sys.exit("ALPACA_API_KEY / ALPACA_API_SECRET шаардлагатай")
if KEY == SECRET:
    print("АНХААР: key ID ба secret ижил байна — Alpaca хоёр ӨӨР утга шаарддаг")

r = httpx.get(
    BASE + "/v2/account",
    headers={"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SECRET},
    timeout=30.0,
)
print(f"GET {BASE}/v2/account -> {r.status_code} {r.text[:200]}")
if r.status_code == 401:
    sys.exit("credential хүчингүй (401 unauthorized) — broker-ээс хамаарах AC-ууд шалгагдахгүй")
print("credential ажиллаж байна — broker-ээс хамаарах AC-ууд шалгагдах боломжтой")
