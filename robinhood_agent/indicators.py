"""Small, dependency-free technical indicators used to summarise market data for Claude."""

from __future__ import annotations

import math
from collections.abc import Sequence

from .models import Bar


def sma(values: Sequence[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    return sum(values[-window:]) / window


def rsi(values: Sequence[float], window: int = 14) -> float | None:
    """Wilder's RSI over the last `window` periods."""
    if len(values) <= window:
        return None
    gains, losses = 0.0, 0.0
    for prev, cur in zip(values[-window - 1 : -1], values[-window:]):
        change = cur - prev
        if change >= 0:
            gains += change
        else:
            losses -= change
    if losses == 0:
        return 100.0
    rs = (gains / window) / (losses / window)
    return 100.0 - 100.0 / (1.0 + rs)


def pct_change(values: Sequence[float], periods: int) -> float | None:
    if len(values) <= periods or values[-periods - 1] == 0:
        return None
    return values[-1] / values[-periods - 1] - 1.0


def annualized_volatility(values: Sequence[float], window: int = 20) -> float | None:
    if len(values) <= window:
        return None
    rets = [
        math.log(cur / prev)
        for prev, cur in zip(values[-window - 1 : -1], values[-window:])
        if prev > 0 and cur > 0
    ]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def summarize(bars: Sequence[Bar]) -> dict[str, float | None]:
    """Compute a compact feature set from daily bars."""
    closes = [b.close for b in bars]

    def r(x: float | None, nd: int = 4) -> float | None:
        return None if x is None else round(x, nd)

    return {
        "last_close": r(closes[-1] if closes else None, 2),
        "sma_10": r(sma(closes, 10), 2),
        "sma_20": r(sma(closes, 20), 2),
        "sma_50": r(sma(closes, 50), 2),
        "rsi_14": r(rsi(closes, 14), 1),
        "ret_1d": r(pct_change(closes, 1)),
        "ret_5d": r(pct_change(closes, 5)),
        "ret_20d": r(pct_change(closes, 20)),
        "vol_20d_annualized": r(annualized_volatility(closes, 20)),
    }
