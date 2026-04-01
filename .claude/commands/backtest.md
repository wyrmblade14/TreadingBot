Run a backtest for the TreadingBot. The user may optionally pass arguments like: `RELIANCE ema_crossover 2023-01-01 2024-01-01`

Parse the arguments if provided (symbol, strategy, start_date, end_date). Use sensible defaults if not provided:
- symbol: RELIANCE
- strategy: ema_crossover
- start_date: 2023-01-01
- end_date: 2024-12-31

Steps:
1. Check if `scripts/run_backtest.py` exists. If not, let the user know Phase 4 (Backtesting Engine) has not been built yet and offer to build it.
2. If it exists: activate venv and run `python scripts/run_backtest.py --symbol <symbol> --strategy <strategy> --start <start> --end <end>`
3. Summarise the results: total return %, win rate, max drawdown, Sharpe ratio, number of trades.
4. Explain what the results mean for a beginner — e.g. "A win rate of 52% with 2:1 RR means the strategy is profitable over time."
