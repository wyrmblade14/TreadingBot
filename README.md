# TreadingBot

Automated intraday trading bot for Indian equity markets (NSE/NIFTY50).
Runs in **paper trading mode** by default — no real money at risk until you're ready.

---

## What it does

- Selects a fundamentals-ranked NIFTY50 watchlist before trading, then scans it every 5 minutes
- Runs multiple strategies (EMA Crossover, RSI+MACD, ORB, VWAP Bounce, Trend Rider, BB Mean Reversion)
- Filters every signal through a mandatory risk manager before placing any order
- Detects market regime (Trending / Ranging / Volatile) and suppresses unsuitable strategies automatically
- Simulates Zerodha brokerage costs accurately (₹20 + STT + exchange + GST)
- Sends trade alerts to your phone via Telegram
- Backtests any strategy on historical data with a full equity curve
- **Weekend review**: parallel sweep of all strategies across top 25 NIFTY50 symbols, Bayesian parameter optimization, results saved to SQLite + PostgreSQL + CSV log

---

## 🤖 For AI Agents (Claude, Gemini, etc.)
This project uses a **Universal AI Agent Protocol** for seamless context handoff.
1. **Read [AGENT_RULES.md](AGENT_RULES.md)** first for session-tracking and handoff instructions.
2. **Read [AGENTS.md](AGENTS.md)** for technical architecture, commands, and project context.
3. **Check [memory/MEMORY.md](memory/MEMORY.md)** for the current session status and handoff note.

---

## Quick Start

```bash
# 1. Clone and set up
git clone <repo>
cd TreadingBot
python -m venv .venv

# Activate the virtual environment:
# Mac/Linux:
source .venv/bin/activate
# Windows (Command Prompt):  .venv\Scripts\activate
# Windows (PowerShell):      .venv\Scripts\Activate.ps1

pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (optional)

# 3. Run the React dashboard (recommended)
docker compose up -d postgres
python scripts/run_react_dashboard.py   # API at http://localhost:8000
cd web && npm install && npm run dev:local  # UI at http://localhost:3000

# 4. Or run the bot from terminal
python scripts/run_bot.py --dry-run     # preview schedule
python scripts/run_bot.py               # start paper trading
```

---

## React Dashboard

The Next.js React dashboard is the primary UI. Legacy Streamlit remains available at `http://localhost:8501`.

```bash
# Start all services via Docker Compose
docker compose up -d postgres dashboard-api react-dashboard
```

Or run each piece manually on the host:

```bash
# PostgreSQL (Docker)
docker compose up -d postgres

# Python JSON API
source .venv/bin/activate
DATABASE_URL=postgresql://treadingbot:changeme@localhost:5432/treadingbot \
  DASHBOARD_API_HOST=0.0.0.0 DASHBOARD_API_PORT=8000 \
  python scripts/run_react_dashboard.py

# React dev server
cd web && npm install
NEXT_PUBLIC_DASHBOARD_API_URL=http://localhost:8000 npm run dev:local
# Open http://localhost:3000
```

Services:
| Service | URL | Notes |
|---|---|---|
| `postgres` | — | Trade log + dashboard data |
| `dashboard-api` | `http://localhost:8000` | Python JSON API |
| `react-dashboard` | `http://localhost:3000` | Next.js UI |
| `dashboard` | `http://localhost:8501` | Legacy Streamlit (reference only) |

---

## Project Structure

```
TreadingBot/
├── config/
│   ├── settings.py              # All constants: market hours, risk limits, brokerage rates
│   ├── param_history.json       # Optimized strategy params + weekly assignments (auto-written)
│   └── approved_symbols.json    # Locked trading universe (written by weekend review, 7-day TTL)
│
├── data/
│   ├── instruments.py           # NIFTY50 symbol list + Kite↔yfinance mapping
│   ├── historical.py            # fetch_ohlcv() — yfinance OHLCV download
│   ├── fundamentals.py          # Cached yfinance fundamental metrics + earnings dates
│   ├── news_catalyst.py         # NSE announcements + yfinance news fallback
│   ├── kite_auth.py             # Zerodha Kite auth helpers
│   ├── kite_feed.py             # Kite REST OHLCV fetches (60-min, up to 400 days)
│   ├── kite_ticker.py           # Kite WebSocket live tick feed + 5m candle builder
│   └── nse_holidays.py          # NSE holiday calendar 2024–2026
│
├── indicators/
│   ├── ema.py                   # EMA 9/21/50 with volume average
│   ├── rsi.py                   # RSI(14)
│   ├── macd.py                  # MACD(12,26,9)
│   ├── orb.py                   # Opening Range (9:15–9:45 AM) high/low
│   └── vwap.py                  # VWAP — resets per trading day
│
├── strategies/
│   ├── ema_crossover.py         # EMA 9/21 crossover + trend + volume + VWAP filter
│   ├── rsi_macd_combo.py        # RSI oversold/overbought + MACD crossover
│   ├── opening_range_breakout.py# ORB breakout + volume + VWAP filter
│   ├── vwap_bounce.py           # VWAP cross confirmation entry
│   ├── trend_rider.py           # SuperTrend + ADX strength gate
│   └── bb_mean_reversion.py     # Bollinger Band reversion — best in ranging markets;
│                                #   suppressed automatically when ADX > 25 (trending)
│
├── risk/
│   ├── risk_manager.py          # Mandatory safety gates and position-size scaling
│   └── position_sizer.py        # qty = floor((capital × 1%) / risk_per_share)
│
├── broker/
│   ├── base_broker.py           # Abstract interface — paper and live are interchangeable
│   └── paper_broker.py          # Full cost simulation including all Zerodha charges
│
├── execution/
│   ├── order_manager.py         # Entry → SL/target monitoring → exit lifecycle
│   ├── trade_log.py             # PostgreSQL trade history (SQLAlchemy ORM)
│   ├── optimizer_log.py         # Saves weekend sweep results to SQLite + PostgreSQL + CSV
│   └── portfolio.py             # Portfolio snapshot for the dashboard
│
├── backtesting/
│   ├── engine.py                # Chronological replay, no lookahead bias, thread-safe
│   ├── performance.py           # Sharpe, max drawdown, win rate, profit factor
│   └── report.py                # Plotly HTML equity curve + trade markers
│
├── analysis/
│   ├── regime_detector.py       # Trending/Ranging/Volatile regime (thread-local backtest flag)
│   ├── fundamental_selector.py  # Fundamentals-ranked trade universe selection
│   ├── fundamental_filter.py    # Sector-relative 0–5 fundamental scoring
│   ├── fundamental_analyst.py   # AI/rule-based fundamental judgment for sizing
│   ├── catalyst_scanner.py      # Pre-market catalyst summary
│   ├── stock_scanner.py         # Scans all NIFTY50 for active signals
│   └── market_overview.py       # NIFTY50 breadth, advance/decline, top movers
│
├── scheduler/
│   ├── job_runner.py            # IST-scheduled APScheduler trading-day jobs
│   ├── watchlist.py             # Daily fundamentals-ranked watchlist selection
│   ├── bot_controller.py        # Singleton — start/stop/status for dashboard
│   └── bot_state.py             # Shared process state file for CLI/UI sync
│
├── learning/
│   └── param_optimizer.py       # Bayesian parameter optimizer (Optuna, 50 trials/symbol)
│
├── notifications/
│   └── telegram_notifier.py     # Phone alerts for trades, daily report, bot events
│
├── dashboard/
│   ├── api/                     # JSON API for the React dashboard
│   └── views/                   # Legacy Streamlit pages (reference)
│
├── web/
│   ├── app/                     # Next.js app-router pages
│   ├── components/              # React UI components
│   └── lib/                     # API clients and shared frontend helpers
│
├── scripts/
│   ├── run_bot.py               # CLI entry point for the scheduler
│   ├── run_backtest.py          # CLI for running backtests (+ --optimize flag)
│   ├── assign_strategies.py     # Weekend review: parallel sweep + optimize + lock approved_symbols.json
│   ├── run_react_dashboard.py   # Python JSON API for the React dashboard
│   ├── run_replay.py            # Replay one market day
│   ├── migrate_sqlite_to_postgres.py  # One-shot SQLite → PostgreSQL migration
│   └── schedule_bot.py          # Cron/Task Scheduler installer
│
├── logs/
│   ├── trades.db                # SQLite trade log + optimizer_runs table
│   └── optimizer_YYYY-MM-DD.csv # Per-run CSV log written by each weekend sweep
│
└── tests/                       # 374 tests, 0 failures
```

---

## Strategies

| Strategy | Signal | Best regime |
|---|---|---|
| EMA Crossover | EMA 9 crosses EMA 21 | Trending |
| RSI+MACD Combo | MACD crossover when RSI confirms | Trending / Ranging |
| Opening Range Breakout | Close above/below 9:15–9:45 range | Trending |
| VWAP Bounce | Price crosses VWAP after a pullback | Trending |
| Trend Rider | SuperTrend signal with ADX strength gate | Trending |
| BB Mean Reversion | Bollinger Band touch + RSI confirmation | **Ranging only** — auto-suppressed when ADX > 25 |

All signals pass through the **RiskManager** before any order is placed.

The **weekend review** (`make weekly-review OPTIMIZE=1`) automatically picks the best strategy per symbol each Saturday and locks it in for the week.

### Scoring formula

```
composite_score = max(sharpe, 0) × (win_rate% / 50)
```

A score of `0.000` means the strategy had a negative Sharpe (net losing) on that symbol — the strategy is disqualified regardless of win rate.

---

## Risk Gates

1. Max 1% of capital at risk per trade
2. Stop-loss required on every trade
3. Min 2:1 reward-to-risk ratio
4. Daily loss > 3% → halt all trading
5. 3 consecutive losses → 1-hour pause
6. No entries before 9:20 AM IST
7. No new entries after 2:30 PM IST
8. Max 3 open positions at once
9. No duplicate symbols (no averaging down)
10. Signal sanity check: SL < entry < target (BUY)
11. Earnings blackout window blocks new entries
12. India VIX / market-direction safety filters suppress unsafe sides

---

## Backtesting

```bash
# Standard backtest
make backtest SYMBOL=RELIANCE
make backtest SYMBOL=RELIANCE STRATEGY=ema_crossover START=2024-01-01 END=2024-12-31

# All 6 strategies side-by-side
make backtest-all SYMBOL=RELIANCE

# Walk-forward (anti-overfitting: 6m train / 2m test windows)
make backtest-wf SYMBOL=RELIANCE

# With Bayesian parameter optimization (finds better params before backtesting)
python scripts/run_backtest.py --symbol RELIANCE --strategy ema_crossover --optimize
```

Or use the **Backtest** page in the React dashboard for an interactive UI with equity curve and drawdown shading.

---

## Weekend Review

Run every Saturday to lock in the best-performing stocks and strategies for the coming week.

```bash
# Standard (top 25 symbols, no optimizer)
make weekly-review

# With Bayesian optimizer — recommended
make weekly-review OPTIMIZE=1

# Wider universe
make weekly-review TOP=30 OPTIMIZE=1

# Dry run — prints results but writes nothing to disk
make weekly-review DRY_RUN=1
```

Or call the script directly for more control:

```bash
python scripts/assign_strategies.py --top 25 --optimize --workers 8

# --workers N   parallel threads (default: 8; use 1 to disable parallelism)
# --days N      lookback period in days (default: 380)
# --dry-run     skip all writes
```

### What it does

1. Ranks NIFTY50 by fundamentals, takes the top 25 (or `--top N`)
2. Fetches 60-min OHLCV from Kite Connect (falls back to yfinance)
3. Backtests all 6 strategies on each symbol **in parallel** (8 worker threads by default)
4. Runs Bayesian optimizer (50 Optuna trials) on the best strategy per symbol if `--optimize`
5. Writes results to three places:
   - `config/approved_symbols.json` — locked trading universe (expires after 7 days)
   - `config/param_history.json` — optimized parameters per symbol/strategy
   - `logs/trades.db` (`optimizer_runs` table) — full historical record in SQLite
   - `logs/optimizer_YYYY-MM-DD.csv` — human-readable CSV log of the run
   - PostgreSQL (`optimizer_runs` table) — if `DATABASE_URL` is set in `.env`

This runs automatically at **Saturday 10 AM IST** when the bot is active. The lock expires after 7 days and falls back to live fundamentals ranking.

---

## Scheduling (optional)

Auto-start the bot on weekdays at 09:00 IST:

```bash
python scripts/schedule_bot.py --install   # Mac/Linux: cron | Windows: Task Scheduler
python scripts/schedule_bot.py --status    # verify it's installed
python scripts/schedule_bot.py --remove    # uninstall
```

> **Windows note:** `--install` creates a Windows Task Scheduler entry via `schtasks`. Run from an Administrator prompt if you see access-denied errors.

---

## Telegram Setup (optional)

1. Open Telegram → search **@BotFather** → `/newbot` → copy your token
2. Start a chat with your bot, then message **@userinfobot** to get your numeric chat ID
3. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-yourtoken
   TELEGRAM_CHAT_ID=987654321
   ```

Leave blank to disable — the bot works normally without it.

---

## Daily Kite Token Refresh (live trading only)

Zerodha requires a fresh access token every day (SEBI rule). Run each morning **before 9:00 AM IST**:

```bash
make login          # automated headless login (needs ZERODHA_* vars in .env)
make login-manual   # browser fallback — paste the redirect URL when prompted
```

Then restart Docker so containers pick up the new token:

```bash
make bot            # restarts only the bot + watchdog containers
```

> If `KITE_API_KEY` is not set, the bot falls back to yfinance for data — but for accurate real-time prices during paper trading you should still refresh the Kite token daily.

---

## Make Reference

```bash
# Kite auth
make login              # automated headless login
make login-manual       # browser fallback

# Docker
make up                 # first-time setup + start all containers
make bot                # restart bot + watchdog only
make down               # stop all containers
make logs               # follow bot logs
make build              # rebuild all images
make shell              # bash inside bot container
make db                 # psql shell inside postgres container

# Backtesting
make backtest SYMBOL=RELIANCE
make backtest SYMBOL=RELIANCE STRATEGY=ema_crossover START=2024-01-01 END=2024-12-31
make backtest-all SYMBOL=RELIANCE
make backtest-wf  SYMBOL=RELIANCE
make backtest-symbols                    # list symbols with assigned strategies
make weekly-review                       # sweep top 25, lock approved_symbols.json
make weekly-review TOP=30 OPTIMIZE=1    # wider universe + Bayesian optimization
make weekly-review DRY_RUN=1            # dry run, nothing written to disk

# Dev
make test               # run full pytest suite (374 tests)
make clean              # remove caches and build artefacts
```

---

## Go-Live Checklist

Before switching `TRADING_MODE=live`:

- [ ] 30+ trading days of paper trading
- [ ] Win rate consistently above 45%
- [ ] You understand every trade the bot made
- [ ] Zerodha API key set in `.env`
- [ ] Start with ₹10,000–₹20,000 maximum
- [ ] Run paper + live in parallel for the first 2 weeks

---

## Tests

```bash
source .venv/bin/activate
python -m pytest tests/ -v
# 374 passed, 0 failures
```

---

## Deployment

CI/CD automated via GitHub Actions. Full stack runs in Docker Compose — see `docker-compose.yml` for service definitions.
