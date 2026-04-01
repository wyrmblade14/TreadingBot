# TreadingBot

Automated intraday trading bot for Indian equity markets (NSE/NIFTY50).
Runs in **paper trading mode** by default — no real money at risk until you're ready.

---

## What it does

- Scans all 50 NIFTY50 stocks every 5 minutes during market hours
- Runs 3 strategies (EMA Crossover, RSI+MACD, Opening Range Breakout)
- Filters every signal through a 10-rule risk manager before placing any order
- Simulates Zerodha brokerage costs accurately (₹20 + STT + exchange + GST)
- Sends trade alerts to your phone via Telegram
- Backtests any strategy on historical data with a full equity curve

---

## Quick Start

```bash
# 1. Clone and set up
git clone <repo>
cd TreadingBot
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (optional)

# 3. Run the dashboard
streamlit run dashboard/app.py
# Opens at http://localhost:8501

# 4. Or run the bot from terminal
python scripts/run_bot.py --dry-run     # preview schedule
python scripts/run_bot.py               # start paper trading
```

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
│   └── nse_holidays.py      # NSE holiday calendar 2024–2026
│
├── indicators/
│   ├── ema.py               # EMA 9/21/50 with volume average
│   ├── rsi.py               # RSI(14)
│   ├── macd.py              # MACD(12,26,9)
│   ├── orb.py               # Opening Range (9:15–9:30 AM) high/low
│   └── vwap.py              # VWAP — resets per trading day
│
├── strategies/
│   ├── ema_crossover.py     # EMA 9/21 crossover + trend + volume + VWAP filter
│   ├── rsi_macd_combo.py    # RSI oversold/overbought + MACD crossover
│   └── opening_range_breakout.py  # ORB breakout + volume + VWAP filter
│
├── risk/
│   ├── risk_manager.py      # 10 hardcoded rules — mandatory approval gate
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
│   ├── job_runner.py        # 6 IST-scheduled APScheduler jobs
│   └── bot_controller.py    # Singleton — start/stop/status for dashboard
│
├── notifications/
│   └── telegram_notifier.py # Phone alerts for trades, daily report, bot events
│
├── analysis/
│   ├── stock_scanner.py     # Scans all NIFTY50 for active signals
│   └── market_overview.py   # NIFTY50 breadth, advance/decline, top movers
│
├── dashboard/
│   ├── app.py               # Streamlit entry point
│   └── views/
│       ├── home.py          # Portfolio P&L, open positions, today's trades
│       ├── signals.py       # Live signal scanner with charts
│       ├── backtest.py      # Interactive backtest runner + equity curve
│       ├── analysis.py      # Market breadth, sector overview
│       ├── bot_control.py   # Start/stop bot, activity log, next job schedule
│       └── settings.py      # Read-only config view + go-live guide
│
├── scripts/
│   ├── run_bot.py           # CLI entry point for the scheduler
│   ├── run_backtest.py      # CLI for running backtests
│   └── run_dashboard.py     # Convenience launcher for Streamlit
│
└── tests/                   # 113 tests, 0 failures
```

---

## Strategies

| Strategy | Signal | Filters |
|---|---|---|
| EMA Crossover | EMA 9 crosses EMA 21 | Above EMA 50 (trend) + volume + VWAP |
| RSI+MACD Combo | MACD crossover when RSI confirms | RSI not overbought/oversold |
| Opening Range Breakout | Close above/below 9:15–9:30 range | Volume spike + VWAP |

All signals pass through the **RiskManager** before any order is placed.

---

## Risk Rules (all hardcoded)

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

---

## Backtesting

```bash
python scripts/run_backtest.py --symbol RELIANCE --strategy ema_crossover --start 2024-01-01 --end 2024-12-31
```

Or use the **Backtest** page in the dashboard for an interactive UI with equity curve and drawdown shading.

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
source venv/bin/activate
python -m pytest tests/ -v
# 113 passed
```
