import pytest

from robinhood_agent.indicators import pct_change, rsi, sma, summarize
from robinhood_agent.models import Bar


def test_sma():
    assert sma([1, 2, 3, 4], 2) == 3.5
    assert sma([1], 2) is None


def test_rsi_extremes():
    assert rsi(list(range(1, 20)), 14) == 100.0
    assert rsi(list(range(20, 1, -1)), 14) == pytest.approx(0.0)


def test_pct_change():
    assert pct_change([100, 110], 1) == pytest.approx(0.10)
    assert pct_change([100], 1) is None


def test_summarize_handles_short_history():
    bars = [Bar("", 1, 1, 1, c, 0) for c in (10, 11, 12)]
    out = summarize(bars)
    assert out["last_close"] == 12
    assert out["sma_20"] is None
