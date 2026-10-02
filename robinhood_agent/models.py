"""Core data types shared across the agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class Bar:
    begins_at: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: float
    average_cost: float
    price: float

    @property
    def market_value(self) -> float:
        return self.quantity * self.price

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.average_cost <= 0:
            return 0.0
        return (self.price - self.average_cost) / self.average_cost


@dataclass(frozen=True)
class AccountSnapshot:
    cash: float  # buying power available for new orders
    equity: float  # cash + market value of positions
    positions: dict[str, Position] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderResult:
    symbol: str
    side: Literal["buy", "sell"]
    dollars: float
    quantity: float | None
    order_id: str | None
    status: str
    raw: dict | None = None


# ---- Claude's structured output ----


class TradeDecision(BaseModel):
    symbol: str
    action: Literal["buy", "sell", "hold"]
    dollars: float = Field(description="Dollar amount to buy or sell. 0 for hold.")
    confidence: float = Field(description="0.0 to 1.0")
    rationale: str


class AgentDecision(BaseModel):
    market_view: str
    decisions: list[TradeDecision]
