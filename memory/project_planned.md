---
name: Planned Phases
description: What remains to be built in TreadingBot — Phases 6 through 8 with details
type: project
---

## Phase 4 — Backtesting Engine ✅ DONE
## Phase 5 — Streamlit Dashboard ✅ DONE

## Phase 6 — Scheduler + Notifications ✅ DONE
Built: scheduler/job_runner.py, scheduler/bot_controller.py, scheduler/watchlist.py,
notifications/telegram_notifier.py, data/nse_holidays.py.

Current bot run flow:
1. Select a fundamentals-ranked daily NIFTY50 watchlist via scheduler/watchlist.py.
2. Run pre-market market breadth, VIX/direction/regime, and catalyst scans.
3. Fetch 5-minute candles from Kite where available, otherwise yfinance fallback.
4. Run strategies, catalyst/fundamental filters, RiskManager, OrderManager, PaperBroker.
5. Square off before close and send Telegram EOD report.

## Phase 6b — Live Kite Broker (Deferred / Next)
Already built: data/kite_auth.py, data/kite_feed.py, data/kite_ticker.py live tick feed.

Remaining:
- broker/kite_broker.py for real Zerodha order execution behind BaseBroker.
- Streamlit daily re-auth helper because Kite access_token expires daily (SEBI rule).
- GTT/OCO protective orders so stops survive crashes in live mode.
- Paper + live parallel comparison mode before any real-money go-live.

## Phase 7 — Paper Trading Period
Operational phase: run paper trading 30+ trading days with the current structured bot.
Go-live criteria: win rate >45%, understand every trade, positive net P&L after costs

## Phase 8 — Go Live
Single change: TRADING_MODE = "live" in config/settings.py
Start capital: ₹10,000–₹20,000 maximum
Run paper + live in parallel for first 2 weeks to compare

**Why:** User needs sufficient confidence and track record before real money.
**How to apply:** Never suggest skipping paper trading or jumping to live early.
