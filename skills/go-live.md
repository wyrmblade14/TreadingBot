# Skill: go-live
**Role:** Go-Live Readiness Checker  
**Trigger:** user asks if they're ready to go live, or types `go-live`

Run the complete Phase 7 → Phase 8 checklist and give a clear GO / NO-GO verdict.
No arguments needed — run the full audit automatically.

## Reference Constraints
- Phase 7: 30+ trading days paper, win rate >45%
- Phase 8: start ₹10k–₹20k, `TRADING_MODE=live`, daily re-auth required
- User is a beginner — never rush toward live trading

## Checklist (mark ✅ PASS or ❌ FAIL for each)

### 1. Paper Trade Volume
```bash
source venv/bin/activate
python - <<'EOF'
import sqlite3, pandas as pd
conn = sqlite3.connect("logs/trades.db")
df = pd.read_sql("SELECT * FROM trades WHERE status='CLOSED'", conn)
days = df["exit_time"].apply(lambda x: x[:10]).nunique() if len(df) else 0
print(f"Closed trades: {len(df)}, Trading days: {days}")
conn.close()
EOF
```
PASS if: ≥30 trading days AND ≥50 closed trades

### 2. Win Rate & Profitability
```bash
python - <<'EOF'
import sqlite3, pandas as pd
conn = sqlite3.connect("logs/trades.db")
df = pd.read_sql("SELECT pnl FROM trades WHERE status='CLOSED'", conn)
if len(df):
    wins = (df["pnl"] > 0).mean()
    total = df["pnl"].sum()
    pf = df[df.pnl>0]["pnl"].sum() / abs(df[df.pnl<0]["pnl"].sum()) if (df.pnl<0).any() else 999
    print(f"Win rate: {wins:.1%}, Total PnL: ₹{total:.0f}, Profit factor: {pf:.2f}")
conn.close()
EOF
```
PASS if: win rate ≥ 45% AND profit factor ≥ 1.3 AND total PnL > 0

### 3. Max Drawdown
Run `strategy-perf` and check drawdown.
PASS if: max drawdown < 15% of virtual capital

### 4. Infrastructure
- `KITE_API_KEY` and `KITE_API_SECRET` in `.env` (not placeholders)
- `TRADING_MODE=paper` still set (confirm user wants to switch)
- `LIVE_CAPITAL` ≤ ₹20,000

### 5. Kite Auth
```bash
python scripts/kite_login.py --check 2>/dev/null || echo "Auth not configured"
```
PASS if: access_token present and profile call succeeds

### 6. GTT Orders
Check `broker/kite_broker.py` for `place_gtt()` call after entry.
PASS if implemented. FAIL → run `gtt-orders` skill first.

### 7. Notifications
Check `.env` for non-empty `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

### 8. Strategy Health
Run `strategy-perf` — all strategies must be HEALTHY or WATCH (not DEGRADED).

---

## Verdict

**All 8 pass → GO LIVE:**
- Set `.env`: `TRADING_MODE=live`, `LIVE_CAPITAL=10000`
- Run daily re-auth before 9:00 AM every morning
- Monitor first 5 live days before increasing capital

**Any fail → NOT READY:**
- List every failing check with specific fix
- "Complete these items, then run `go-live` again"

**Always remind the beginner:** "Paper trading for 30 days is not optional — it's the difference between learning cheaply and losing real savings. Every professional trader papers first."
