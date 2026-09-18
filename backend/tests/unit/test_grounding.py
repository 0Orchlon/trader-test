"""T-24 (ID=651) — Grounding Checker (NFR-1, AC-9).

«Байхгүйг мэдээлэх, таамаглахгүй.» Тоон мэдэгдэл бүр цитат tool call-ийн
payload-д бодитоор байх ёстой.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.agents.grounding import check, extract_claims, walk_numbers

ZERO = Decimal("0")


def test_a_number_present_in_the_citation_passes():
    result = check("Сүүлийн үнэ 221.50 байна.", [{"last": "221.50"}], tolerance=ZERO)
    assert result.passed
    assert result.unverified_claims == []
    assert result.checked_claims == 1


def test_an_invented_number_fails():
    result = check("Сүүлийн үнэ 999.99 байна.", [{"last": "221.50"}], tolerance=ZERO)
    assert not result.passed
    assert result.unverified_claims == ["999.99"]


def test_indicator_windows_are_not_claims():
    """«20/50 EMA» нь ҮНЭ биш — худал эерэг үүсгэхгүй (LLD §13)."""
    assert extract_claims("20/50 EMA огтлолцол, RSI 14 period") == []


def test_a_price_next_to_an_indicator_is_still_checked():
    claims = extract_claims("50 EMA дээр үнэ 402.00 хүрэв")
    assert "402.00" in claims


def test_thousand_separators_normalize():
    assert check("Эквити 104,238.17", [{"equity": "104238.17"}], tolerance=ZERO).passed


def test_percent_sign_is_stripped_before_comparison():
    assert check("Өсөлт 1.8%", [{"ratio": "1.8"}], tolerance=ZERO).passed


def test_numbers_are_found_at_any_depth():
    payload = {"bars": [{"c": {"close": "221.50"}}]}
    assert list(walk_numbers(payload)) == [Decimal("221.500000")]


def test_a_rationale_with_no_numbers_passes():
    result = check("Чиг хандлага эерэг байна.", [], tolerance=ZERO)
    assert result.passed and result.checked_claims == 0


def test_no_citations_means_every_number_is_unverified():
    result = check("Үнэ 221.50", [], tolerance=ZERO)
    assert not result.passed and result.unverified_claims == ["221.50"]


def test_tolerance_zero_requires_an_exact_match():
    assert not check("Үнэ 221.51", [{"last": "221.50"}], tolerance=ZERO).passed


def test_tolerance_allows_a_declared_percentage_drift():
    """Тэвчээр нь ИЛ config — чимээгүй зөөлрөлт биш (LLD §13)."""
    assert check("Үнэ 221.51", [{"last": "221.50"}], tolerance=Decimal("1")).passed


def test_booleans_are_not_numbers():
    assert list(walk_numbers({"ok": True, "blocked": False})) == []


# --- adversarial suite (T-24) ---


@pytest.mark.parametrize(
    "rationale,payloads",
    [
        ("Delisted ABCD-ийн үнэ 12.34", [{"error": {"code": "invalid_symbol"}}]),
        ("Өгөгдөлгүй мужид дундаж 55.10", [{"error": {"code": "no_data"}, "data": None}]),
        ("Зохиосон эзлэхүүн 1,250,000", [{"volume": "812345"}]),
        ("Тоо 402.00 байсан", [None]),
    ],
)
def test_adversarial_cases_report_absence_instead_of_guessing(rationale, payloads):
    result = check(rationale, payloads, tolerance=ZERO)
    assert not result.passed
    assert result.unverified_claims
