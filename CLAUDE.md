# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Self-Learning Rules
- Read `memory/ideas_and_improvements.md` at session start
- Add ideas to that file while building — not just at the end
- Update idea Status (Idea→In Progress→DONE/DROPPED) as work happens
- Log gaps found during user questions as new ideas

## Project Context
- **User**: Stock market beginner. Always explain concepts. Paper-first, never rush to live.
- **Broker**: Zerodha (Kite Connect). Market: NSE India. Instruments: NIFTY50 cash segment only.
- **Mode**: `TRADING_MODE=paper` in `.env`. Switch to `live` only after 30+ days paper success.
- **Language**: Python 3.14, venv at `venv/` (`source venv/bin/activate`)

## Commands

```bash
# Activate venv (required before all commands)
source venv/bin/activate

# Run all tests
python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/test_risk_manager.py -v

# Run a single test by name
python -m pytest tests/test_strategies.py -v -k "test_ema_crossover"

# Run tests with coverage
python -m pytest tests/ --cov

# Run the dashboard (opens at http://localhost:8501)
streamlit run dashboard/app.py

# Run the bot (paper trading scheduler)
python scripts/run_bot.py --dry-run     # preview schedule
python scripts/run_bot.py               # start

# Run a backtest from CLI
python scripts/run_backtest.py --symbol RELIANCE --strategy ema_crossover --start 2024-01-01 --end 2024-12-31
# --strategy options: ema_crossover | rsi_macd_combo | opening_range_breakout | bb_mean_reversion | vwap_bounce
# --all-strategies: run all strategies sequentially
# --walk-forward: walk-forward validation mode (add --train-months / --test-months)
```

## .env Variables

```
TRADING_MODE=paper          # paper | live
KITE_API_KEY=               # Zerodha API key (needed for live only)
KITE_ACCESS_TOKEN=          # Refreshed daily (SEBI rule)
TELEGRAM_BOT_TOKEN=         # Optional — leave blank to disable alerts
TELEGRAM_CHAT_ID=           # Your Telegram numeric chat ID
```

## Architecture Flow
```
Market data → indicators/ → strategies/ → RiskManager.evaluate()
                                                    ↓ approved
                                         OrderManager.execute_signal()
                                                    ↓
                                     PaperBroker / KiteBroker
                                                    ↓
                                    TradeLogger (logs/trades.db)
                                                    ↓
                                    Portfolio → Dashboard
```

## Build Status
| Phase | Status | Tests | Key files |
|---|---|---|---|
| 1 Foundation | ✅ Done | 20 | config/, data/, indicators/ |
| 2 Strategies + Risk | ✅ Done | 43 | strategies/, risk/ |
| 3 Paper Trading | ✅ Done | 23 | broker/, execution/ |
| 4 Backtesting | ✅ Done | 21 | backtesting/engine.py, performance.py, report.py |
| 5 Dashboard | ✅ Done | — | dashboard/app.py, dashboard/views/, analysis/ |
| BB Mean Reversion | ✅ Done | 11 | strategies/bb_mean_reversion.py |
| 6 Scheduler + Notifications | ✅ Done | — | scheduler/, notifications/ |
| VIX Direction Bias | ✅ Done | — | data/india_vix.py, analysis/market_direction.py |
| Adaptive Strategy Manager | ✅ Done | — | config/adaptive.py |
| VWAP Bounce Strategy | ✅ Done | — | strategies/vwap_bounce.py |
| V-Reversal Early Exit | ✅ Done | 9 | execution/order_manager.py (check_reversal_exit) |
| Notification Dedup | ✅ Done | — | notifications/telegram_notifier.py (_once_today) |
| Fundamental Analysis | ✅ Done | 34 | data/fundamentals.py, analysis/fundamental_filter.py, analysis/fundamental_analyst.py |
| Pre-Market Catalyst Scanner | ✅ Done | 21 | data/news_catalyst.py, analysis/catalyst_scanner.py |
| 6b Live Kite | 🔲 Deferred | — | data/market_feed.py, broker/kite_broker.py |
| 7 Paper Period | 🔲 | — | 30+ trading days, win rate >45% |
| 8 Go Live | 🔲 | — | `TRADING_MODE=live`, start ₹10k–₹20k |

**Total tests: 257 passing, 0 failures**

## Key Constants (config/settings.py)
```
Market: 9:15–15:30 IST | Blackout: <9:20 | No new entries: >14:30 | Square-off: 15:15
Risk: 1%/trade | Daily loss halt: 3% | Max positions: 3 | Min RR: 2:1 | Consec losses halt: 3→1hr
Zerodha costs: ₹20/order + STT 0.025% sell + exchange 0.00325% + GST 18% + SEBI ₹10/cr + stamp 0.003% buy
Slippage: 0.1% | Virtual capital: ₹1,00,000
```

## Risk Rules (risk/risk_manager.py — all 10 hardcoded)
1. qty = floor((capital×1%) / risk_per_share)
2. Stop-loss required on every trade
3. Min 2:1 reward:risk
4. Daily loss >3% → halt
5. 3 consecutive losses → 1hr pause
6. No entries before 9:20 AM
7. No new entries after 2:30 PM
8. Max 3 open positions
9. No duplicate symbol (no averaging down)
10. Signal sanity: SL < entry < target (BUY)

## Symbol Formats
- Kite Connect: `"RELIANCE"` — no suffix
- yfinance: `"RELIANCE.NS"` — .NS for NSE
- Mapping in `data/instruments.py`: `KITE_TO_YF`, `YF_TO_KITE`

## Indicator API (using `ta` library)
```python
ta.trend.EMAIndicator(close, window=N).ema_indicator()
ta.momentum.RSIIndicator(close, window=14).rsi()
ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9).macd()  # / .macd_signal() / .macd_diff()
ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()
```

## Critical Tech Decisions
| Decision | Reason |
|---|---|
| `ta` not `pandas-ta` | pandas-ta needs numba; numba doesn't support Python 3.14 |
| `pd.concat` not `df[col]=` | Avoids pandas CoW FutureWarning in indicator compute() |
| `BaseBroker` interface | Paper↔live swap = one config line, zero other changes |
| ATR-based stop-loss | Sits outside normal noise; fallback = 0.5% of price |
| ORB target = max(projected, entry+2×ATR) | Fixes edge case when price already exceeds projection |
| EMA target = 3.0×ATR (not 2.5×ATR) | 3.0/1.5 = 2.0:1 RR exactly — 2.5/1.5 = 1.67 failed minimum |
| Backtest intraday: global_idx not day-slice | Strategies need 26+ candles; day-only slice = 0 trades |
| Backtest tiered intervals: 5m/1h/1d | yfinance limits: 5m=60d, 1h=730d, 1d=unlimited |
| `BackgroundScheduler` for dashboard | `BlockingScheduler` freezes Streamlit thread |
| `dashboard/views/` not `dashboard/pages/` | Streamlit auto-detects `pages/` folder and duplicates nav |
| VWAP `_is_daily`: compare index to normalize() | floor("D") == normalize() always; must compare original to floor |
| `TradeLogger` at module level in views | Streamlit reruns render() on every click — avoids repeated DB init |
| `check_reversal_exit()` before `check_exits()` | Reversal fires first so price cross-back exits before SL is reached |
| `_once_today(key)` in TelegramNotifier | Pre-market briefing + bot-started must not repeat on mid-session restart |
| `restore_position()` in broker tests | `_positions` stores Position objects; injecting plain dicts breaks `update_ltp()` |

## Test Mock Pattern (RiskManager time gates)
```python
with patch("risk.risk_manager.datetime") as mock_dt:
    mock_dt.now.return_value = datetime.fromisoformat("2024-01-02 09:25:00+05:30")
```

## Phase 4 — Backtesting (DONE)
- `backtesting/engine.py`: tiered intervals (5m≤55d, 1h≤700d, 1d>700d), global_idx no-lookahead
- `backtesting/performance.py`: Sharpe, max drawdown, win rate, profit factor
- `backtesting/report.py`: Plotly HTML equity curve + drawdown shading + trade markers
- `scripts/run_backtest.py`: CLI `--symbol`, `--strategy`, `--start`, `--end`

## Phase 5 — Dashboard (DONE)
- Streamlit at `localhost:8501` — run `streamlit run dashboard/app.py`
- Pages: Home, Signals, Backtest, Analysis, Bot Control, Settings
- Views in `dashboard/views/` (NOT `pages/` — Streamlit auto-detects that folder)

## Phase 6 — Scheduler + Notifications (DONE, live Kite deferred)
- `scheduler/job_runner.py`: APScheduler IST jobs (9:00 pre-market → 15:30 report)
- `scheduler/bot_controller.py`: BackgroundScheduler singleton, start/stop/event-log for UI
- `notifications/telegram_notifier.py`: trade alerts + daily report to Telegram
- `data/nse_holidays.py`: NSE holiday calendar 2024–2026

## Phase 6b — Live Kite (Deferred)
- `data/market_feed.py`: KiteTicker WebSocket + candle builder + reconnection logic
- `broker/kite_broker.py`: live order execution
- Daily re-auth: access_token expires daily (SEBI rule) — needs Streamlit helper

## Memory Files
- `memory/MEMORY.md` — index
- `memory/project_built.md` — phase details + key facts per phase
- `memory/lessons_learned.md` — gotchas, non-obvious decisions
- `memory/project_planned.md` — phases 4–8 detail
- `memory/ideas_and_improvements.md` — living ideas backlog (read every session)

## Skills (invoke with /skill-name)
`/run-tests` `/backtest` `/dashboard` `/add-strategy` `/trade-log` `/paper-trade` `/ideas`
