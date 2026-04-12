# Skill: kite-live
**Role:** Zerodha Kite Connect Expert  
**Trigger:** user asks about Kite auth, live trading, GTT, ticker feed, or types `kite-live`

Full expertise on Kite Connect auth flow, order API, GTT orders, WebSocket ticker, and live broker switchover.

## Files You Own
- `broker/kite_broker.py`
- `broker/base_broker.py`
- `data/kite_auth.py`
- `data/kite_feed.py`
- `data/kite_ticker.py`
- `scripts/kite_login.py`
- `data/instruments.py`

## Daily Auth Flow (SEBI rule: token expires daily)

1. `source venv/bin/activate && python scripts/kite_login.py`
2. Open URL in browser → login with Zerodha credentials + TOTP
3. Copy `request_token` from redirect URL, paste when prompted
4. Verify:
```bash
python - <<'EOF'
from kiteconnect import KiteConnect
import os; from dotenv import load_dotenv; load_dotenv()
kite = KiteConnect(api_key=os.getenv("KITE_API_KEY"))
kite.set_access_token(os.getenv("KITE_ACCESS_TOKEN"))
print(kite.profile())
EOF
```

## Live Switchover Checklist (Paper → Live)
Before setting `TRADING_MODE=live` in `.env`:
- [ ] 30+ trading days paper results in `logs/trades.db`
- [ ] Paper win rate ≥ 45% (run `strategy-perf`)
- [ ] Max drawdown < 15%
- [ ] `KITE_API_KEY` + `KITE_API_SECRET` in `.env`
- [ ] Daily re-auth tested successfully
- [ ] `LIVE_CAPITAL` set to ₹10,000–₹20,000
- [ ] GTT orders implemented (run `gtt-orders`)
- [ ] Telegram notifications working
- [ ] Run `go-live` for full check

## GTT Orders (stops that survive crashes)
After every entry, place OCO GTT:
```python
kite.place_gtt(
    trigger_type=kite.GTT_TYPE_OCO,
    tradingsymbol="RELIANCE", exchange="NSE",
    trigger_values=[stop_loss_price, target_price],
    last_price=entry_price,
    orders=[
        {"transaction_type": kite.TRANSACTION_TYPE_SELL, "quantity": qty,
         "order_type": kite.ORDER_TYPE_LIMIT, "product": kite.PRODUCT_MIS,
         "price": stop_loss_price},
        {"transaction_type": kite.TRANSACTION_TYPE_SELL, "quantity": qty,
         "order_type": kite.ORDER_TYPE_LIMIT, "product": kite.PRODUCT_MIS,
         "price": target_price},
    ]
)
```
Run `gtt-orders` skill to implement this fully.

## Symbol Mapping Gotchas
- Kite: `"RELIANCE"` | yfinance: `"RELIANCE.NS"`
- Tata Motors post-demerger: Kite=`"TMPV"`, yfinance=`"TMPV.NS"` (not TATAMOTORS)
- Kite REST candle datetimes are pytz-aware → convert to `ZoneInfo("Asia/Kolkata")`

## Diagnostics
```bash
# Test Kite feed
python - <<'EOF'
from data.kite_feed import KiteFeed
feed = KiteFeed()
df = feed.get_ohlcv("RELIANCE", interval="5minute", days=1)
print(df.tail())
EOF

# Check interpreter if imports fail
which python && python --version && pip list | grep kiteconnect
```
If venv Python ≠ expected: `python3.14 -m venv venv && pip install -r requirements.txt`
