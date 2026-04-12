# Skill: signal-debug
**Role:** Signal Pipeline Debugger  
**Trigger:** user asks why a signal fired/didn't fire, or types `signal-debug [SYMBOL] [STRATEGY]`

Trace exactly why a signal fired or was silenced at every layer of the stack.

## Pipeline Layers (check in order)
```
Strategy.generate_signal()
  → AdaptiveStrategyManager (param overrides)
  → MarketDirection (VIX skip_buys/skip_sells + NEUTRAL sit-out)
  → MarketRegime (TRENDING counter-trend suppression)
  → SectorBreadth (breadth bias filter)
  → RiskManager.evaluate() (12 gates)
  → OrderManager cooldown + open-trade dedup
  → Signal fired / blocked
```

## Files You Own
- `execution/signal_pipeline.py`
- `scheduler/job_runner.py` — `signal_check()` loop
- `strategies/<name>.py`
- `analysis/market_direction.py`
- `analysis/regime_detector.py`
- `analysis/market_overview.py`
- `data/india_vix.py`
- `config/adaptive.py`
- `execution/order_manager.py`

## Steps

### 1. Fetch last signal for symbol
```bash
source venv/bin/activate
python - <<'EOF'
from data.historical import get_ohlcv
# Replace with actual strategy import
# from strategies.ema_crossover import EMACrossoverStrategy
# df = get_ohlcv("RELIANCE.NS", period="5d", interval="5m")
# sig = EMACrossoverStrategy().generate_signal("RELIANCE", df)
# print(sig)
EOF
```

### 2. Check VIX + direction layer
```bash
python - <<'EOF'
from data.india_vix import get_vix_signal
from analysis.market_direction import get_market_direction
print("VIX signal:", get_vix_signal())
print("Market direction:", get_market_direction())
EOF
```
- `skip_buys=True` → BUY suppressed
- `skip_sells=True` → SELL suppressed
- Both True → NEUTRAL sit-out, no trades

### 3. Check regime
```bash
python - <<'EOF'
from analysis.regime_detector import get_current_regime
print("Regime:", get_current_regime())
EOF
```
TRENDING + UP → block SELL. TRENDING + DOWN → block BUY.

### 4. Check adaptive mode
```bash
python - <<'EOF'
from config.adaptive import get_adaptive_mode
print("Adaptive mode:", get_adaptive_mode())
EOF
```
DEFENSIVE tightens thresholds. HALTED blocks all signals.

### 5. Walk through indicator values manually
Print last 5 candles: close, EMA9, EMA21, RSI, MACD, VWAP, volume vs avg.
Identify which condition failed (e.g. "RSI=72 > threshold 65 → HOLD returned").

### 6. Report
For each pipeline layer: ✅ PASS or ❌ BLOCK with one-line reason.
Show the first block point. Explain what the trader needs to see for the signal to fire.
