"""T-01 / T-05 (ID=628, ID=632) — secret scanner + лог шүүлтүүр.

Хоёулаа НЭГ хэв маягийн жагсаалтыг (`app.audit.redact`) ашиглана — хоёр дахь
эх үүсгэхгүй.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

from app.audit import logging as audit_logging
from app.audit.redact import REDACTED, SECRET_VALUE_PATTERNS

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Тестийн өөрийн fixture, гэрээний жишээ — зориудаар хуурамч утгууд.
SCAN_EXCLUDE_SUFFIXES = (".lock", ".png", ".ico", ".svg")
SCAN_EXCLUDE_PARTS = (
    "node_modules",
    ".venv",
    "tests/unit/test_redact.py",
    "tests/static/test_secret_scanner.py",
    "backend/app/audit/redact.py",
)


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    files = []
    for line in out.stdout.splitlines():
        if any(part in line for part in SCAN_EXCLUDE_PARTS):
            continue
        path = REPO_ROOT / line
        if path.suffix in SCAN_EXCLUDE_SUFFIXES or not path.is_file():
            continue
        files.append(path)
    return files


def test_no_secret_shaped_strings_are_committed():
    hits: list[str] = []
    for path in _tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_VALUE_PATTERNS:
            for match in pattern.finditer(text):
                hits.append(f"{path.relative_to(REPO_ROOT)}: {match.group(0)[:24]}…")
    assert hits == [], f"repo-д secret хэлбэрийн мөр байна: {hits}"


@pytest.mark.parametrize(
    "message",
    [
        "Alpaca руу холбогдлоо key=PKTEST1234567890ABCD",
        "Authorization: Bearer sk-live-0123456789abcdef",
    ],
)
def test_logging_filter_redacts(message, caplog):
    logger = logging.getLogger("p3.secret-test")
    logger.addFilter(audit_logging.RedactingFilter())
    with caplog.at_level(logging.INFO, logger="p3.secret-test"):
        logger.info(message)
    rendered = caplog.text
    assert REDACTED in rendered
    for pattern in SECRET_VALUE_PATTERNS:
        assert not pattern.search(rendered), f"лог дээр secret үлдсэн: {rendered}"
