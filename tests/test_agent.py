import dataclasses

from robinhood_agent.agent import TradingAgent
from robinhood_agent.broker.paper import PaperBroker
from robinhood_agent.config import RiskLimits, Settings
from robinhood_agent.journal import Journal
from robinhood_agent.models import AgentDecision, Bar, TradeDecision

PRICES = {"SPY": 500.0, "QQQ": 400.0}


def bars(symbol):
    return [Bar(str(i), 1, 1, 1, PRICES[symbol] * (1 + i / 1000), 0) for i in range(60)]


class FakeDecider:
    def __init__(self, decisions):
        self.decisions = decisions
        self.contexts = []

    def decide(self, context):
        self.contexts.append(context)
        return AgentDecision(market_view="test", decisions=self.decisions)


def make(tmp_path, decisions, market_open=True):
    settings = Settings(
        trading_mode="paper",
        watchlist=("SPY", "QQQ"),
        data_dir=tmp_path,
        kill_switch_file=tmp_path / "KILL",
        risk=RiskLimits(max_order_usd=500, max_position_pct=0.5, min_cash_usd=0),
    )
    broker = PaperBroker(
        tmp_path / "paper.json",
        10_000,
        price_source=lambda syms: {s: PRICES[s] for s in syms if s in PRICES},
        bars_source=bars,
        market_open=lambda: market_open,
    )
    decider = FakeDecider(decisions)
    return TradingAgent(settings, broker, decider, Journal(tmp_path)), broker, decider


def test_cycle_executes_approved_buy(tmp_path):
    agent, broker, decider = make(
        tmp_path,
        [
            TradeDecision(symbol="SPY", action="buy", dollars=1000, confidence=0.9, rationale="x"),
            TradeDecision(symbol="QQQ", action="hold", dollars=0, confidence=0.5, rationale="y"),
        ],
    )
    report = agent.run_cycle()
    assert [r.status for r in report.results] == ["filled"]
    acct = broker.account()
    assert acct.positions["SPY"].market_value == 500  # capped at max_order_usd
    assert acct.cash == 9500
    assert set(decider.contexts[0]["watchlist"]) == {"SPY", "QQQ"}
    assert (tmp_path / "journal.jsonl").read_text().count('"event": "order"') == 1


def test_market_closed_skips_claude(tmp_path):
    agent, _, decider = make(tmp_path, [], market_open=False)
    report = agent.run_cycle()
    assert report.skipped == "market closed"
    assert decider.contexts == []


def test_kill_switch_skips_claude(tmp_path):
    agent, _, decider = make(tmp_path, [])
    (tmp_path / "KILL").touch()
    assert "kill switch" in agent.run_cycle().skipped
    assert decider.contexts == []


def test_decider_error_holds(tmp_path):
    agent, broker, decider = make(tmp_path, [])
    decider.decide = lambda ctx: (_ for _ in ()).throw(RuntimeError("boom"))
    report = agent.run_cycle()
    assert "decision error" in report.skipped
    assert broker.account().cash == 10_000
