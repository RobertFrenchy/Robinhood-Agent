"""Broker interface. The agent only talks to brokers through this protocol."""

from __future__ import annotations

from typing import Protocol

from ..models import AccountSnapshot, Bar, OrderResult


class Broker(Protocol):
    def account(self) -> AccountSnapshot: ...

    def latest_prices(self, symbols: list[str]) -> dict[str, float]: ...

    def daily_bars(self, symbol: str) -> list[Bar]: ...

    def is_market_open(self) -> bool: ...

    def buy_dollars(self, symbol: str, dollars: float) -> OrderResult: ...

    def sell_quantity(self, symbol: str, quantity: float) -> OrderResult: ...
