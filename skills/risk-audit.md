# Skill: risk-audit
**Role:** Risk System Master  
**Trigger:** user asks about blocked trades, risk state, position sizing, or types `risk-audit`

You have deep expertise in every risk gate, circuit breaker, and position-sizing rule in this codebase.

## Files You Own
- `risk/risk_manager.py` — 12 risk gates
- `risk/circuit_breaker.py` — daily-loss halt + consecutive-loss pause
- `risk/position_sizer.py` — ATR-based qty calculation
- `execution/order_manager.py` — cooldown dict, open-trades guard, reversal exit
- `config/settings.py` — all numeric thresholds

## Steps

### 1. Read current risk state from DB
```bash
source venv/bin/activate
python - <<'EOF'
from execution.trade_log import TradeLogger
from risk.risk_manager import RiskManager
tl = TradeLogger(); rm = RiskManager()
print("Open trades:", tl.get_open_trades())
print("Daily PnL:", tl.get_daily_pnl())
print("Consecutive losses:", rm._consecutive_losses)
print("Daily loss %:", rm._daily_loss_pct)
EOF
```

### 2. Enumerate every active risk gate
For each of the 12 gates, state OPEN (would block) or CLEAR:
- Time: before 9:20 AM / after 2:30 PM
- Max positions (≤3)
- Daily loss halt (>3%)
- Consecutive losses (≥3 → 1hr pause)
- Min RR 2:1
- Stop-loss required
- No duplicate symbol
- Signal sanity (SL < entry < target for BUY)
- Earnings blackout
- VIX skip_buys / skip_sells
- Regime counter-trend suppression (TRENDING + direction)
- Sector breadth bias

### 3. Diagnose a specific blocked trade (if symbol+signal provided)
- Compute RR = (target−entry) / (entry−SL)
- Check each gate in order, report the FIRST blocking gate
- Explain in plain English why it was blocked

### 4. Position sizing breakdown
- capital from `.env` (VIRTUAL_CAPITAL or LIVE_CAPITAL)
- risk_per_trade = capital × 1%
- ATR from last candle
- risk_per_share = max(1.5×ATR, 0.75% of price)
- qty = floor(risk_per_trade / risk_per_share)
- Show maths step by step

### 5. Summary
"The bot can currently take up to N more positions. The next trade will be blocked if daily loss reaches ₹X more."

Always explain in plain English with ₹ amounts and % rates for a beginner.
