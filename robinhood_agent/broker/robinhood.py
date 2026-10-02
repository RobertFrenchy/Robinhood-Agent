"""Robinhood broker backed by the unofficial `robin_stocks` library.

Robinhood does not publish an official equities API. `robin_stocks` drives the same private
endpoints as the Robinhood app, so it can break without notice and is not sanctioned by
Robinhood. Use at your own risk.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pyotp
import robin_stocks.robinhood as rh

from ..models import AccountSnapshot, Bar, OrderResult, Position

log = logging.getLogger(__name__)


def _f(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class RobinhoodBroker:
    def __init__(self, username: str, password: str, mfa_secret: str | None = None):
        if not username or not password:
            raise ValueError("RH_USERNAME and RH_PASSWORD are required for the Robinhood broker")
        self._username = username
        self._password = password
        self._mfa_secret = mfa_secret
        self._logged_in = False

    # ---- session ----

    def login(self) -> None:
        mfa_code = pyotp.TOTP(self._mfa_secret).now() if self._mfa_secret else None
        rh.login(
            username=self._username,
            password=self._password,
            mfa_code=mfa_code,
            store_session=True,
        )
        self._logged_in = True
        log.info("Logged in to Robinhood as %s", self._username)

    def _ensure_login(self) -> None:
        if not self._logged_in:
            self.login()

    # ---- read ----

    def account(self) -> AccountSnapshot:
        self._ensure_login()
        profile = rh.load_account_profile() or {}
        portfolio = rh.load_portfolio_profile() or {}
        holdings = rh.build_holdings() or {}

        positions = {
            symbol: Position(
                symbol=symbol,
                quantity=_f(h.get("quantity")),
                average_cost=_f(h.get("average_buy_price")),
                price=_f(h.get("price")),
            )
            for symbol, h in holdings.items()
            if _f(h.get("quantity")) > 0
        }
        cash = _f(profile.get("buying_power"))
        equity = _f(portfolio.get("equity")) or cash + sum(p.market_value for p in positions.values())
        return AccountSnapshot(cash=cash, equity=equity, positions=positions)

    def latest_prices(self, symbols: list[str]) -> dict[str, float]:
        self._ensure_login()
        prices = rh.get_latest_price(symbols, includeExtendedHours=False) or []
        return {s: _f(p) for s, p in zip(symbols, prices) if _f(p) > 0}

    def daily_bars(self, symbol: str) -> list[Bar]:
        self._ensure_login()
        rows = rh.get_stock_historicals(symbol, interval="day", span="3month") or []
        return [
            Bar(
                begins_at=row.get("begins_at", ""),
                open=_f(row.get("open_price")),
                high=_f(row.get("high_price")),
                low=_f(row.get("low_price")),
                close=_f(row.get("close_price")),
                volume=_f(row.get("volume")),
            )
            for row in rows
            if row
        ]

    def is_market_open(self) -> bool:
        self._ensure_login()
        now = datetime.now(timezone.utc)
        hours = rh.get_market_hours("XNYS", now.strftime("%Y-%m-%d")) or {}
        if not hours.get("is_open"):
            return False
        try:
            opens = datetime.fromisoformat(hours["opens_at"].replace("Z", "+00:00"))
            closes = datetime.fromisoformat(hours["closes_at"].replace("Z", "+00:00"))
        except (KeyError, AttributeError, ValueError):
            return False
        return opens <= now < closes

    # ---- write ----

    def buy_dollars(self, symbol: str, dollars: float) -> OrderResult:
        self._ensure_login()
        raw = rh.order_buy_fractional_by_price(symbol, round(dollars, 2), timeInForce="gfd")
        return self._result(symbol, "buy", dollars, None, raw)

    def sell_quantity(self, symbol: str, quantity: float) -> OrderResult:
        self._ensure_login()
        qty = round(quantity, 6)
        raw = rh.order_sell_fractional_by_quantity(symbol, qty, timeInForce="gfd")
        return self._result(symbol, "sell", 0.0, qty, raw)

    @staticmethod
    def _result(symbol, side, dollars, quantity, raw) -> OrderResult:
        raw = raw if isinstance(raw, dict) else {"response": raw}
        order_id = raw.get("id")
        status = raw.get("state") or ("rejected" if not order_id else "unknown")
        if not order_id:
            log.error("Robinhood rejected %s %s: %s", side, symbol, raw)
        return OrderResult(symbol, side, dollars, quantity, order_id, status, raw)
