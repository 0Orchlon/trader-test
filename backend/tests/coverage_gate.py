"""Coverage gate (T-36, LLD §18.3, AC-27).

Босго нь ЗАМЫН БҮЛГЭЭР — нийт хувь нь өндөр атлаа эрсдэлийн зам хоосон
байж болно:

| Бүлэг | Босго | Шалтгаан |
|---|---|---|
| `app/risk/**` | 100% line **+ branch** | Энэ бол мөнгө зогсоодог хаалга |
| Order илгээх зам | ≥ 90% | `app/execution`, `app/api/routes_orders.py`, `app/approvals` |

`pytest --cov` дуусахад ажиллана — **тусдаа команд, тусдаа хэрэгсэл
БАЙХГҮЙ** (`plan.md`-ийн «хоёр дахь эх үүсгэхгүй»).

Босгыг сулруулах нь `tests/static/test_secret_scanner.py`-ийн R-5-тай
ижил түвшний өөрчлөлт: энэ файл нь review-д ил гарна.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

#: (бүлгийн нэр, зам хайх урьдчилгаа, шаардлагатай хувь)
GATES: tuple[tuple[str, tuple[str, ...], float], ...] = (
    # Файл НЭРЛЭХГҮЙ, БҮЛЭГ бүхэлдээ: нэрлэсэн жагсаалт нь шинэ файлыг
    # (жишээ нь `breaker.py`) чимээгүй хаалганаас гадуур үлдээдэг байв (B-3).
    ("risk", ("app/risk/",), 100.0),
    (
        "order-path",
        ("app/execution/", "app/api/routes_orders.py", "app/approvals/"),
        90.0,
    ),
)

#: Хэмжигдэхгүй файлууд. Жагсаалт нь БОГИНО бөгөөд шалтгаантай — урт болох
#: нь gate-ийг чимээгүй сулруулах хэлбэр.
EXCLUDED = (
    "app/broker/port.py",  # Protocol — ажиллах код БАЙХГҮЙ
    "app/migrate.py",  # CLI орох цэг
    "app/system/scheduler.py",  # APScheduler-ийн утаслалт; job-ууд тусад нь
)


def _normalise(path: str) -> str:
    return path.replace("\\", "/")


def evaluate(files: dict[str, dict]) -> list[str]:
    """coverage JSON-ийн `files` → зөрчлийн жагсаалт. Цэвэр функц."""
    failures: list[str] = []
    for name, prefixes, threshold in GATES:
        covered = 0
        total = 0
        matched: list[str] = []
        for path, entry in files.items():
            normalised = _normalise(path)
            if any(excluded in normalised for excluded in EXCLUDED):
                continue
            if not any(prefix in normalised for prefix in prefixes):
                continue
            matched.append(normalised)
            summary = entry["summary"]
            # Line + branch НИЙЛЭЭД — зөвхөн мөрөөр хэмжих нь салаалалтыг
            # далдална (`if` бүрийн нэг тал л ажилласан байж болно).
            total += summary["num_statements"] + summary.get("num_branches", 0)
            covered += summary["covered_lines"] + summary.get("covered_branches", 0)
        if not matched:
            failures.append(f"{name}: хэмжигдсэн файл ОЛДСОНГҮЙ ({prefixes})")
            continue
        percent = 100.0 if total == 0 else covered * 100.0 / total
        if percent + 1e-9 < threshold:
            failures.append(
                f"{name}: {percent:.2f}% < {threshold:.0f}% — файлууд: {sorted(matched)}"
            )
    return failures


def check(cov) -> list[str]:
    """`coverage.Coverage` объектоос JSON тайлан гаргаж шалгана."""
    with tempfile.TemporaryDirectory() as directory:
        outfile = Path(directory) / "coverage.json"
        cov.json_report(outfile=str(outfile))
        report = json.loads(outfile.read_text(encoding="utf-8"))
    return evaluate(report["files"])
