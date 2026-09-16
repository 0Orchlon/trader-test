"""T-14 (ID=641) — статик хаалтууд R-1…R-5 (LLD §18.2).

Эдгээр нь энгийн pytest тест — тусдаа хэрэгсэл нэмэхгүй («хоёр дахь эх
үүсгэхгүй» зарчим).
"""
from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"


def _modules() -> list[tuple[str, ast.Module]]:
    out = []
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(APP.parent).with_suffix("")
        out.append((".".join(rel.parts), ast.parse(path.read_text(encoding="utf-8"), str(path))))
    return out


# --- R-1: `submit_order`-ийг зөвхөн `app.execution` дуудна (AC-3, AC-31) ---

#: `app.broker.alpaca` нь методыг ТОДОРХОЙЛНО, дуудахгүй — тодорхойлолт нь
#: дуудалт биш тул хасагдана.
R1_ALLOWED_PREFIXES = ("app.execution",)


def test_r1_submit_order_is_called_only_from_execution():
    offenders = []
    for module, tree in _modules():
        if module.startswith(R1_ALLOWED_PREFIXES):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "submit_order"
            ):
                offenders.append(f"{module}:{node.lineno}")
    assert offenders == [], (
        "BrokerPort.submit_order-ийг зөвхөн app.execution дуудна (LLD §18.2 R-1). "
        f"Зөрчил: {offenders}"
    )


# --- R-2: `app.risk` нь `app.api`, `app.agents`, `app.broker.alpaca`-г import хийхгүй ---

#: `app.broker.models` нь давхаргын ХАМААРАЛ биш, **нийтлэг толь** (LLD §4) —
#: бүх давхарга үүнийг хуваалцана. Хориглогдох нь adapter ба port.
R2_FORBIDDEN = ("app.api", "app.agents", "app.broker.alpaca", "app.broker.port", "app.stream")


def test_r2_risk_has_no_upward_imports():
    offenders = []
    for module, tree in _modules():
        if not module.startswith("app.risk"):
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.startswith(R2_FORBIDDEN):
                    offenders.append(f"{module}:{node.lineno} → {name}")
    assert offenders == [], f"app.risk-ийн дээшээ чиглэсэн import (R-2): {offenders}"


# --- R-3: мөнгөн замд `float(` БАЙХГҮЙ (AC-25) ---

R3_MODULES = ("app.risk", "app.execution", "app.broker")


def test_r3_no_float_on_money_paths():
    offenders = []
    for module, tree in _modules():
        if not module.startswith(R3_MODULES):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float":
                offenders.append(f"{module}:{node.lineno}")
    assert offenders == [], f"мөнгөн замд float() хоригтой (R-3): {offenders}"


# --- R-4: `datetime.now()` / naive datetime БАЙХГҮЙ (AC-26) ---

#: `app.util.time` нь `now_utc()`-ийн ЦОРЫН ГАНЦ тодорхойлолт.
R4_ALLOWED = ("app.util.time",)


def test_r4_no_raw_datetime_now():
    offenders = []
    for module, tree in _modules():
        if module.startswith(R4_ALLOWED):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_now = (
                isinstance(func, ast.Attribute)
                and func.attr in ("now", "utcnow", "today")
                and isinstance(func.value, ast.Name)
                and func.value.id in ("datetime", "date")
            )
            if is_now:
                offenders.append(f"{module}:{node.lineno}")
    assert offenders == [], f"datetime.now() хоригтой, now_utc() ашигла (R-4): {offenders}"


# --- R-5: coverage тойрох тохиргоо БАЙХГҮЙ (AC-27) ---

R5_FORBIDDEN_TOKENS = (
    "--no-cov",
    "fail_under = 0",
    "NETOS_GATES_SKIP",
    "gates.skip",
    "# pragma: no cover-all",
)


def test_r5_no_coverage_bypass_in_config():
    root = APP.parent
    targets = [root / "pyproject.toml", root.parent / "ci" / "github-workflow-ci.yml"]
    offenders = []
    for path in targets:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        offenders += [f"{path.name}: {t}" for t in R5_FORBIDDEN_TOKENS if t in text]
    assert offenders == [], f"coverage тойрох тохиргоо (R-5): {offenders}"


# --- хаалганууд ХООСОН биш гэдгийн нотолгоо ---


def _calls_submit_order(source: str) -> bool:
    tree = ast.parse(source)
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "submit_order"
        for n in ast.walk(tree)
    )


def test_r1_detector_actually_detects():
    """Хаалга ажиллаж байгааг батална — хоосон шалгалт нь хамгаалалт биш."""
    assert _calls_submit_order("await self.broker.submit_order(order)")
    assert not _calls_submit_order("await self.broker.get_account()")
