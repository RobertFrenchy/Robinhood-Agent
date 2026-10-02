"""Settings loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _float(name: str, default: float) -> float:
    return float(_env(name, str(default)))


def _int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


@dataclass(frozen=True)
class RiskLimits:
    max_order_usd: float = 200.0
    max_position_pct: float = 0.20
    min_cash_usd: float = 100.0
    max_orders_per_day: int = 6
    max_daily_loss_pct: float = 0.03
    min_confidence: float = 0.6


@dataclass(frozen=True)
class Settings:
    trading_mode: str = "paper"
    watchlist: tuple[str, ...] = ("SPY", "QQQ")
    cycle_minutes: int = 30
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "high"
    rh_username: str | None = None
    rh_password: str | None = None
    rh_mfa_secret: str | None = None
    data_dir: Path = Path("data")
    kill_switch_file: Path = Path("data/KILL")
    paper_starting_cash: float = 10_000.0
    risk: RiskLimits = field(default_factory=RiskLimits)

    @property
    def is_live(self) -> bool:
        return self.trading_mode == "live"


def load_settings(env_file: str | None = ".env") -> Settings:
    if env_file:
        load_dotenv(env_file)

    mode = (_env("TRADING_MODE", "paper") or "paper").lower()
    if mode not in ("live", "paper"):
        raise ValueError(f"TRADING_MODE must be 'live' or 'paper', got {mode!r}")

    watchlist = tuple(
        s.strip().upper() for s in (_env("WATCHLIST", "SPY,QQQ") or "").split(",") if s.strip()
    )
    if not watchlist:
        raise ValueError("WATCHLIST must contain at least one symbol")

    data_dir = Path(_env("DATA_DIR", "data"))
    return Settings(
        trading_mode=mode,
        watchlist=watchlist,
        cycle_minutes=_int("CYCLE_MINUTES", 30),
        claude_model=_env("CLAUDE_MODEL", "claude-opus-5-5"),
        claude_effort=_env("CLAUDE_EFFORT", "high"),
        rh_username=_env("RH_USERNAME"),
        rh_password=_env("RH_PASSWORD"),
        rh_mfa_secret=_env("RH_MFA_SECRET"),
        data_dir=data_dir,
        kill_switch_file=Path(_env("KILL_SWITCH_FILE", str(data_dir / "KILL"))),
        paper_starting_cash=_float("PAPER_STARTING_CASH", 10_000.0),
        risk=RiskLimits(
            max_order_usd=_float("MAX_ORDER_USD", 200.0),
            max_position_pct=_float("MAX_POSITION_PCT", 0.20),
            min_cash_usd=_float("MIN_CASH_USD", 100.0),
            max_orders_per_day=_int("MAX_ORDERS_PER_DAY", 6),
            max_daily_loss_pct=_float("MAX_DAILY_LOSS_PCT", 0.03),
            min_confidence=_float("MIN_CONFIDENCE", 0.6),
        ),
    )
