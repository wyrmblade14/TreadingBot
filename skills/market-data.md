# Skill: market-data
**Role:** Market Data Doctor  
**Trigger:** user reports data errors, missing candles, wrong symbols, VIX issues, or types `market-data [SYMBOL]`

Diagnose and fix all data pipeline issues: yfinance failures, Kite feed errors, NSE holidays, VIX problems, symbol mapping bugs.

## Files You Own
- `data/historical.py`
- `data/india_vix.py`
- `data/instruments.py`
- `data/kite_feed.py`
- `data/kite_ticker.py`
- `data/nse_holidays.py`
- `data/news_catalyst.py`

## Diagnostics

### 1. Test yfinance for a symbol
```bash
source venv/bin/activate
python - <<'EOF'
from data.historical import get_ohlcv
df = get_ohlcv("RELIANCE.NS", period="5d", interval="5m")  # change symbol as needed
if df is None or df.empty:
    print("ERROR: No data")
else:
    print(f"OK: {len(df)} candles, last={df.index[-1]}, close={df['close'].iloc[-1]}")
EOF
```
If None: check NSE holiday, yfinance rate limit (wait 30s, retry), symbol format (must be `SYMBOL.NS`).

### 2. Symbol mapping check
```bash
python - <<'EOF'
from data.instruments import KITE_TO_YF, YF_TO_KITE
sym = "TATAMOTORS"  # replace
print(f"Kite→yfinance: {KITE_TO_YF.get(sym, 'NOT FOUND')}")
EOF
```
**Known issue:** Tata Motors post-demerger → Kite=`TMPV`, yfinance=`TMPV.NS`. `TATAMOTORS` no longer exists.

### 3. VIX feed test
```bash
python - <<'EOF'
from data.india_vix import get_vix_signal, fetch_vix
raw = fetch_vix()
signal = get_vix_signal()
print(f"Raw VIX: {raw}")
print(f"skip_buys: {signal.skip_buys} | skip_sells: {signal.skip_sells}")
EOF
```
If None: yfinance rate-limited or `^INDIAVIX` ticker changed. VIX fails open (no suppression) — by design.

### 4. NSE holiday check
```bash
python - <<'EOF'
from data.nse_holidays import is_market_open
from datetime import date
today = date.today()
print(f"Market open today ({today}):", is_market_open(today))
from data.nse_holidays import NSE_HOLIDAYS_2025, NSE_HOLIDAYS_2026
upcoming = [d for d in sorted(NSE_HOLIDAYS_2025 + NSE_HOLIDAYS_2026) if d >= today][:5]
print("Next holidays:", upcoming)
EOF
```
If a holiday is missing, add it to `data/nse_holidays.py`. Calendar covers 2024–2026 — update before year-end.

### 5. Kite candle timezone fix
Kite REST returns pytz-aware datetimes. Convert with:
```python
from zoneinfo import ZoneInfo
df.index = df.index.map(
    lambda x: x.astimezone(ZoneInfo("Asia/Kolkata")).replace(tzinfo=ZoneInfo("Asia/Kolkata"))
)
```
If `ValueError: cannot reindex from duplicate labels` after conversion — DST transition issue.

### 6. yfinance interval/period limits
| Interval | Max period |
|---|---|
| 5m | 60 days |
| 1h | 730 days |
| 1d | Unlimited |
Never request 5m data older than 55 days. Backtest engine handles this automatically.

### 7. Retry logic
`data/historical.py` should retry once after 2s on None (idea #14):
```python
import time
df = ticker.history(...)
if df is None or df.empty:
    time.sleep(2)
    df = ticker.history(...)
```
If not present, add it.

**Explain to beginner:** "yfinance being rate-limited is normal when fetching many stocks at once. Wait 30 seconds and try again — it's not a bug in the bot."
