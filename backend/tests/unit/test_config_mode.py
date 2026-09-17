"""T-03 (ID=630) — config, mode resolution, live-egress хаалт."""
import pytest

from app.config.mode import ConfigError, TradingMode, resolve_mode
from app.config.settings import Settings


class Env:
    def __init__(self, **kw):
        self.ALPACA_ENV = kw.get("ALPACA_ENV", "paper")
        self.LIVE_TRADING_ACKNOWLEDGED = kw.get("LIVE_TRADING_ACKNOWLEDGED", False)
        self.LIVE_CHECKLIST_SIGNATURE = kw.get("LIVE_CHECKLIST_SIGNATURE")


def test_paper_is_default():
    assert resolve_mode(Env()) is TradingMode.PAPER


def test_live_requires_all_three_signals():
    # AC-12: гурвын аль нэг дутвал paper руу УНАХГҮЙ — алдаа гаргана.
    with pytest.raises(ConfigError):
        resolve_mode(Env(ALPACA_ENV="live"))
    with pytest.raises(ConfigError):
        resolve_mode(Env(ALPACA_ENV="live", LIVE_TRADING_ACKNOWLEDGED=True))
    assert (
        resolve_mode(
            Env(
                ALPACA_ENV="live",
                LIVE_TRADING_ACKNOWLEDGED=True,
                LIVE_CHECKLIST_SIGNATURE="ops@example:2026-09-16",
            )
        )
        is TradingMode.LIVE
    )


def test_limits_have_no_defaults(monkeypatch):
    """§17.1 / AC-13 — 10 хязгаарын аль нэг дутвал app эхлэхгүй."""
    for name in Settings.REQUIRED_LIMIT_FIELDS:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(Exception):
        Settings()


def test_settings_loads_when_all_limits_present(monkeypatch, limit_env):
    for k, v in limit_env.items():
        monkeypatch.setenv(k, v)
    s = Settings()
    assert str(s.MAX_ORDER_NOTIONAL) == "5000.00"
    assert s.WIND_DOWN_GRACE.total_seconds() == 900


# --- N-3: `DAILY_LOSS_LIMIT` нь далд БИШ, ил гэрээтэй ---


def test_a_positive_daily_loss_limit_is_refused(limit_env):
    """Эерэг утга нь чимээгүй бүтэн түгжээ болно (N-3).

    `r8` нь `pnl > limit`-ээр зөвшөөрдөг, breaker нь `pnl <= limit`-ээр
    зогсоодог: `+2000` бичвэл order бүр татгалзаж, breaker шууд унана —
    fail-closed боловч шалтгаан нь хаана ч харагдахгүй.
    """
    from pydantic import ValidationError

    from app.config.settings import Settings

    with pytest.raises(ValidationError) as exc:
        Settings(**{**limit_env, "DAILY_LOSS_LIMIT": "2000.00"})
    assert "DAILY_LOSS_LIMIT" in str(exc.value)
