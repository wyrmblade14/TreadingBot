# Skill: add-strategy
**Role:** Strategy Developer  
**Trigger:** user wants to add a new trading strategy, or types `add-strategy [NAME]`

Guide the user through adding a new strategy to TreadingBot end-to-end.

## Steps

1. **Clarify the strategy** — if the user hasn't described it, ask:
   - What is the entry signal? (price action, indicator crossover, breakout, etc.)
   - What is the exit signal? (target, trailing stop, time exit)
   - Is it momentum or mean-reversion?
   - Works intraday (5m candles) or swing (daily)?

2. **Read the interface** — `strategies/base_strategy.py` for `Signal` dataclass and `BaseStrategy` contract.

3. **Read a reference** — `strategies/ema_crossover.py` for momentum, `strategies/bb_mean_reversion.py` for mean reversion.

4. **Create** `strategies/<strategy_name>.py`:
   - Inherits `BaseStrategy`
   - Docstring explaining the strategy in plain English (beginner-friendly)
   - Implements `generate_signal(symbol, df) -> Signal`
   - Uses ATR-based stop-loss: `stop = entry - max(1.5×ATR, 0.75% of price)`
   - Target gives at least 2:1 RR: `target = entry + 2×(entry−stop)`
   - Includes time guard: no signals before 9:20 AM, after 2:30 PM
   - Checks VWAP alignment as filter (above VWAP for BUY, below for SELL)

5. **Register** in `config/strategies.py` under `STRATEGY_CONFIGS` dict.

6. **Write tests** in `tests/test_strategies.py`:
   - Signal fires correctly with valid input
   - Returns HOLD when conditions not met
   - Stop and target satisfy 2:1 RR

7. **Run tests**:
   ```bash
   source venv/bin/activate
   python -m pytest tests/test_strategies.py -v --tb=short
   ```

8. **Quick backtest** to sanity-check:
   ```bash
   python scripts/run_backtest.py --symbol RELIANCE --strategy <name> --start 2024-01-01 --end 2024-12-31
   ```

9. **Summarise** for the user:
   - What the strategy does and when it works well in Indian markets
   - Expected win rate range (based on strategy type)
   - Recommended markets (trending vs sideways)
   - Any known limitations (e.g. BB mean reversion needs swing mode for best results)

## Critical Rules (never violate)
- Every signal MUST have stop_loss set
- Target MUST give ≥ 2:1 reward:risk (enforced by RiskManager too, but build it in)
- Use `ta` library, not `pandas-ta` (pandas-ta needs numba; numba doesn't support Python 3.14)
- Use `pd.concat` not `df[col]=` for new indicator columns (avoids CoW FutureWarning)
- Test with `df.index[-1]` for time checks so backtests work correctly
