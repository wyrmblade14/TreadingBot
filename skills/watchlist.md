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
