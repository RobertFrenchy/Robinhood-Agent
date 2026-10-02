# Robinhood Agent

An autonomous trading agent for Robinhood stocks and ETFs. Each cycle, Claude reviews the
account and recent price data for a watchlist and proposes trades. Hard-coded risk rules then
approve, shrink, or reject each proposal before any order goes out.

> **Warning:** This agent places **real orders with real money** when `TRADING_MODE=live`.
> Robinhood has no official stock-trading API. This project uses the unofficial
> [`robin_stocks`](https://github.com/jmfernandes/robin_stocks) library, which calls the same
> private endpoints as the Robinhood app. It can break without notice, and Robinhood does not
> sanction it. Nothing here is financial advice. Run it in paper mode first.

## How it works

```
 ┌──────────────┐   account, quotes,   ┌──────────────┐  JSON decisions  ┌──────────────┐  approved  ┌───────────┐
 │  Robinhood   │ ──daily bars──────▶  │    Claude    │ ───────────────▶ │ Risk manager │ ─────────▶ │  Orders   │
 │ (robin_stocks)│   + indicators       │ (structured  │                  │ (hard rules) │            │ + journal │
 └──────────────┘                       │   output)    │                  └──────────────┘            └───────────┘
                                        └──────────────┘
```

1. **Observe.** The agent loads buying power, equity, and positions, plus about 3 months of
   daily bars for every watchlist and held symbol. It reduces the bars to compact features:
   SMA 10/20/50, RSI-14, 1/5/20-day returns, and 20-day volatility.
2. **Decide.** Claude (`claude-opus-5-5` by default) returns schema-validated JSON with one
   `buy` / `sell` / `hold` decision per symbol, each with a dollar size, a confidence score,
   and a rationale. If Claude declines, truncates, or errors, the agent holds for that cycle.
3. **Enforce.** `robinhood_agent/risk.py` applies limits in code. Claude cannot override them:
   - kill-switch file → no orders at all
   - max orders per day
   - daily loss limit → buys stop for the day (sells to reduce risk are still allowed)
   - minimum confidence
   - buys only on watchlist symbols
   - every buy is capped at the smallest of: the max order size, the max position size as a
     percent of equity, and the cash left above your reserve
   - no shorting or margin; sells can't exceed what you hold
   - one order per symbol per cycle
   - no trading outside regular market hours
4. **Execute and record.** The agent places fractional dollar-based buys and quantity-based
   sells (good-for-day). Every snapshot, decision, approval, rejection, and order result is
   appended to `data/journal.jsonl`.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then fill in credentials and limits
```

- **Robinhood credentials:** `RH_USERNAME` and `RH_PASSWORD`. For unattended logins, enable
  authenticator-app 2FA in Robinhood and put the base32 setup secret in `RH_MFA_SECRET`. The
  agent generates TOTP codes from it with `pyotp`. Sessions are cached by `robin_stocks` in
  `~/.tokens/`.
- **Anthropic:** set `ANTHROPIC_API_KEY`.
- **Risk limits:** review every value in `.env` before going live. The defaults are
  deliberately small: $200 max order, 20% max position, 6 orders/day, 3% daily loss halt.

## Usage

```bash
python -m robinhood_agent run --paper --once   # one simulated cycle (real quotes, fake fills)
python -m robinhood_agent run --once           # one cycle in TRADING_MODE (live by default in .env.example)
python -m robinhood_agent run                  # loop every CYCLE_MINUTES during market hours
python -m robinhood_agent status               # equity, cash, positions, today's risk state
python -m robinhood_agent kill                 # emergency stop: no further orders
python -m robinhood_agent resume               # clear the kill switch
```

Paper mode keeps its simulated portfolio in `data/paper_state.json`. It still needs Robinhood
credentials, because it uses Robinhood quotes and market hours.

## Project layout

| Path | Purpose |
|---|---|
| `robinhood_agent/agent.py` | One cycle: observe → decide → enforce → execute → journal |
| `robinhood_agent/strategy.py` | Claude prompt, JSON schema, refusal handling |
| `robinhood_agent/risk.py` | Deterministic risk rules |
| `robinhood_agent/broker/robinhood.py` | Live broker built on `robin_stocks` |
| `robinhood_agent/broker/paper.py` | Simulated broker with persisted state |
| `robinhood_agent/indicators.py` | Dependency-free technical indicators |
| `robinhood_agent/journal.py` | JSONL audit log and per-day risk state |
| `tests/` | Unit tests (no network or credentials needed) |

## Running tests

```bash
pytest
```

## Ideas for next steps

- Add a backtest harness that replays historical bars through the same `Decider` and risk path.
- Feed in news or earnings data. Treat it as untrusted input in the prompt.
- Send notifications (email or push) when orders fill or the daily loss halt triggers.
- Run it on a scheduler, such as cron or a small VM, instead of a long-lived loop.
