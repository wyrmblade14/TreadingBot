# Skill: self-learn
**Role:** Self-Learning System Architect  
**Trigger:** user asks how to make the bot self-learning, smarter over time, or types `self-learn`

You are the architect of TreadingBot's feedback loop. You know every layer of the existing stack and how to close the loop from trade outcome → improved parameters.

---

## What "Self-Learning" Means Here

The bot currently does:
```
Signal → Risk Gates → Execute → Log outcome → (nothing learned)
```

Self-learning closes the loop:
```
Signal → Risk Gates → Execute → Log outcome → Analyse → Improve params → Better signals
```

Three levels, in order of complexity:

| Level | Name | What it does | Already exists? |
|---|---|---|---|
| 1 | Rule-based adaptation | VIX/regime/losses → NORMAL/DEFENSIVE/HALTED | ✅ `config/adaptive.py` |
| 2 | Statistical learning | Train signal classifier on past trade features | ❌ Build this first |
| 3 | Parameter optimization | Bayesian search for best strategy thresholds | ✅ `learning/param_optimizer.py` + `scripts/weekly_review.py` |

---

## The Foundation: Feature Store

Before any ML can happen, we need to record **what the market looked like when each signal fired**.

### Create `learning/feature_store.py`

New DB table: `trade_features`

```python
class TradeFeature(Base):
    __tablename__ = "trade_features"

    id            = Column(Integer, primary_key=True)
    trade_id      = Column(Integer, ForeignKey("trades.id"))  # links to TradeRecord
    symbol        = Column(String(20))
    strategy      = Column(String(50))
    timestamp     = Column(DateTime)

    # Indicator snapshot at signal time
    rsi           = Column(Float)      # RSI(6) value at entry candle
    ema_spread    = Column(Float)      # (EMA9 - EMA21) / price — momentum strength
    vwap_dev      = Column(Float)      # (price - VWAP) / VWAP — VWAP deviation
    volume_ratio  = Column(Float)      # volume / 20-bar avg volume
    macd_hist     = Column(Float)      # MACD histogram value
    atr_pct       = Column(Float)      # ATR / price — volatility normalised

    # Market context at signal time
    vix           = Column(Float)      # India VIX
    regime        = Column(String(20)) # TRENDING / RANGING / VOLATILE
    direction     = Column(String(10)) # UP / DOWN / NEUTRAL
    hour          = Column(Integer)    # entry hour (9–14)
    day_of_week   = Column(Integer)    # 0=Mon ... 4=Fri
    nifty_chg     = Column(Float)      # NIFTY50 intraday % change at entry

    # Outcome (filled when trade closes)
    outcome       = Column(Integer)    # 1 = win, 0 = loss (NULL while open)
    pnl           = Column(Float)      # actual P&L (NULL while open)
    hold_minutes  = Column(Integer)    # how long the trade was open
```

### Wire it into OrderManager
In `execution/order_manager.py` → `_execute_signal_locked()` after entry fills:
```python
from learning.feature_store import FeatureStore
FeatureStore().capture(trade_id, symbol, strategy, df, signal, vix, regime, direction)
```

On close in `_close_trade()`:
```python
FeatureStore().label(trade_log_id, outcome=1 if pnl>0 else 0, pnl=pnl, hold_minutes=...)
```

---

## Level 2: Signal Confidence Classifier

### Create `learning/signal_classifier.py`

```python
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
import joblib, pathlib

MODEL_PATH = pathlib.Path("learning/models/signal_classifier.pkl")
SCALER_PATH = pathlib.Path("learning/models/scaler.pkl")
MIN_SAMPLES = 100   # don't train until we have 100 labelled trades

FEATURES = ["rsi", "ema_spread", "vwap_dev", "volume_ratio", 
            "macd_hist", "atr_pct", "vix", "hour", "day_of_week", "nifty_chg"]

class SignalClassifier:
    def fit(self, df):
        """Train on labelled rows from trade_features table."""
        if len(df) < MIN_SAMPLES:
            return False  # not enough data yet
        X = df[FEATURES].fillna(0)
        y = df["outcome"]
        self.scaler_ = StandardScaler().fit(X)
        self.model_  = LogisticRegression(C=0.1, max_iter=500).fit(
            self.scaler_.transform(X), y
        )
        joblib.dump(self.model_, MODEL_PATH)
        joblib.dump(self.scaler_, SCALER_PATH)
        return True

    def predict_proba(self, feature_dict: dict) -> float:
        """Return probability of win (0.0–1.0) for a new signal."""
        if not MODEL_PATH.exists():
            return 0.5  # no model yet — neutral score
        import numpy as np
        X = np.array([[feature_dict.get(f, 0) for f in FEATURES]])
        X_scaled = self.scaler_.transform(X)
        return float(self.model_.predict_proba(X_scaled)[0][1])

    def feature_importance(self) -> dict:
        """Which features matter most — for dashboard display."""
        return dict(zip(FEATURES, abs(self.model_.coef_[0])))
```

### Add ConfidenceFilter to signal pipeline

In `execution/signal_pipeline.py`, add a new filter:

```python
class ConfidenceFilter(SignalFilter):
    """Block low-confidence signals based on ML classifier."""
    name = "confidence"
    THRESHOLD = 0.45   # below this = reject

    def evaluate(self, signal, context) -> FilterResult:
        from learning.signal_classifier import SignalClassifier
        from learning.feature_store import extract_features
        try:
            features = extract_features(context.df, context.symbol)
            score = SignalClassifier().predict_proba(features)
            if score < self.THRESHOLD:
                return FilterResult("REJECT", f"confidence={score:.2f}<{self.THRESHOLD}")
            return FilterResult("PASS", f"confidence={score:.2f}")
        except Exception:
            return FilterResult("PASS", "confidence:error→fail-open")
```

Add `ConfidenceFilter()` to the pipeline list in `signal_pipeline.py` — **after** all rule-based filters, **before** `RiskManager.evaluate()`.

---

## Level 3: Parameter Optimizer ✅ (DONE)

Parameter optimization is **fully implemented** via `learning/param_optimizer.py` — uses Optuna (Bayesian search).

### How to use

**Option 1: Single symbol + strategy**
```bash
python -c "
from learning.param_optimizer import ParamOptimizer
opt = ParamOptimizer()
result = opt.optimize_ema_crossover('RELIANCE', n_trials=50)
# Checks baseline Sharpe on last 30d, runs 50 trials, saves if >10% improvement
"
```

**Option 2: Integrated with backtest**
```bash
# Run backtest + optimizer in one command
python scripts/run_backtest.py --symbol RELIANCE --strategy ema_crossover --optimize
# → runs 50 Optuna trials, re-backtests with improved params if found
```

**Option 3: Weekly review (all 6 strategies on top fundamentals)**
```bash
make weekly-review [TOP=25] [OPTIMIZE=1]
# → gets top N fundamentally-ranked symbols
# → backtests all 6 strategies on each symbol
# → if OPTIMIZE=1, runs Bayesian optimizer on best strategy per symbol
# → saves config/approved_symbols.json with winners for next week's trading
```

### What gets optimized (per strategy)

- **ema_crossover**: short/long EMA periods, volume multiplier, supertrend params
- **rsi_macd_combo**: RSI period, MACD fast/slow/signal, VWAP band %
- **opening_range_breakout**: ORB duration (minutes), volume & supertrend params
- **bb_mean_reversion**: Bollinger Band period, std dev, RSI period
- **trend_rider**: Supertrend, ADX min/period, volume multiplier
- **vwap_bounce**: RSI period, VWAP tolerance %, volume multiplier

### How it works

1. **Baseline**: measures current params on last 30 days of data (establishes baseline Sharpe)
2. **Search**: 50 Optuna trials (Bayesian — focuses on promising zones, 10–20× faster than grid search)
3. **Gate**: only saves if improvement >10% (prevents overfitting)
4. **Apply**: optimized params auto-loaded from `config/param_history.json` on next backtest/paper trade

---

## Retraining Schedule

Wire into `scheduler/job_runner.py`:

```python
# Pre-market (9:00 AM) — safe to change params before trading starts
scheduler.add_job(retrain_classifier, "cron", hour=9, minute=0)
scheduler.add_job(optimize_params, "cron", hour=9, minute=5)

# Post-market (4:00 PM) — analyse today's trades
scheduler.add_job(post_market_learning_report, "cron", hour=16, minute=0)
```

Retrain classifier if trades since last retrain ≥ 20.  
Run optimizer if total labelled trades ≥ 100 AND it's been ≥ 5 trading days.

---

## Safety Guardrails (critical — never skip these)

1. **Minimum data gate**: No ML until 100 closed, labelled trades. Before that, `predict_proba()` returns 0.5.
2. **Market hours lock**: No param changes between 9:15 AM – 3:30 PM IST. Optimizer only runs pre-market.
3. **Param change cap**: New params can't deviate >25% from current values. Prevents runaway drift.
4. **Rollback store**: Keep last 3 param snapshots in `learning/param_history.json`. Revert via `/risk-audit`.
5. **Fail-open**: Any exception in ML code → PASS the signal. ML is enhancement, not gate.
6. **Human approval** (optional): Dashboard shows "Proposed param change: RSI buy_min 35→42". User clicks Apply/Reject.

---

## Implementation Order (do these in sequence)

```
Phase A: Feature Store  ← foundation, must be first
  learning/feature_store.py
  Wire capture() + label() into order_manager.py
  DB migration: add trade_features table

Phase B: Signal Classifier  ← needs 100 trades of data first
  learning/signal_classifier.py
  learning/models/ directory for persisted models
  Add ConfidenceFilter to signal_pipeline.py
  Add: pip install scikit-learn (likely already in requirements.txt)

Phase C: Param Optimizer  ← needs 100+ trades for meaningful signal
  learning/param_optimizer.py
  Wire into job_runner.py pre-market jobs
  Add: pip install optuna

Phase D: Learning Dashboard
  dashboard/views/learning.py
  Charts: learning curve, feature importance, param history, model accuracy
```

---

## What to Run to Check Current State
```bash
source venv/bin/activate
python - <<'EOF'
import sqlite3, pandas as pd
conn = sqlite3.connect("logs/trades.db")
try:
    df = pd.read_sql("SELECT count(*) as n FROM trade_features WHERE outcome IS NOT NULL", conn)
    print(f"Labelled trade features: {df['n'].iloc[0]}")
except:
    print("trade_features table does not exist yet — Phase A not implemented")

df2 = pd.read_sql("SELECT count(*) as n FROM trades WHERE status='CLOSED'", conn)
print(f"Closed trades total: {df2['n'].iloc[0]}")
conn.close()
EOF
```

**Explain to beginner:** "Self-learning means the bot watches its own performance like a coach watching game tape. After every trade, it records what the market looked like when it made the decision. After 100 trades, it can spot patterns like 'RSI above 60 at 10 AM is usually a bad buy signal on Fridays' — and it starts avoiding those automatically."
