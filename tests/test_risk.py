from pathlib import Path

import pytest

from robinhood_agent.config import RiskLimits
from robinhood_agent.models import AccountSnapshot, Position, TradeDecision
from robinhood_agent.risk import DailyState, RiskManager

LIMITS = RiskLimits(
    max_order_usd=200,
    max_position_pct=0.2,
    min_cash_usd=100,
    max_orders_per_day=3,
    max_daily_loss_pct=0.03,
    min_confidence=0.6,
)


def d(symbol, action, dollars, confidence=0.8):
    return TradeDecision(symbol=symbol, action=action, dollars=dollars, confidence=confidence, rationale="")


@pytest.fixture
def rm(tmp_path: Path):
    return RiskManager(LIMITS, ("SPY", "AAPL", "MSFT"), tmp_path / "KILL")


ACCOUNT = AccountSnapshot(
    cash=1000,
    equity=2000,
    positions={"AAPL": Position("AAPL", 2, 100, 150)},  # $300 held
)
PRICES = {"SPY": 500.0, "AAPL": 150.0, "MSFT": 400.0, "TSLA": 250.0}


def daily(**kw):
    return DailyState(date="2026-01-01", start_equity=kw.pop("start_equity", 2000), **kw)


def test_buy_capped_by_max_order(rm):
    ok, bad = rm.review([d("SPY", "buy", 1000)], ACCOUNT, PRICES, daily())
    assert [(o.symbol, o.dollars) for o in ok] == [("SPY", 200)]
    assert not bad


def test_buy_capped_by_position_limit(rm):
    # 20% of 2000 = 400 max position; already hold 300 of AAPL -> 100 room
    ok, _ = rm.review([d("AAPL", "buy", 200)], ACCOUNT, PRICES, daily())
    assert ok[0].dollars == 100


def test_buy_respects_cash_reserve(rm):
    poor = AccountSnapshot(cash=150, equity=2000, positions={})
    ok, _ = rm.review([d("SPY", "buy", 200)], poor, PRICES, daily())
    assert ok[0].dollars == 50


def test_cash_is_shared_across_buys(rm):
    poor = AccountSnapshot(cash=350, equity=2000, positions={})
    ok, bad = rm.review([d("SPY", "buy", 200), d("MSFT", "buy", 200)], poor, PRICES, daily())
    assert sum(o.dollars for o in ok) == 250
    assert len(ok) == 2 and not bad


def test_rejects_low_confidence_and_off_watchlist(rm):
    ok, bad = rm.review(
        [d("SPY", "buy", 100, confidence=0.3), d("TSLA", "buy", 100)], ACCOUNT, PRICES, daily()
    )
    assert not ok
    assert {r.symbol for r in bad} == {"SPY", "TSLA"}


def test_no_shorting(rm):
    ok, bad = rm.review([d("SPY", "sell", 100)], ACCOUNT, PRICES, daily())
    assert not ok and "shorting" in bad[0].reason


def test_sell_full_position_closes_cleanly(rm):
    ok, _ = rm.review([d("AAPL", "sell", 299)], ACCOUNT, PRICES, daily())
    assert ok[0].quantity == 2


def test_partial_sell(rm):
    ok, _ = rm.review([d("AAPL", "sell", 150)], ACCOUNT, PRICES, daily())
    assert ok[0].quantity == pytest.approx(1.0)


def test_daily_loss_blocks_buys_but_allows_sells(rm):
    state = daily(start_equity=2100)  # equity 2000 -> ~4.8% drawdown
    ok, bad = rm.review([d("SPY", "buy", 100), d("AAPL", "sell", 150)], ACCOUNT, PRICES, state)
    assert [o.side for o in ok] == ["sell"]
    assert "daily loss" in bad[0].reason


def test_kill_switch_halts_everything(rm):
    rm.kill_switch_file.touch()
    ok, bad = rm.review([d("AAPL", "sell", 150)], ACCOUNT, PRICES, daily())
    assert not ok and "kill switch" in bad[0].reason


def test_daily_order_limit(rm):
    ok, bad = rm.review(
        [d("SPY", "buy", 10), d("MSFT", "buy", 10)], ACCOUNT, PRICES, daily(orders_placed=2)
    )
    assert len(ok) == 1 and len(bad) == 1


def test_one_order_per_symbol(rm):
    ok, bad = rm.review([d("SPY", "buy", 10), d("SPY", "buy", 10)], ACCOUNT, PRICES, daily())
    assert len(ok) == 1 and len(bad) == 1


def test_hold_is_ignored(rm):
    ok, bad = rm.review([d("SPY", "hold", 0)], ACCOUNT, PRICES, daily())
    assert not ok and not bad
