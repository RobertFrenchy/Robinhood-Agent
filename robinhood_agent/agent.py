"""One trading cycle: observe -> ask Claude -> enforce risk rules -> execute -> journal."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .broker.base import Broker
from .config import Settings
from .indicators import summarize
from .journal import Journal
from .models import OrderResult
from .risk import ApprovedOrder, Rejection, RiskManager
from .strategy import Decider, build_context

log = logging.getLogger(__name__)


@dataclass
class CycleReport:
    skipped: str | None = None
    market_view: str | None = None
    approved: list[ApprovedOrder] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)
    results: list[OrderResult] = field(default_factory=list)


class TradingAgent:
    def __init__(self, settings: Settings, broker: Broker, decider: Decider, journal: Journal):
        self.settings = settings
        self.broker = broker
        self.decider = decider
        self.journal = journal
        self.risk = RiskManager(settings.risk, settings.watchlist, settings.kill_switch_file)

    def run_cycle(self) -> CycleReport:
        report = CycleReport()
        account = self.broker.account()
        daily = self.journal.load_daily(account.equity)

        if not self.broker.is_market_open():
            report.skipped = "market closed"
        else:
            report.skipped = self.risk.halt_reason(account, daily)
        if report.skipped:
            log.info("Skipping cycle: %s", report.skipped)
            self.journal.log("cycle_skipped", reason=report.skipped, equity=account.equity)
            return report

        symbols = sorted(set(self.settings.watchlist) | set(account.positions))
        features, closes = {}, {}
        for symbol in symbols:
            try:
                bars = self.broker.daily_bars(symbol)
            except Exception:
                log.exception("Failed to load bars for %s", symbol)
                continue
            if not bars:
                continue
            features[symbol] = summarize(bars)
            closes[symbol] = [round(b.close, 2) for b in bars[-10:]]
        prices = self.broker.latest_prices(symbols)
        for symbol, price in prices.items():
            if symbol in features:
                features[symbol]["latest_price"] = round(price, 2)

        context = build_context(
            account,
            features,
            closes,
            self.settings.risk,
            self.settings.risk.max_orders_per_day - daily.orders_placed,
        )
        try:
            decision = self.decider.decide(context)
        except Exception as exc:
            log.exception("Decision step failed; holding this cycle")
            self.journal.log("decision_error", error=repr(exc))
            report.skipped = f"decision error: {exc!r}"
            return report

        report.market_view = decision.market_view
        report.approved, report.rejected = self.risk.review(decision.decisions, account, prices, daily)
        self.journal.log(
            "decision",
            mode=self.settings.trading_mode,
            equity=account.equity,
            cash=account.cash,
            context=context,
            decision=decision,
            approved=report.approved,
            rejected=report.rejected,
        )

        for order in report.approved:
            try:
                if order.side == "buy":
                    result = self.broker.buy_dollars(order.symbol, order.dollars)
                else:
                    result = self.broker.sell_quantity(order.symbol, order.quantity or 0.0)
            except Exception as exc:
                log.exception("Order failed: %s", order)
                self.journal.log("order_error", order=order, error=repr(exc))
                continue
            report.results.append(result)
            if result.order_id:
                daily.orders_placed += 1
                self.journal.save_daily(daily)
            log.info(
                "%s %s $%.2f qty=%s -> %s (%s)",
                order.side.upper(), order.symbol, order.dollars, order.quantity,
                result.status, result.order_id,
            )
            self.journal.log("order", mode=self.settings.trading_mode, order=order, result=result)

        for r in report.rejected:
            log.info("Rejected %s %s: %s", r.action, r.symbol, r.reason)
        return report
