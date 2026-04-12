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
