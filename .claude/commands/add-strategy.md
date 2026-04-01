Guide the user through adding a new trading strategy to the TreadingBot.

The user may specify a strategy name or describe what it should do. If they haven't, ask them.

Steps:
1. Read `strategies/base_strategy.py` to understand the Signal dataclass and BaseStrategy interface.
2. Read an existing strategy (e.g. `strategies/ema_crossover.py`) as a reference.
3. Create a new file `strategies/<strategy_name>.py` that:
   - Inherits from `BaseStrategy`
   - Has a clear docstring explaining the strategy in plain English (beginner-friendly)
   - Implements `generate_signal(symbol, df) -> Signal`
   - Uses ATR-based stop-loss
   - Ensures target gives at least 2:1 reward:risk
4. Register the strategy in `config/strategies.py` under `STRATEGY_CONFIGS`.
5. Write tests in `tests/test_strategies.py` for the new strategy.
6. Run `pytest tests/test_strategies.py -v` to confirm tests pass.
7. Summarise what the strategy does and when it is likely to work well in Indian markets.
