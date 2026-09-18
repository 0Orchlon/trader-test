"""Grounding Checker (T-24, LLD §13, NFR-1, AC-9).

**Дүрэм:** `rationale` дахь тоон мэдэгдэл бүр нь `grounded_in`-д нэрлэгдсэн
tool call-ийн ХАРИУН дотор бодитоор байх ёстой. Байхгүй бол санал Risk
Agent хүртэл ОЧИХГҮЙ.

Энэ нь цензур биш, **харилцан яриа**: `unverified_claims` нь LLM рүү
буцна, тэр засаж дахин оролдож болно. Чимээгүй хаялт нь модельд юу буруу
болсныг хэлэхгүй тул давтагдана.

**Худал эерэгийн хаалт.** «20/50 EMA огтлолцол»-ийн 20, 50 нь ҮНЭ биш,
индикаторын цонх. Тэднийг мэдэгдэл гэж тоолбол бүх техник дүн шинжилгээ
унана. Тиймээс индикаторын контекст дэх тоог хасна — цагаан жагсаалт нь
ил, нууц биш.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

#: Тоон token: `-1,234.56`, `12%`, `0.5`.
NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")

#: Индикаторын цонхыг заадаг үг. Тоо нь эдгээрийн ХАЖУУД байвал мэдэгдэл биш.
WINDOW_TOKENS = (
    "ema", "sma", "ma", "rsi", "macd", "atr", "vwap", "bollinger", "stochastic",
    "day", "days", "week", "weeks", "month", "months", "period", "periods",
    "bar", "bars", "minute", "minutes", "hour", "hours", "fold", "folds",
    "хоног", "өдөр", "өдрийн", "цонх", "үе",
)
WINDOW_SET = frozenset(WINDOW_TOKENS)

#: Тоо ба индикаторын нэрийг тусгаарлаж БОЛОХ тэмдэгтүүд. Зөвхөн ЗЭРГЭЛДЭЭ
#: үг тоологдоно: «50 EMA дээр үнэ 402.00»-ийн 402.00 нь ҮНЭ хэвээр.
#: Өргөн цонх авбал өгүүлбэр дэх ямар ч индикатор бүх тоог далдална.
_GAP = r"[\s()/,\-]*[\d.,]*[\s()/,\-]*"
_WORD = r"[^\W\d_]+"
LEFT_RE = re.compile(rf"({_WORD}){_GAP}$", re.UNICODE)
RIGHT_RE = re.compile(rf"^{_GAP}({_WORD})", re.UNICODE)

#: Зэргэлдээ үгийг хайх хамгийн их зай.
CONTEXT_CHARS = 14

#: Харьцуулах нарийвчлал. Үүнээс доош ялгааг тоохгүй — float биш, Decimal.
PRECISION = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class GroundingResult:
    passed: bool
    unverified_claims: list[str] = field(default_factory=list)
    #: Хэдэн тоо шалгагдсан — «шалгалт хийгдсэн үү» гэдэг нь ил.
    checked_claims: int = 0

    def to_contract(self) -> dict:
        return {
            "passed": self.passed,
            "unverified_claims": list(self.unverified_claims),
            "checked_claims": self.checked_claims,
        }


def _normalize(token: str) -> Decimal | None:
    text = token.replace(",", "").rstrip("%")
    try:
        return Decimal(text).quantize(PRECISION)
    except (InvalidOperation, ValueError):
        return None


def _is_window(text: str, start: int, end: int) -> bool:
    left = LEFT_RE.search(text[max(0, start - CONTEXT_CHARS) : start])
    right = RIGHT_RE.search(text[end : end + CONTEXT_CHARS])
    for match in (left, right):
        if match and match.group(1).lower() in WINDOW_SET:
            return True
    return False


def extract_claims(rationale: str) -> list[str]:
    """Индикаторын цонхыг ХАСААД үлдсэн тоон token-ууд."""
    out: list[str] = []
    for match in NUMBER_RE.finditer(rationale):
        if _is_window(rationale, match.start(), match.end()):
            continue
        out.append(match.group())
    return out


def walk_numbers(payload: Any) -> Iterable[Decimal]:
    """Цитат payload-ийн БҮХ түвшнээс тоо цуглуулна — бүтэц гүн байж болно."""
    if isinstance(payload, bool):
        return
    if isinstance(payload, (int, Decimal)):
        yield Decimal(str(payload)).quantize(PRECISION)
    elif isinstance(payload, float):
        # Мөнгөн зам БИШ (энэ нь LLM-ийн цитат), гэхдээ ижил нарийвчлалд.
        yield Decimal(str(payload)).quantize(PRECISION)
    elif isinstance(payload, str):
        for match in NUMBER_RE.finditer(payload):
            value = _normalize(match.group())
            if value is not None:
                yield value
    elif isinstance(payload, dict):
        for value in payload.values():
            yield from walk_numbers(value)
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            yield from walk_numbers(value)


def check(
    rationale: str, cited_payloads: list[Any], *, tolerance: Decimal = Decimal("0")
) -> GroundingResult:
    """`tolerance` нь ХУВИЙН зөрүү (0 = яг таарна).

    Цитатгүй санал нь автоматаар унана: `grounded_in` хоосон байхад тоо
    хаанаас ирснийг шалгах боломжгүй — «шалгаагүй» нь «зөв» БИШ.
    """
    claims = extract_claims(rationale)
    if not claims:
        # Тоогүй үндэслэл нь grounding-ийн хувьд асуудалгүй: шалгах зүйлгүй.
        return GroundingResult(passed=True, unverified_claims=[], checked_claims=0)

    haystack = {n for payload in cited_payloads for n in walk_numbers(payload)}
    unverified = [c for c in claims if not _found(c, haystack, tolerance)]
    return GroundingResult(
        passed=not unverified,
        unverified_claims=unverified,
        checked_claims=len(claims),
    )


def _found(claim: str, haystack: set[Decimal], tolerance: Decimal) -> bool:
    value = _normalize(claim)
    if value is None:  # pragma: no cover - regex нь зөвхөн тоо олдог
        return False
    if value in haystack:
        return True
    if tolerance <= 0:
        return False
    for candidate in haystack:
        if candidate == 0:
            continue
        if abs(candidate - value) / abs(candidate) * Decimal("100") <= tolerance:
            return True
    return False
