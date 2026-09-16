"""T-40 (ID=667) — pin хийгээгүй хамаарал БАЙХГҮЙ (AC-28).

Давтагдах build-ийн урьдчилсан нөхцөл: хамаарал бүр ЯГ нэг хувилбарт
уягдсан байх. `>=`, `~=`, `^`, эсвэл хувилбаргүй нэр нь «өнөөдөр
ажиллаж байсан» build-ийг маргааш өөр болгоно.

Lockfile нь мөн ЗААВАЛ: pin нь шууд хамаарлыг барина, lockfile нь
дамжсан хамаарлыг.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
FRONTEND = REPO / "frontend"
CONTRACTS = REPO / "contracts"

#: `name==1.2.3` эсвэл `name[extra]==1.2.3`. Бусад бүх хэлбэр татгалзана.
PINNED = re.compile(r"^[A-Za-z0-9._-]+(\[[A-Za-z0-9,._-]+\])?==[0-9][^;]*$")

#: npm-д яг хувилбар: `1.2.3`. `^1.2.3`, `~1.2.3`, `*`, `latest` татгалзана.
NPM_EXACT = re.compile(r"^\d+\.\d+\.\d+")


def test_backend_dependencies_are_exactly_pinned():
    pyproject = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    every = list(project["dependencies"])
    for extras in project.get("optional-dependencies", {}).values():
        every += list(extras)
    loose = [dep for dep in every if not PINNED.match(dep)]
    assert loose == [], f"pin хийгээгүй Python хамаарал (AC-28): {loose}"


def test_backend_lockfile_exists_and_is_fully_pinned():
    lockfile = BACKEND / "requirements.lock"
    assert lockfile.exists(), "requirements.lock БАЙХГҮЙ — дамжсан хамаарал барьцаагүй"
    loose = [
        line.strip()
        for line in lockfile.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#") and not PINNED.match(line.strip())
    ]
    assert loose == [], f"lockfile-д pin хийгээгүй мөр: {loose}"


def test_every_declared_dependency_is_present_in_the_lockfile():
    """pyproject ↔ lockfile нь ЗӨРӨХГҮЙ — хоёр эх сурвалж болохгүй."""
    pyproject = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    locked = {
        line.split("==")[0].lower()
        for line in (BACKEND / "requirements.lock").read_text(encoding="utf-8").splitlines()
        if "==" in line
    }
    declared = [
        dep.split("==")[0].split("[")[0].lower() for dep in pyproject["project"]["dependencies"]
    ]
    missing = [name for name in declared if name not in locked]
    assert missing == [], f"pyproject-д байгаа ч lockfile-д алга: {missing}"


def _npm_loose(package_json: Path) -> list[str]:
    data = json.loads(package_json.read_text(encoding="utf-8"))
    out: list[str] = []
    for section in ("dependencies", "devDependencies"):
        for name, spec in data.get(section, {}).items():
            if not NPM_EXACT.match(str(spec)):
                out.append(f"{package_json.parent.name}: {name}@{spec}")
    return out


def test_npm_dependencies_are_exactly_pinned():
    loose = _npm_loose(FRONTEND / "package.json") + _npm_loose(CONTRACTS / "package.json")
    assert loose == [], f"pin хийгээгүй npm хамаарал (AC-28): {loose}"


def test_npm_lockfiles_exist():
    for surface in (FRONTEND, CONTRACTS):
        assert (surface / "package-lock.json").exists(), f"{surface.name}: package-lock.json алга"


def test_the_detector_actually_rejects_loose_specifiers():
    """Хаалга ажиллаж байгааг батална — хоосон шалгалт нь хамгаалалт биш."""
    assert PINNED.match("fastapi==0.115.6")
    assert PINNED.match("uvicorn[standard]==0.34.0")
    assert not PINNED.match("fastapi>=0.115")
    assert not PINNED.match("fastapi~=0.115.0")
    assert not PINNED.match("fastapi")
    assert NPM_EXACT.match("18.3.1")
    assert not NPM_EXACT.match("^18.3.1")
    assert not NPM_EXACT.match("latest")
