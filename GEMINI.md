# TreadingBot - Gemini AI Assistant Context

## Project Overview
TreadingBot is an automated intraday trading bot for Indian equity markets (NSE/NIFTY50). It operates in paper trading mode by default and supports real trading via the Zerodha Kite API.
The core system is built in Python, featuring fundamental analysis, technical indicators (EMA, RSI, MACD, ORB, VWAP), multiple trading strategies, and strict risk management gates.
It includes two user interfaces:
1. A legacy Streamlit dashboard (`dashboard/app.py`).
2. A modern Next.js React dashboard (`web/`) backed by a Python JSON API (`scripts/run_react_dashboard.py`) and PostgreSQL.

## Building and Running

### Local Python Setup
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Running the Bot
- Dry run / preview: `python scripts/run_bot.py --dry-run`
- Paper trading: `python scripts/run_bot.py`
- Backtesting: `python scripts/run_backtest.py --symbol RELIANCE --strategy ema_crossover --start 2024-01-01 --end 2024-12-31`
- **Walk-forward Backtesting:** `python scripts/run_walk_forward.py --symbol RELIANCE --strategy ema_crossover --start 2024-01-01 --end 2024-12-31`
- **Daily Kite Token Refresh:** `make login` (Requires interactive browser login)

### Running the Dashboards
- **Legacy Streamlit:** `streamlit run dashboard/app.py`
- **Full React Stack (Docker):** `docker compose up -d postgres dashboard-api react-dashboard`
- **Local React Dev:** `cd web && npm install && npm run dev:local` (Ensure API and DB are running)

### Docker / Makefile Commands
- Start all services: `make up`
- Stop services: `make down`
- Rebuild and deploy (parallel): `make deploy`
- Build all services (parallel): `make build-all`
- Cleanup caches/temp files: `make clean`
- View bot logs: `make logs`
- Open PostgreSQL shell: `make db`

## Agent Skills

All skills are in `skills/` — read `skills/<name>.md` to execute a skill task.

| Skill | What it does |
|---|---|
| `skills/risk-audit.md` | Audit all 12 risk gates, diagnose blocked trades, show position sizing |
| `skills/signal-debug.md` | Trace why a signal fired or was silenced layer by layer |
| `skills/kite-live.md` | Kite Connect auth flow, GTT orders, live broker switchover |
| `skills/strategy-perf.md` | Analyse paper trade win rates, detect degradation |
| `skills/go-live.md` | Full Phase 7→8 readiness checklist (GO / NO-GO verdict) |
| `skills/watchlist.md` | Manage and debug fundamentals-ranked trading universe |
| `skills/market-data.md` | Fix yfinance/Kite data issues, NSE holidays, symbol mapping |
| `skills/gtt-orders.md` | Implement GTT crash-safe stop+target orders on Kite |
| `skills/add-strategy.md` | Add a new trading strategy end-to-end |
| `skills/backtest.md` | Run standard or walk-forward backtest and interpret results |
| `skills/brainstorm.md` | NSE market expert — brainstorm accuracy improvements |
| `skills/self-learn.md` | Self-learning system — feature store, ML signal classifier, Bayesian param optimizer |

## Development Conventions
- **Risk Management:** All trading signals must pass through the `RiskManager` before execution.
  - **The 12 Rules:** Includes 1% max risk, 3% daily loss halt, and **Market Breadth Filter** (Rule 12: suppresses BUY/SELL if <20% of NIFTY50 stocks are moving in that direction).
- **Testing:** The project has an extensive test suite. Always run tests using `make test` or `python -m pytest tests/ -v` after changes.
- **Holiday Checking:** A robust holiday checking system is implemented in `data/nse_holidays.py`, including support for special weekend trading sessions (like Muhurat trading).
- **Crash Watchdog:** A watchdog service (`scripts/watchdog.py`) is used to automatically restart the bot if it crashes, with full support for NSE holidays.
- **Database:** Trade history and dashboard data use PostgreSQL (via SQLAlchemy) when running the full stack, with SQLite as a local/testing fallback.
- **Logging:** Structured logging is handled via `loguru`.
- **Scheduling:** Intraday jobs are scheduled using `APScheduler` in IST timezone.
