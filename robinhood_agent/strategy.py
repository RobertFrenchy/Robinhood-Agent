"""Claude-based decision layer: turns a market snapshot into structured trade proposals."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Protocol

import anthropic

from .config import RiskLimits
from .models import AccountSnapshot, AgentDecision

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are the decision engine of an automated trading agent that manages a small Robinhood \
brokerage account holding US stocks and ETFs. Each cycle you receive the account state and \
recent daily price features for a fixed watchlist, and you return one decision per watchlist \
symbol (plus any held symbol outside the watchlist).

How to decide:
- Prefer "hold" unless the evidence is clear. Doing nothing is a good outcome; churn costs money \
through spreads and taxes.
- Think in terms of risk-adjusted return over days to weeks, not minutes. Use trend (price vs. \
moving averages), momentum (multi-period returns), mean reversion (RSI extremes), volatility, \
and current position size and unrealized P&L.
- Size buys in dollars. Keep each position modest and diversified; scale in rather than going \
all-in. Size sells in dollars of the position to sell (use the full position value to exit).
- confidence is your calibrated probability (0.0-1.0) that the trade improves the portfolio's \
risk-adjusted outcome over the next few weeks. Be honest; low-confidence ideas should be holds.
- You cannot short and cannot use margin or options.
- Hard risk limits are enforced in code after you respond: oversized orders will be shrunk or \
rejected, so propose what you actually want within the stated limits.
- The data is all you know. Do not invent news or events. If the data is insufficient, hold.

Keep each rationale to one or two sentences citing the specific numbers that drove it.\
"""

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "market_view": {"type": "string"},
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "action": {"type": "string", "enum": ["buy", "sell", "hold"]},
                    "dollars": {"type": "number"},
                    "confidence": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": ["symbol", "action", "dollars", "confidence", "rationale"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["market_view", "decisions"],
    "additionalProperties": False,
}


class Decider(Protocol):
    def decide(self, context: dict) -> AgentDecision: ...


def build_context(
    account: AccountSnapshot,
    features: dict[str, dict],
    recent_closes: dict[str, list[float]],
    limits: RiskLimits,
    orders_left_today: int,
) -> dict:
    return {
        "as_of_utc": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "account": {
            "cash_available": round(account.cash, 2),
            "equity": round(account.equity, 2),
            "positions": [
                {
                    "symbol": p.symbol,
                    "quantity": round(p.quantity, 6),
                    "average_cost": round(p.average_cost, 2),
                    "price": round(p.price, 2),
                    "market_value": round(p.market_value, 2),
                    "unrealized_pnl_pct": round(p.unrealized_pnl_pct, 4),
                    "pct_of_equity": round(p.market_value / account.equity, 4) if account.equity else 0,
                }
                for p in account.positions.values()
            ],
        },
        "risk_limits": {
            "max_order_usd": limits.max_order_usd,
            "max_position_pct_of_equity": limits.max_position_pct,
            "min_cash_reserve_usd": limits.min_cash_usd,
            "min_confidence_to_execute": limits.min_confidence,
            "orders_remaining_today": orders_left_today,
        },
        "watchlist": {
            symbol: {**features[symbol], "last_10_closes": recent_closes.get(symbol, [])}
            for symbol in features
        },
    }


class ClaudeDecider:
    def __init__(self, model: str, effort: str = "high", client: anthropic.Anthropic | None = None):
        self.model = model
        self.effort = effort
        self.client = client or anthropic.Anthropic()

    def decide(self, context: dict) -> AgentDecision:
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": DECISION_SCHEMA},
            },
            messages=[
                {
                    "role": "user",
                    "content": "Current snapshot (JSON):\n"
                    + json.dumps(context, sort_keys=True)
                    + "\n\nReturn your decisions.",
                }
            ],
        )

        if response.stop_reason == "refusal":
            log.warning("Claude declined this cycle (%s); holding.", response.stop_details)
            return AgentDecision(market_view="model declined; holding", decisions=[])
        if response.stop_reason == "max_tokens":
            log.warning("Claude hit max_tokens; holding this cycle.")
            return AgentDecision(market_view="truncated response; holding", decisions=[])

        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            log.warning("Claude returned no text block; holding.")
            return AgentDecision(market_view="empty response; holding", decisions=[])
        return AgentDecision.model_validate_json(text)
