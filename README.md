# TreadingBot

Automated intraday trading bot for Indian equity markets (NSE/NIFTY50).
Runs in **paper trading mode** by default — no real money at risk until you're ready.

---

## What it does

- Selects a fundamentals-ranked NIFTY50 watchlist before trading, then scans it every 5 minutes
- Runs multiple strategies (EMA Crossover, RSI+MACD, Opening Range Breakout, VWAP Bounce)
- Filters every signal through a mandatory risk manager before placing any order
- Simulates Zerodha brokerage costs accurately (₹20 + STT + exchange + GST)
- Sends trade alerts to your phone via Telegram
- Backtests any strategy on historical data with a full equity curve

---

## 🤖 For AI Agents (Claude, Gemini, etc.)
This project uses a **Universal AI Agent Protocol** for seamless context handoff.
1.  **Read [AGENT_RULES.md](AGENT_RULES.md)** first for session-tracking and handoff instructions.
2.  **Read [AGENTS.md](AGENTS.md)** for technical architecture, commands, and project context.
3.  **Check [memory/MEMORY.md](memory/MEMORY.md)** for the current session status and handoff note.

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
# Windows (Command Prompt):
# .venv\Scripts\activate
# Windows (PowerShell):
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (optional)

# 3. Run the legacy Streamlit dashboard
streamlit run dashboard/app.py
# Opens at http://localhost:8501

# 4. Or run the bot from terminal
python scripts/run_bot.py --dry-run     # preview schedule
python scripts/run_bot.py               # start paper trading
# Optional: choose how many fundamentals-ranked NIFTY50 stocks to scan
python scripts/run_bot.py --watchlist 10
```

---

## React Dashboard

The Next.js React dashboard is the new UI path. Streamlit remains available as the legacy dashboard at `http://localhost:8501`.

Run the database:

```bash
cp .env.example .env
docker compose up -d postgres
```

Run the Python JSON API from the host:

```bash
source venv/bin/activate
DATABASE_URL=postgresql://treadingbot:changeme_before_production@localhost:5432/treadingbot \
  DASHBOARD_API_HOST=0.0.0.0 \
  DASHBOARD_API_PORT=8000 \
  python scripts/run_react_dashboard.py
```

Run the Next.js dev server:

```bash
cd web
npm install
NEXT_PUBLIC_DASHBOARD_API_URL=http://localhost:8000 npm run dev:local
```

Open `http://localhost:3000`.

Docker Compose can run the full dashboard stack:

```bash
docker compose up -d postgres dashboard-api react-dashboard
```

Services:
- `postgres` stores the trade log and dashboard data.
- `dashboard-api` exposes the Python JSON API on `http://localhost:8000`.
- `react-dashboard` serves the Next.js UI on `http://localhost:3000`.
- `dashboard` is the legacy Streamlit UI on `http://localhost:8501`.

---

## Project Structure

```
TreadingBot/
├── config/
│   ├── settings.py          # All constants: market hours, risk limits, brokerage rates
│   └── strategies.py        # Strategy parameter configs
│
├── data/
│   ├── instruments.py       # NIFTY50 symbol list + Kite↔yfinance mapping
│   ├── historical.py        # fetch_ohlcv() — downloads OHLCV from yfinance
│   ├── fundamentals.py      # Cached yfinance fundamental metrics + earnings dates
│   ├── news_catalyst.py     # NSE announcements + yfinance news fallback
│   ├── kite_auth.py         # Zerodha Kite auth helpers
│   ├── kite_feed.py         # Kite REST OHLCV fetches
│   ├── kite_ticker.py       # Kite WebSocket live tick feed + 5m candle builder
│   └── nse_holidays.py      # NSE holiday calendar 2024–2026
│
├── indicators/
│   ├── ema.py               # EMA 9/21/50 with volume average
│   ├── rsi.py               # RSI(14)
│   ├── macd.py              # MACD(12,26,9)
│   ├── orb.py               # Opening Range (9:15–9:45 AM) high/low
│   └── vwap.py              # VWAP — resets per trading day
│
├── strategies/
│   ├── ema_crossover.py     # EMA 9/21 crossover + trend + volume + VWAP filter
│   ├── rsi_macd_combo.py    # RSI oversold/overbought + MACD crossover
│   ├── opening_range_breakout.py  # ORB breakout + volume + VWAP filter
│   ├── vwap_bounce.py       # VWAP cross confirmation entry
│   ├── gap_and_go.py        # Morning gap strategy
│   └── bb_mean_reversion.py # Mean reversion strategy, better for swing mode
│
├── risk/
│   ├── risk_manager.py      # Mandatory safety gates and position-size scaling
│   └── position_sizer.py    # qty = floor((capital × 1%) / risk_per_share)
│
├── broker/
│   ├── base_broker.py       # Abstract interface — paper and live are interchangeable
│   └── paper_broker.py      # Full cost simulation including all Zerodha charges
│
├── execution/
│   ├── order_manager.py     # Entry → SL/target monitoring → exit lifecycle
│   ├── trade_log.py         # SQLite trade history (logs/trades.db)
│   └── portfolio.py         # Portfolio snapshot for the dashboard
│
├── backtesting/
│   ├── engine.py            # Chronological replay, no lookahead bias
│   ├── performance.py       # Sharpe, max drawdown, win rate, profit factor
│   └── report.py            # Plotly HTML equity curve + trade markers
│
├── scheduler/
│   ├── job_runner.py        # IST-scheduled APScheduler trading-day jobs
│   ├── watchlist.py         # Daily fundamentals-ranked watchlist selection
│   ├── bot_controller.py    # Singleton — start/stop/status for dashboard
│   └── bot_state.py         # Shared process state file for CLI/UI sync
│
├── notifications/
│   └── telegram_notifier.py # Phone alerts for trades, daily report, bot events
│
├── analysis/
│   ├── stock_scanner.py     # Scans all NIFTY50 for active signals
│   ├── market_overview.py   # NIFTY50 breadth, advance/decline, top movers
│   ├── fundamental_filter.py    # Sector-relative 0–5 fundamental scoring
│   ├── fundamental_selector.py  # Fundamentals-ranked trade universe selection
│   ├── fundamental_analyst.py   # AI/rule-based fundamental judgment for sizing
│   ├── catalyst_scanner.py      # Pre-market catalyst summary
│   ├── market_direction.py      # Intraday NIFTY direction
│   └── regime_detector.py       # Trending/ranging/volatile market regime
│
├── dashboard/
│   ├── app.py               # Legacy Streamlit entry point
│   ├── api/                 # JSON API for the React dashboard
│   └── views/
│       ├── home.py          # Portfolio P&L, open positions, today's trades
│       ├── signals.py       # Live signal scanner with charts
│       ├── backtest.py      # Interactive backtest runner + equity curve
│       ├── analysis.py      # Market breadth, sector overview
│       ├── fundamentals.py  # Fundamental scorecard and AI/rule-based analysis
│       ├── journal.py       # Historical trade analytics
│       ├── comparison.py    # Strategy head-to-head comparison
│       ├── replay.py        # Day replay tooling
│       ├── bot_control.py   # Start/stop bot, activity log, next job schedule
│       └── settings.py      # Read-only config view + go-live guide
│
├── web/
│   ├── app/                 # Next.js app-router pages
│   ├── components/          # React UI components
│   ├── lib/                 # API clients and shared frontend helpers
│   └── package.json         # React dashboard scripts and dependencies
│
├── scripts/
│   ├── run_bot.py              # CLI entry point for the scheduler
│   ├── run_backtest.py         # CLI for running backtests (+ --optimize flag)
│   ├── assign_strategies.py    # Weekend review: backtest + optimize top fundamentals, lock approved_symbols.json
│   ├── run_dashboard.py        # Convenience launcher for legacy Streamlit
│   ├── run_react_dashboard.py  # Python JSON API for the React dashboard
│   ├── run_replay.py           # Replay one market day
│   └── schedule_bot.py         # Cron/Task Scheduler installer
│
└── tests/                   # 374 tests, 0 failures
```

---

## Strategies

| Strategy | Signal | Filters |
|---|---|---|
| EMA Crossover | EMA 9 crosses EMA 21 | Above EMA 50 (trend) + volume + VWAP |
| RSI+MACD Combo | MACD crossover when RSI confirms | RSI not overbought/oversold |
| Opening Range Breakout | Close above/below 9:15–9:45 range | Volume spike + VWAP |
| VWAP Bounce | Price crosses VWAP after a pullback | EMA alignment + RSI + volume + time filter |
| Trend Rider | SuperTrend signal with ADX strength gate | ADX > threshold + volume filter |
| BB Mean Reversion | Bollinger Band touch + RSI confirmation | Best in ranging/sideways markets |

All signals pass through the **RiskManager** before any order is placed.

The **weekend review** (`make weekly-review OPTIMIZE=1`) automatically picks the best strategy per symbol each Saturday and locks it in for the week.

---

## Risk Gates

1. Max 1% of capital at risk per trade
2. Stop-loss required on every trade
3. Min 2:1 reward-to-risk ratio
4. Daily loss > 3% → halt all trading
5. 3 consecutive losses → 1-hour pause
6. No entries before 9:20 AM
7. No new entries after 2:30 PM
8. Max 3 open positions at once
9. No duplicate symbols (no averaging down)
10. Signal sanity check: SL < entry < target (BUY)
11. Earnings blackout window blocks new entries
12. India VIX / market-direction safety filters suppress unsafe sides

---

## Backtesting

```bash
# Standard backtest
python scripts/run_backtest.py --symbol RELIANCE --strategy ema_crossover --start 2024-01-01 --end 2024-12-31

# With Bayesian parameter optimization (finds better params before backtesting)
python scripts/run_backtest.py --symbol RELIANCE --strategy ema_crossover --optimize

# Walk-forward (anti-overfitting)
python scripts/run_backtest.py --symbol RELIANCE --strategy ema_crossover --walk-forward
```

Or use the **Backtest** page in the dashboard for an interactive UI with equity curve and drawdown shading.

## Weekend Review

Run every Saturday to lock in the best-performing stocks and strategies for the next week:

```bash
make weekly-review OPTIMIZE=1
# 1. Ranks NIFTY50 by fundamentals, takes top 25
# 2. Backtests all 6 strategies on each symbol (Kite 60-min or yfinance)
# 3. Bayesian optimizer (50 Optuna trials) on best strategy per symbol
# 4. Saves config/approved_symbols.json — bot trades ONLY these symbols next week
```

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

Data intervals selected automatically:
- ≤55 days → 5-minute candles
- ≤700 days → 1-hour candles
- >700 days → daily candles

---

## Telegram Setup (optional)

Get trade alerts on your phone:

1. Open Telegram → search **@BotFather** → `/newbot` → copy your token
2. Start a chat with your bot, then message **@userinfobot** to get your chat ID (it's a number, not a username)
3. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-yourtoken
   TELEGRAM_CHAT_ID=987654321
   ```

Leave blank to disable — the bot works normally without it.

---

## Daily Kite Token Refresh (when using live trading)

Zerodha requires a fresh access token every day (SEBI rule). Run this each morning **before 9:00 AM IST**, on your machine (not inside Docker):

```bash
python scripts/kite_login.py
```

It walks you through three steps:
1. Opens a login URL — paste it into your browser
2. You log in with your Zerodha credentials
3. Paste the redirect URL back into the terminal — the script writes the new token to `.env` automatically

Then start (or restart) Docker so the containers pick up the new token:

```bash
# If Docker isn't running yet:
docker-compose up -d

# If Docker is already running:
docker-compose restart bot
```

> **Note:** If `KITE_API_KEY` is not set, the bot falls back to yfinance for data — but for accurate real-time prices during paper trading you should still set up the Kite token daily.

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
# 374 passed
```

## Deployment
CI/CD automated via GitHub Actions.
