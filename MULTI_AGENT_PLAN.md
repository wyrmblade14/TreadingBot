# Multi-Agent System Plan (Claude API)

## Context
The current system is a monolithic sequential loop in `scheduler/job_runner.py`. The user wants to introduce Claude API agents to replace hardcoded rule-based decisions with LLM reasoning — smarter, explainable decisions on signals, regime, and risk.

## Approach: Python Pre-filter + Claude Judgment Layer

Keep all existing Python code as the fast mechanical scanner (free, runs every minute as today).  
Add Claude agents only at decision points — when there's an actual signal to evaluate.

**Cost target:** ~$0.20-0.50/day using claude-haiku-4-5.

---

## Proposed Agents

| Agent | Replaces | When Called | Model |
|---|---|---|---|
| **MarketContextAgent** | `config/adaptive.py` + `analysis/regime_detector.py` | Every 10 min | Haiku |
| **SignalAgent** | hardcoded signal filtering logic in `signal_check()` | When Python strategy fires a signal | Haiku |
| **RiskAgent** | `RiskManager.evaluate()` reasoning layer | When SignalAgent approves | Haiku |
| **ExitMonitorAgent** | V-reversal judgment in exit logic | When open position shows warning signs | Haiku |

**MarketContextAgent** — replaces the 5-signal adaptive.refresh() with a Claude call that receives VIX, ADX, ATR, consecutive losses, time, and fundamental health, then outputs: `mode (NORMAL/DEFENSIVE/HALTED)`, `active_strategies[]`, `reasoning`.

**SignalAgent** — receives: market context, symbol data (OHLCV), strategy signal from Python, fundamental score. Outputs: `approve (bool)`, `confidence (1-5)`, `reasoning`. Does NOT replace strategy.generate_signal() — that still runs in Python first.

**RiskAgent** — receives: SignalAgent output, portfolio state (open positions, capital, daily P&L, consecutive losses). Outputs: `approve (bool)`, `position_size`, `sl_pct`, `reasoning`. Hard limits (max 3 positions, daily halt) enforced AFTER as a Python sanity check — LLM cannot override them.

**ExitMonitorAgent** — only triggered when existing Python exit logic is uncertain (e.g., V-reversal threshold borderline). Optional phase 2.

---

## Implementation Plan

### Phase 1: Agent Infrastructure
- Create `agents/base_agent.py` — wrapper around Anthropic SDK with retry, logging, token tracking
- Create `agents/tools.py` — existing functions exposed as Claude tool definitions:
  - `get_market_data(symbol)` → calls existing data pipeline
  - `get_regime()` → calls `regime_detector.get_current_regime()`
  - `get_vix()` → existing VIX fetch
  - `get_fundamental_score(symbol)` → existing filter
  - `get_portfolio_state()` → from `_risk_mgr.state`

### Phase 2: MarketContextAgent
- File: `agents/market_context_agent.py`
- Replaces: `config/adaptive.py::refresh()` call in `job_runner.signal_check()`
- Output stored in module-level `_market_context` dict, TTL-cached 10 min
- Still mutates `cfg.STRATEGY_CONFIGS` based on LLM output (same interface as today)

### Phase 3: SignalAgent
- File: `agents/signal_agent.py`
- Called in `signal_check()` after `strategy.generate_signal()` returns a non-None signal
- Replaces the current `_pipeline.run()` filter chain for the *judgment* part
- SignalPipeline hard filters (dedup, short-selling, earnings blackout) still run in Python first

### Phase 4: RiskAgent
- File: `agents/risk_agent.py`
- Called after SignalAgent approves, before `OrderManager.execute_signal()`
- Python sanity check runs after to enforce hard limits regardless of LLM output

### Phase 5: Logging + Dashboard
- Log all LLM `reasoning` fields to `logs/agent_decisions.jsonl`
- Add "Agent Reasoning" tab to Streamlit dashboard showing latest decisions
- Track daily token usage and cost in `logs/agent_costs.json`

---

## Critical Files to Modify

- `scheduler/job_runner.py` — main integration point, `signal_check()` function
- `config/adaptive.py` — replaced by MarketContextAgent (keep as fallback)
- `config/strategies.py` — `STRATEGY_CONFIGS` still mutated, same interface
- `dashboard/app.py` — add reasoning tab

## New Files to Create

- `agents/__init__.py`
- `agents/base_agent.py`
- `agents/tools.py`
- `agents/market_context_agent.py`
- `agents/signal_agent.py`
- `agents/risk_agent.py`

## Hard Constraints (Never Delegated to LLM)

- Max 3 open positions
- Daily loss halt (> -2% P&L)
- No trades after 2:00 PM IST
- VIX > 30 = halt (VOLATILE regime)
- Earnings blackout window

---

## Verification

1. Run `python -m pytest tests/` — all existing tests pass
2. Run in paper trading mode for 1 week, compare decisions vs current rule-based system
3. Check `logs/agent_decisions.jsonl` for reasoning quality
4. Check `logs/agent_costs.json` — daily cost should stay under $1
5. Compare trade outcomes: win rate, Sharpe should be equal or better
