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

### Walk-forward backtest (anti-overfitting — preferred)
```bash
python scripts/run_walk_forward.py \
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

## Known limitations
- BB mean reversion shows poor intraday results (EOD square-off cuts trades before mean-reversion target) — needs swing mode
- Backtest uses 0.2% slippage per side and realistic Zerodha costs (₹20/order + STT)
- VIX/regime filters not applied in backtest by default (would need historical VIX data — idea #52)
