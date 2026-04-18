# Skill: strategy-perf
**Role:** Strategy Performance Analyst  
**Trigger:** user asks about win rates, strategy health, degradation, or types `strategy-perf [STRATEGY]`

Analyse real paper trade data to measure each strategy's health, detect degradation, and recommend changes.

## Files You Own
- `execution/trade_log.py`
- `backtesting/performance.py`
- `backtesting/walk_forward.py`
- `logs/trades.db`

## Steps

### 1. Query trade database
```bash
source venv/bin/activate
python - <<'EOF'
import sqlite3, pandas as pd
conn = sqlite3.connect("logs/trades.db")
df = pd.read_sql("SELECT * FROM trades WHERE status='CLOSED' ORDER BY exit_time DESC", conn)
print(df.groupby("strategy")[["pnl","win"]].agg(
    trades=("pnl","count"),
    win_rate=("win","mean"),
    total_pnl=("pnl","sum"),
    avg_pnl=("pnl","mean")
).round(2))
conn.close()
EOF
```

### 2. Per-strategy breakdown
- Total trades, win rate %, avg P&L per trade
- Profit factor = gross_profit / gross_loss
- Max consecutive losses
- Best and worst single trade
- Compare to backtest baseline

### 3. Degradation check
Rolling last-10-trade win rate per strategy:
- win rate < 35% on last 10 → DEGRADED ⚠️
- win rate < 45% overall → UNDERPERFORMING

### 4. Time-of-day analysis
```bash
python - <<'EOF'
import sqlite3, pandas as pd
conn = sqlite3.connect("logs/trades.db")
df = pd.read_sql("SELECT strategy, entry_time, pnl FROM trades WHERE status='CLOSED'", conn)
df["hour"] = pd.to_datetime(df["entry_time"]).dt.hour
print(df.groupby(["strategy","hour"])["pnl"].agg(["count","mean","sum"]).round(2))
conn.close()
EOF
```

### 5. Walk-forward results
```bash
python scripts/run_walk_forward.py --symbol RELIANCE --strategy ema_crossover
```

### 6. Recommendations
For each degraded strategy, give a specific actionable suggestion:
- "ORB 28% win rate after 11 AM → add `if now > time(11,0): return HOLD`"
- "RSI_MACD wins 52% before 10:30, 31% after 1 PM → add time filter"
- State clearly: "Do NOT go live if overall win rate < 45%"

### 7. Summary table
One row per strategy: trades / win % / avg ₹P&L / status (HEALTHY / WATCH / DEGRADED)

**Explain for beginner:** "Profit factor 1.8 means for every ₹1 lost, you earn ₹1.80 on winners."

## Parameter Optimization Feedback Loop (Phase 3.5)

When a strategy underperforms in paper trading, the **weekly review** automatically backtests + optimizes its parameters:

### Flow
1. **Monitor**: Review strategy performance above (win rate, profit factor, degradation)
2. **Backtest**: Run `make backtest SYMBOL=X STRATEGY=Y` to confirm issue
3. **Optimize**: Add `--optimize` flag: `python scripts/run_backtest.py --symbol X --strategy Y --optimize`
   - Runs 50 Optuna trials on last 30 days
   - Measures baseline Sharpe, searches for better parameters
   - Saves improved params to `config/param_history.json` if Sharpe improves >10%
4. **Re-test**: Backtest with optimized params to verify improvement
5. **Weekly sweep**: `make weekly-review` backtests all 6 strategies on top fundamentals, locks in best performers

### When to re-optimize
- **Weekly**: automatic via `make weekly-review` (Saturday 10 AM scheduled)
- **Ad-hoc**: when strategy win rate drops below 45% on last 10 trades
- **After market regime change**: VIX spike, major index move, earnings season shift

### Example: EMA Crossover degrading
```bash
# 1. Confirm issue
python - <<'EOF'
import sqlite3, pandas as pd
conn = sqlite3.connect("logs/trades.db")
df = pd.read_sql("""
  SELECT strategy, pnl, win FROM trades 
  WHERE strategy='ema_crossover' AND status='CLOSED' 
  ORDER BY exit_time DESC LIMIT 10
""", conn)
wr = (df['win'].sum() / len(df) * 100)
print(f"Last 10 trades: {wr:.0f}% win rate")
conn.close()
EOF

# 2. Backtest to isolate issue
make backtest SYMBOL=RELIANCE STRATEGY=ema_crossover START=2024-10-01 END=2024-12-31

# 3. Optimize parameters
python scripts/run_backtest.py --symbol RELIANCE --strategy ema_crossover --optimize

# 4. Re-backtest with optimized params (they're auto-loaded)
make backtest SYMBOL=RELIANCE STRATEGY=ema_crossover START=2024-10-01 END=2024-12-31
```

### Optimization in weekly review
The `make weekly-review` command does this automatically for all 6 strategies on top fundamentals:
```bash
make weekly-review TOP=25 OPTIMIZE=1
# For each of top-25 symbols:
#   1. Backtest all 6 strategies
#   2. Pick best strategy (highest Sharpe × win_rate score)
#   3. Run Bayesian optimizer on best strategy (30 trials, faster than 50)
#   4. Save to config/approved_symbols.json with locked-in strategy per symbol
```

This ensures **before going live next week**, you've already validated which strategy works best on each symbol.
