"""Hard risk rules. Every Claude proposal passes through here before it can become an order.

These checks are deterministic code, not prompt instructions, so the model cannot talk its
way past them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .config import RiskLimits
from .models import AccountSnapshot, TradeDecision

MIN_ORDER_USD = 1.0  # Robinhood's fractional-share minimum


@dataclass(frozen=True)
class ApprovedOrder:
    symbol: str
    side: Literal["buy", "sell"]
    dollars: float
    quantity: float | None  # set for sells
    reason: str


@dataclass(frozen=True)
class Rejection:
    symbol: str
    action: str
    reason: str


@dataclass
class DailyState:
    date: str
    start_equity: float
    orders_placed: int = 0


class RiskManager:
    def __init__(self, limits: RiskLimits, watchlist: tuple[str, ...], kill_switch_file: Path):
        self.limits = limits
        self.watchlist = set(watchlist)
        self.kill_switch_file = Path(kill_switch_file)

    def halt_reason(self, account: AccountSnapshot, daily: DailyState) -> str | None:
        """A reason to place no orders at all this cycle, or None."""
        if self.kill_switch_file.exists():
            return f"kill switch present at {self.kill_switch_file}"
        if daily.orders_placed >= self.limits.max_orders_per_day:
            return f"daily order limit reached ({self.limits.max_orders_per_day})"
        return None

    def daily_loss_breached(self, account: AccountSnapshot, daily: DailyState) -> bool:
        if daily.start_equity <= 0:
            return False
        drawdown = (daily.start_equity - account.equity) / daily.start_equity
        return drawdown >= self.limits.max_daily_loss_pct

    def review(
        self,
        decisions: list[TradeDecision],
        account: AccountSnapshot,
        prices: dict[str, float],
        daily: DailyState,
    ) -> tuple[list[ApprovedOrder], list[Rejection]]:
        approved: list[ApprovedOrder] = []
        rejected: list[Rejection] = []

        halt = self.halt_reason(account, daily)
        if halt:
            actionable = [d for d in decisions if d.action != "hold"]
            return [], [Rejection(d.symbol, d.action, halt) for d in actionable]

        buys_blocked = self.daily_loss_breached(account, daily)
        cash = account.cash
        orders_left = self.limits.max_orders_per_day - daily.orders_placed
        seen: set[str] = set()

        # Sells first so freed cash is not double-counted and de-risking takes priority.
        ordered = sorted(decisions, key=lambda d: {"sell": 0, "buy": 1}.get(d.action, 2))

        for d in ordered:
            symbol = d.symbol.upper().strip()
            if d.action == "hold":
                continue

            def reject(reason: str) -> None:
                rejected.append(Rejection(symbol, d.action, reason))

            if orders_left <= 0:
                reject("daily order limit reached")
                continue
            if symbol in seen:
                reject("only one order per symbol per cycle")
                continue
            if not (0.0 <= d.confidence <= 1.0) or d.confidence < self.limits.min_confidence:
                reject(f"confidence {d.confidence:.2f} below minimum {self.limits.min_confidence:.2f}")
                continue
            price = prices.get(symbol)
            if not price or price <= 0:
                reject("no valid price")
                continue
            if d.dollars <= 0:
                reject("non-positive dollar amount")
                continue

            if d.action == "buy":
                if buys_blocked:
                    reject(f"daily loss limit ({self.limits.max_daily_loss_pct:.1%}) breached; buys halted")
                    continue
                if symbol not in self.watchlist:
                    reject("symbol not on watchlist")
                    continue
                held_value = account.positions[symbol].market_value if symbol in account.positions else 0.0
                position_room = self.limits.max_position_pct * account.equity - held_value
                cash_room = cash - self.limits.min_cash_usd
                dollars = min(d.dollars, self.limits.max_order_usd, position_room, cash_room)
                dollars = round(dollars, 2)
                if dollars < MIN_ORDER_USD:
                    reject(
                        "no room: "
                        f"position_room=${position_room:.2f}, cash_room=${cash_room:.2f}"
                    )
                    continue
                note = "" if dollars == round(d.dollars, 2) else f" (resized from ${d.dollars:.2f})"
                approved.append(ApprovedOrder(symbol, "buy", dollars, None, f"approved{note}"))
                cash -= dollars

            elif d.action == "sell":
                pos = account.positions.get(symbol)
                if not pos or pos.quantity <= 0:
                    reject("no position to sell (shorting is not allowed)")
                    continue
                qty = d.dollars / price
                # Selling (nearly) everything: close the position cleanly instead of leaving dust.
                if qty >= pos.quantity * 0.98:
                    qty = pos.quantity
                qty = min(qty, pos.quantity)
                if qty * price < MIN_ORDER_USD and qty < pos.quantity:
                    reject("sell amount below $1 minimum")
                    continue
                approved.append(ApprovedOrder(symbol, "sell", round(qty * price, 2), qty, "approved"))
                cash += qty * price
            else:
                reject(f"unknown action {d.action!r}")
                continue

            seen.add(symbol)
            orders_left -= 1

        return approved, rejected
