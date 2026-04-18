# Skill: backtest
**Role:** Backtesting Expert  
**Trigger:** user wants to run a backtest or walk-forward test, or types `backtest [SYMBOL] [STRATEGY] [START] [END]`

Run backtests and walk-forward tests, interpret results, and explain them clearly to a beginner.

## Arguments (use defaults if not provided)
- symbol: `RELIANCE`
- strategy: `ema_crossover`
- start_date: `2023-01-01`
- end_date: `2024-12-31`

## Steps

### Standard backtest
```bash
source venv/bin/activate
python scripts/run_backtest.py \
  --symbol <symbol> \
  --strategy <strategy> \
  --start <start_date> \
  --end <end_date>
```

### Backtest + Bayesian Parameter Optimization
Use `--optimize` to run 50 Optuna trials before the backtest and apply improved params automatically:

```bash
python scripts/run_backtest.py \
  --symbol <symbol> \
  --strategy <strategy> \
  --start <start_date> \
  --end <end_date> \
  --optimize
```

Runs 50 Bayesian trials on last 30 days of data. If Sharpe improves >10%, saves to `config/param_history.json` and re-runs backtest with optimized params.

For all symbols at once (weekend workflow):
```bash
make weekly-review OPTIMIZE=1    # top 25 fundamentals + optimize + lock approved_symbols.json
```

### Walk-forward backtest (anti-overfitting — preferred)
```bash
python scripts/run_backtest.py \
  --walk-forward \
  --symbol <symbol> \
  --strategy <strategy> \
  --start <start_date> \
  --end <end_date>
```
Walk-forward splits data into rolling train/test windows. More reliable than a single-period backtest.

### Available strategies
- `ema_crossover` — EMA9/EMA21 momentum
- `opening_range_breakout` — ORB 9:15–9:45
- `rsi_macd_combo` — RSI + MACD confluence
- `bb_mean_reversion` — Bollinger Band reversion (best in sideways markets)
- `gap_and_go` — morning gap >0.5% with volume surge
- `vwap_bounce` — VWAP cross confirmation entry

## Interpreting results for a beginner

Explain each metric in plain English:
- **Win rate**: "52% win rate means 52 out of 100 trades were profitable"
- **Profit factor**: "1.8 means for every ₹1 lost, you earned ₹1.80 on winners. Above 1.3 is acceptable, above 1.5 is good"
- **Max drawdown**: "15% drawdown means at worst, virtual capital fell ₹15,000 from its peak before recovering"
- **Sharpe ratio**: "Above 1.0 is acceptable, above 1.5 is good. Measures return per unit of risk"
- **Total return %**: Net gain/loss over the test period

## Health thresholds
- Win rate ≥ 45% → acceptable for live trading
- Profit factor ≥ 1.3 → acceptable
- Max drawdown < 15% → acceptable
- Sharpe > 1.0 → acceptable
- If any metric fails → do NOT go live with this strategy

## Backtest interval tiers (automatic)
- ≤55 days → 5m candles (highest detail)
- ≤700 days → 1h candles
- >700 days → daily candles
This is set automatically by `backtesting/engine.py`.

## Bayesian Parameter Optimizer (Phase 3 — Self-Learning)

The optimizer uses **Optuna** (Bayesian optimization) to find better parameters for your strategy:

### How it works
1. **Baseline**: measures current strategy performance on last 30 days of data (establishes Sharpe ratio)
2. **Search**: runs 50 trials, each trying a different parameter combination, scoring by Sharpe ratio
3. **Save**: if best trial beats baseline by >10%, saves params to `config/param_history.json`
4. **Apply**: bot loads optimized params at startup; backtest uses them automatically

### Parameter search spaces (per strategy)
- **ema_crossover**: short/long periods (5–35), volume multiplier (1.0–2.5), supertrend period (7–21), multiplier (1.5–4.5)
- **rsi_macd_combo**: RSI period (4–14), MACD fast/slow (8–32), signal (7–12), VWAP band (0.2–1.5%)
- **opening_range_breakout**: ORB duration (15–45 min), volume/supertrend params
- **bb_mean_reversion**: BB period (10–30), std dev (1.5–3.0), RSI period (4–14)
- **trend_rider**: supertrend params, ADX min (15–35), period (10–20)
- **vwap_bounce**: RSI period (4–14), VWAP tolerance (0.1–0.8%), volume (1.0–2.0×)

### Why Bayesian > Grid Search
- **Grid search** tries every combination (exhaustive but slow: 5×5×5 = 125 trials minimum)
- **Bayesian** uses probability to focus only on promising zones (10–20× faster, fewer trials)

### Example: optimizing RELIANCE EMA Crossover
```bash
python -c "
from learning.param_optimizer import ParamOptimizer
opt = ParamOptimizer()
result = opt.optimize_ema_crossover('RELIANCE', n_trials=50)
# Checks baseline Sharpe on last 30d, runs 50 trials, saves if >10% improvement
"
```

### When to use optimizer
- **After backtest shows good results** (win rate >45%, Sharpe >1.0)
- **Weekly/monthly** — re-optimize as market regime changes
- **Before paper trading** — lock in best params for the current market
- **NOT for overfitting** — only saves if improvement is statistically meaningful (>10%)

## Known limitations
- BB mean reversion shows poor intraday results (EOD square-off cuts trades before mean-reversion target) — needs swing mode
- Backtest uses 0.2% slippage per side and realistic Zerodha costs (₹20/order + STT)
- VIX/regime filters not applied in backtest by default (would need historical VIX data — idea #52)
- Optimizer runs on last 30 days only — doesn't guarantee out-of-sample performance (walk-forward validation still needed)
