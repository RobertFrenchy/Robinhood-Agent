"""Paper broker: simulated fills at the latest price from a market-data source.

State is persisted to JSON so paper positions survive restarts.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Callable

from ..models import AccountSnapshot, Bar, OrderResult, Position


class PaperBroker:
    def __init__(
        self,
        state_file: Path,
        starting_cash: float,
        price_source: Callable[[list[str]], dict[str, float]],
        bars_source: Callable[[str], list[Bar]],
        market_open: Callable[[], bool] = lambda: True,
    ):
        self._state_file = Path(state_file)
        self._price_source = price_source
        self._bars_source = bars_source
        self._market_open = market_open
        if self._state_file.exists():
            self._state = json.loads(self._state_file.read_text())
        else:
            self._state = {"cash": starting_cash, "positions": {}}
            self._save()

    def _save(self) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps(self._state, indent=2))

    def account(self) -> AccountSnapshot:
        held = self._state["positions"]
        prices = self._price_source(list(held)) if held else {}
        positions = {
            s: Position(s, p["quantity"], p["average_cost"], prices.get(s, p["average_cost"]))
            for s, p in held.items()
        }
        cash = self._state["cash"]
        return AccountSnapshot(
            cash=cash,
            equity=cash + sum(p.market_value for p in positions.values()),
            positions=positions,
        )

    def latest_prices(self, symbols: list[str]) -> dict[str, float]:
        return self._price_source(symbols)

    def daily_bars(self, symbol: str) -> list[Bar]:
        return self._bars_source(symbol)

    def is_market_open(self) -> bool:
        return self._market_open()

    def buy_dollars(self, symbol: str, dollars: float) -> OrderResult:
        price = self._price_source([symbol]).get(symbol)
        if not price or dollars <= 0 or dollars > self._state["cash"] + 1e-9:
            return OrderResult(symbol, "buy", dollars, None, None, "rejected")
        qty = dollars / price
        pos = self._state["positions"].get(symbol, {"quantity": 0.0, "average_cost": 0.0})
        new_qty = pos["quantity"] + qty
        pos["average_cost"] = (pos["quantity"] * pos["average_cost"] + dollars) / new_qty
        pos["quantity"] = new_qty
        self._state["positions"][symbol] = pos
        self._state["cash"] -= dollars
        self._save()
        return OrderResult(symbol, "buy", dollars, qty, f"paper-{uuid.uuid4().hex[:12]}", "filled")

    def sell_quantity(self, symbol: str, quantity: float) -> OrderResult:
        price = self._price_source([symbol]).get(symbol)
        pos = self._state["positions"].get(symbol)
        if not price or not pos or quantity <= 0 or quantity > pos["quantity"] + 1e-9:
            return OrderResult(symbol, "sell", 0.0, quantity, None, "rejected")
        quantity = min(quantity, pos["quantity"])
        pos["quantity"] -= quantity
        if pos["quantity"] <= 1e-9:
            del self._state["positions"][symbol]
        self._state["cash"] += quantity * price
        self._save()
        return OrderResult(
            symbol, "sell", quantity * price, quantity, f"paper-{uuid.uuid4().hex[:12]}", "filled"
        )
