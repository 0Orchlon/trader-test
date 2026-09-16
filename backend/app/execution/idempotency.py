"""`client_order_id`-ийн деривац (LLD §9.2, T-08).

Ижил key + ижил талбар → ижил `client_order_id` → DB-ийн `unique` барина.
Ижил key + ӨӨР талбар → hash өөр; тиймээс key-ийн бүртгэл ТУСАД НЬ шалгагдаж
409 `idempotency_conflict` буцна (зөвхөн hash дээр түшиглэвэл өөр биетэй
давхар order дамжина).
"""
from __future__ import annotations

import json
from hashlib import blake2s

from app.broker.models import OrderIntent

PREFIX = "p3-"


def canonical_order_fields(req: OrderIntent) -> str:
    return json.dumps(
        {
            "symbol": req.symbol.upper(),
            "side": req.side.value,
            "qty": str(req.qty),
            "order_type": req.order_type.value,
            "time_in_force": req.time_in_force.value,
            "limit_price": str(req.limit_price) if req.limit_price is not None else None,
            "stop_price": str(req.stop_price) if req.stop_price is not None else None,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def request_hash(req: OrderIntent) -> str:
    return blake2s(canonical_order_fields(req).encode(), digest_size=16).hexdigest()


def derive_client_order_id(idempotency_key: str, req: OrderIntent) -> str:
    digest = blake2s(
        (idempotency_key + "|" + canonical_order_fields(req)).encode(), digest_size=12
    ).hexdigest()
    return PREFIX + digest
