"""Command-line entry point.

    python -m robinhood_agent run            # loop forever, one cycle every CYCLE_MINUTES
    python -m robinhood_agent run --once     # single cycle
    python -m robinhood_agent run --paper    # force paper mode regardless of TRADING_MODE
    python -m robinhood_agent status         # account, positions, today's risk state
    python -m robinhood_agent kill           # halt all trading (creates the kill-switch file)
    python -m robinhood_agent resume         # remove the kill-switch file
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
import time

from .config import Settings, load_settings
from .journal import Journal

log = logging.getLogger("robinhood_agent")


def build_broker(settings: Settings):
    from .broker.paper import PaperBroker
    from .broker.robinhood import RobinhoodBroker

    rh = RobinhoodBroker(settings.rh_username, settings.rh_password, settings.rh_mfa_secret)
    if settings.is_live:
        return rh
    # Paper mode still uses real Robinhood quotes and market hours, but simulates fills.
    return PaperBroker(
        state_file=settings.data_dir / "paper_state.json",
        starting_cash=settings.paper_starting_cash,
        price_source=rh.latest_prices,
        bars_source=rh.daily_bars,
        market_open=rh.is_market_open,
    )


def cmd_run(settings: Settings, once: bool) -> int:
    from .agent import TradingAgent
    from .strategy import ClaudeDecider

    if settings.is_live:
        log.warning(
            "LIVE MODE: real orders will be placed on Robinhood account %s. "
            "Limits: max order $%.0f, max position %.0f%%, max %d orders/day, "
            "daily loss halt %.1f%%. Kill switch: %s",
            settings.rh_username,
            settings.risk.max_order_usd,
            settings.risk.max_position_pct * 100,
            settings.risk.max_orders_per_day,
            settings.risk.max_daily_loss_pct * 100,
            settings.kill_switch_file,
        )
    else:
        log.info("Paper mode: orders are simulated.")

    agent = TradingAgent(
        settings,
        build_broker(settings),
        ClaudeDecider(settings.claude_model, settings.claude_effort),
        Journal(settings.data_dir),
    )
    while True:
        try:
            report = agent.run_cycle()
            if report.market_view:
                log.info("Market view: %s", report.market_view)
        except KeyboardInterrupt:
            return 0
        except Exception:
            log.exception("Cycle crashed; will retry next interval")
        if once:
            return 0
        try:
            time.sleep(settings.cycle_minutes * 60)
        except KeyboardInterrupt:
            return 0


def cmd_status(settings: Settings) -> int:
    broker = build_broker(settings)
    account = broker.account()
    daily = Journal(settings.data_dir).load_daily(account.equity)
    print(f"Mode:    {settings.trading_mode}")
    print(f"Equity:  ${account.equity:,.2f}")
    print(f"Cash:    ${account.cash:,.2f}")
    print(f"Today:   start equity ${daily.start_equity:,.2f}, orders placed {daily.orders_placed}")
    print(f"Kill switch: {'ON' if settings.kill_switch_file.exists() else 'off'}")
    for p in sorted(account.positions.values(), key=lambda p: -p.market_value):
        print(
            f"  {p.symbol:6} qty={p.quantity:.4f} value=${p.market_value:,.2f} "
            f"pnl={p.unrealized_pnl_pct:+.2%}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="robinhood-agent")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run the trading loop")
    run.add_argument("--once", action="store_true", help="run a single cycle and exit")
    run.add_argument("--paper", action="store_true", help="force paper trading")
    sub.add_parser("status", help="show account and risk state")
    sub.add_parser("kill", help="halt all trading")
    sub.add_parser("resume", help="clear the kill switch")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_settings(args.env_file)
    if getattr(args, "paper", False):
        settings = dataclasses.replace(settings, trading_mode="paper")

    if args.command == "run":
        return cmd_run(settings, args.once)
    if args.command == "status":
        return cmd_status(settings)
    if args.command == "kill":
        settings.kill_switch_file.parent.mkdir(parents=True, exist_ok=True)
        settings.kill_switch_file.touch()
        print(f"Kill switch set: {settings.kill_switch_file}")
        return 0
    if args.command == "resume":
        settings.kill_switch_file.unlink(missing_ok=True)
        print("Kill switch cleared.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
