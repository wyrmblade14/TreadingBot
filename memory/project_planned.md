---
name: Planned Phases
description: What remains to be built in TreadingBot — Phases 6 through 8 with details
type: project
---

## Phase 4 — Backtesting Engine ✅ DONE
## Phase 5 — Streamlit Dashboard ✅ DONE

## Phase 6 — Live Kite Integration (NEXT)
Files to build: data/market_feed.py (KiteTicker WebSocket + candle builder),
broker/kite_broker.py (live order execution), scheduler/job_runner.py (APScheduler IST jobs),
scripts/run_bot.py (main entry point)

KiteTicker needs reconnection logic (WebSocket drops regularly)
Daily re-auth required: access_token expires every day (SEBI rule)
Auth flow: visit login URL → extract request_token from redirect → exchange for access_token
APScheduler jobs: pre_market_scan (9:00), start_trading (9:15), process_signals (every 5min),
  stop_new_entries (14:30), square_off_all (15:15), daily_report (15:30)

## Phase 7 — Paper Trading Period
Not code — operational phase: run paper trading 30+ days with live Kite data feed
Go-live criteria: win rate >45%, understand every trade, positive net P&L after costs

## Phase 8 — Go Live
Single change: TRADING_MODE = "live" in config/settings.py
Start capital: ₹10,000–₹20,000 maximum
Run paper + live in parallel for first 2 weeks to compare

**Why:** User needs sufficient confidence and track record before real money.
**How to apply:** Never suggest skipping paper trading or jumping to live early.
