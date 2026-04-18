# Skill: watchlist
**Role:** Watchlist & Universe Manager  
**Trigger:** user asks about the trading universe, why a stock is missing, or types `watchlist [SYMBOL]`

Manage the fundamentals-ranked daily trading universe, debug selection issues, explain inclusions/exclusions.

## Files You Own
- `scheduler/watchlist.py` — DailyWatchlist class
- `analysis/fundamental_selector.py` — ranks NIFTY50 by fundamental score
- `analysis/fundamental_analyst.py` — FundamentalAnalyst (AI synthesis)
- `analysis/fundamental_filter.py` — FundamentalsFilter in signal pipeline
- `data/fundamentals.py` — data fetch layer
- `config/settings.py` — MAX_WATCHLIST_SIZE, sector concentration cap

## Steps

### Show current watchlist
```bash
source venv/bin/activate
python - <<'EOF'
from scheduler.watchlist import DailyWatchlist
wl = DailyWatchlist()
symbols = wl.get_today_symbols()
print(f"Today's universe ({len(symbols)} symbols):", symbols)
for sym in symbols:
    j = wl.get_fundamental_judgment(sym)
    print(f"  {sym}: score={j.score:.2f}, tier={j.tier}, position_scale={j.position_scale:.2f}")
EOF
```

### Refresh watchlist
```bash
python - <<'EOF'
from scheduler.watchlist import DailyWatchlist
wl = DailyWatchlist()
wl.refresh()
print("Refreshed:", wl.get_today_symbols())
EOF
```

### Debug why a symbol is excluded
1. Confirm it's in the NIFTY50 static list (`scheduler/watchlist.py`)
2. Check its fundamental score:
```bash
python - <<'EOF'
from analysis.fundamental_selector import score_fundamentals
from data.fundamentals import get_fundamentals
data = get_fundamentals("SYMBOL.NS")  # replace SYMBOL
score = score_fundamentals(data)
print(f"Score: {score}")
EOF
```
3. Check earnings blackout:
```bash
python - <<'EOF'
from data.fundamentals import is_earnings_blackout
print(is_earnings_blackout("SYMBOL"))
EOF
```
4. Check sector cap — if 3+ stocks from the same sector rank higher, this stock is cut.

### Scoring system (explain to beginner)
- **P/E ratio** vs sector peers (lower = better value)
- **Debt-to-equity** (lower = safer)
- **Net profit margin** (higher = more profitable)
- **Earnings growth** QoQ/YoY
- **Dividend yield** (bonus)

Score 0.0–1.0:
- ≥ 0.6 → `position_scale=1.0` (full size)
- 0.4–0.6 → `position_scale=0.75` (reduced)
- < 0.4 → excluded (unless static fallback)

### Static fallback
If fundamentals data is unavailable (API down), system falls back to the hardcoded NIFTY50 order. This is intentional — the bot never stops trading due to stale fundamentals.

## Weekly Approved Symbols (Phase 3.5)

Once per week (Saturday 10 AM), run the **Weekly Saturday Review** to backtest + optimize all 6 strategies on top fundamentals, then lock in the best performers for the next week's trading.

### Generate approved symbols
```bash
make weekly-review [TOP=25] [OPTIMIZE=1]
# Creates config/approved_symbols.json:
# {
#   "week_of": "2026-04-18",
#   "symbols": [
#     {"symbol": "RELIANCE", "strategy": "ema_crossover", "sharpe": 1.43, "win_rate": 52.3},
#     ...
#   ]
# }
```

### Prioritize in daily watchlist
Modify `scheduler/watchlist.py`:
1. In `DailyWatchlist.__init__()`, add:
```python
self.approved = self._load_approved_symbols()  # from config/approved_symbols.json
```

2. In `select_daily_watchlist()`, sort priority:
```python
# Tier 1: approved symbols from this week
approved_syms = [s["symbol"] for s in self.approved["symbols"]] if self.approved else []
tier1 = [s for s in ranked_by_fundamentals if s in approved_syms]

# Tier 2: all fundamentals-ranked symbols (rest of NIFTY50)
tier2 = [s for s in ranked_by_fundamentals if s not in approved_syms]

# Combine and take top N
watchlist = (tier1 + tier2)[:self.size]
```

3. When executing a signal on an approved symbol, use the pre-optimized strategy from approved_symbols.json if available:
```python
def get_strategy_for_symbol(self, symbol: str) -> str | None:
    if self.approved:
        for entry in self.approved["symbols"]:
            if entry["symbol"] == symbol:
                return entry["strategy"]
    return None  # fallback to default or assignment from param_history.json
```

### What this does
- **Weekly review** backtests all 6 strategies on top-25 fundamental stocks
- **Optimization** runs 50 Optuna trials per strategy to find best parameter tuning
- **Lock in winners** → saves to `config/approved_symbols.json` (valid for 7 days)
- **Next week**: bot only trades approved symbols + their vetted strategies
- **Result**: higher win rate, fewer surprises, automated strategy selection per symbol
