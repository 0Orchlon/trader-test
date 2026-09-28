"""Санал бүрийн `grounded_in` нь ЗӨВХӨН өөрийнх нь уншилтууд байх ёстой.

Бүх quote-ыг цутгавал grounding нь «энэ тоо хаа нэгтээ бий юу» болж мөхөс
болно — өөр symbol-ын үнээр худал rationale давчихна (T-99).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents import runner


class _Gateway:
    def __init__(self) -> None:
        self.proposals: list[dict] = []

    async def dispatch(self, name, args, state, ctx):
        if name == "propose_order":
            self.proposals.append(dict(args))
        return {
            "ok": True,
            "tool_call_id": f"{name}:{args.get('symbol', '')}",
            "data": {"positions": []},
        }


def _call(name: str, **args) -> dict:
    import json

    return {"id": f"c-{name}", "function": {"name": name, "arguments": json.dumps(args)}}


def _settings() -> SimpleNamespace:
    return SimpleNamespace(RESEARCH_MAX_TOOL_TURNS=3, research_symbols=["AAPL", "BTC/USD"])


@pytest.fixture(autouse=True)
def _no_state(monkeypatch):
    async def fake_state_view(machine):
        return None

    monkeypatch.setattr(runner, "state_view", fake_state_view)


def _script(monkeypatch, turns: list[dict]) -> None:
    queue = list(turns)

    async def fake_call_local(settings, messages, tools):
        message = queue.pop(0) if queue else {"content": ""}
        return {"choices": [{"message": message}]}

    monkeypatch.setattr(runner, "_call_local", fake_call_local)


READS = [
    _call("get_account"),
    _call("get_positions"),
    _call("get_quote", symbol="AAPL"),
    _call("get_quote", symbol="BTC/USD"),
]


async def test_only_the_proposed_symbols_quote_is_cited(monkeypatch):
    _script(
        monkeypatch,
        [
            {"tool_calls": READS},
            {"tool_calls": [_call("propose_order", symbol="BTCUSD", side="buy")]},
        ],
    )
    gateway = _Gateway()

    await runner._run_local_loop(gateway, None, None, _settings(), "go", [])

    # `BTCUSD` ↔ `BTC/USD` таарна; AAPL-ийн quote ОГТ орохгүй.
    assert gateway.proposals[0]["grounded_in"] == [
        "get_account:",
        "get_positions:",
        "get_quote:BTC/USD",
    ]


async def test_a_symbol_with_no_quote_is_cited_without_one(monkeypatch):
    _script(
        monkeypatch,
        [
            {"tool_calls": READS},
            {"tool_calls": [_call("propose_order", symbol="TSLA", side="buy")]},
        ],
    )
    gateway = _Gateway()

    await runner._run_local_loop(gateway, None, None, _settings(), "go", [])

    assert gateway.proposals[0]["grounded_in"] == ["get_account:", "get_positions:"]


class _StaleQuoteGateway(_Gateway):
    """AAPL-ийн quote нь хуучирсан/алдаатай буцна — бусад уншилт хэвийн."""

    async def dispatch(self, name, args, state, ctx):
        result = await super().dispatch(name, args, state, ctx)
        if name == "get_quote" and args.get("symbol") == "AAPL":
            return {
                "ok": False,
                "tool_call_id": result["tool_call_id"],
                "data": None,
                "error": {"code": "stale", "message": "AAPL: quote хуучирсан"},
            }
        return result


async def test_a_failed_read_is_never_cited(monkeypatch):
    """Амжилтгүй уншилт citation болох ёсгүй: `ok: false` payload нь тухайн
    symbol-ын «нотолгоо» болж Decision Log-д бичигдэнэ (ROOT CAUSE G)."""
    _script(
        monkeypatch,
        [
            {"tool_calls": READS},
            {"tool_calls": [_call("propose_order", symbol="AAPL", side="buy")]},
        ],
    )
    gateway = _StaleQuoteGateway()

    await runner._run_local_loop(gateway, None, None, _settings(), "go", [])

    assert gateway.proposals[0]["grounded_in"] == ["get_account:", "get_positions:"]


async def test_the_text_repair_path_cites_the_same_narrow_set(monkeypatch):
    _script(
        monkeypatch,
        [
            {"tool_calls": READS},
            {
                "content": '{"symbol": "AAPL", "side": "buy", "qty": "1", '
                '"order_type": "market", "rationale": "ask 100.00"}'
            },
        ],
    )
    gateway = _Gateway()

    await runner._run_local_loop(gateway, None, None, _settings(), "go", [])

    assert gateway.proposals[0]["grounded_in"] == [
        "get_account:",
        "get_positions:",
        "get_quote:AAPL",
    ]
