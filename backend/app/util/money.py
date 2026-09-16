"""Money-ийн хилийн дүрэм (LLD §4, AC-25).

Домэйнд `Decimal`, API хил дээр `str(quantize(0.01))`. `float` мөнгөн замд
хоригтой — статик тест (tests/static) үүнийг барина.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

CENT = Decimal("0.01")
QTY_STEP = Decimal("0.000000001")


def money(value: str | int | Decimal) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:  # pragma: no cover - хамгаалалт
        raise ValueError(f"мөнгөн утга биш: {value!r}") from exc


def money_str(value: Decimal | None) -> str | None:
    r"""contracts.yaml `Money` — `^-?[0-9]+\.[0-9]{2}$`."""
    if value is None:
        return None
    return str(money(value).quantize(CENT))


def qty_str(value: Decimal | None) -> str | None:
    """contracts.yaml `Quantity` — 9 хүртэл бутархай, ардаа тэггүй."""
    if value is None:
        return None
    normalized = money(value).normalize()
    text = format(normalized, "f")
    return text
