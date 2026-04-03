---
name: What Has Been Built
description: Completed phases of the TreadingBot — modules, files, test counts, and key functionality
type: project
---

All code lives at the project root.
Virtual environment: venv/ — on Windows use `venv/Scripts/python.exe` (not venv/bin/).
Total tests: 182 passing, 0 failures (as of April 2026, Python 3.14 on Windows).

## Phase 1 — Foundation ✅
Files: config/settings.py, config/strategies.py, data/instruments.py,
data/historical.py, data/data_store.py, indicators/base.py, indicators/ema.py,
indicators/rsi.py, indicators/macd.py, indicators/orb.py
Tests: tests/test_indicators.py (20 tests)

Key facts:
- pandas-ta was REPLACED by `ta` library (pandas-ta requires numba, numba doesn't support Python 3.14)
- All indicator compute() methods use pd.concat to add columns — never chained assignment
- NIFTY50 complete instrument list in data/instruments.py with Kite↔yfinance symbol map
- settings.py is the single source of truth for all constants

## Phase 2 — Strategies + Risk Engine ✅
Files: strategies/base_strategy.py, strategies/ema_crossover.py,
strategies/rsi_macd_combo.py, strategies/opening_range_breakout.py,
risk/risk_manager.py, risk/position_sizer.py, risk/circuit_breaker.py
Tests: tests/test_strategies.py (22 tests), tests/test_risk_manager.py (22 tests)

Key facts:
- Signal dataclass has is_valid(), reward_risk_ratio, total_risk properties
- ORB strategy uses ATR fallback for target when price already exceeds ORB projection
- RiskManager has RiskState dataclass tracking daily_pnl, consecutive_losses, halt_until
- Position sizing: qty = floor((capital × 0.01) / abs(entry - stop_loss))
- 10 hardcoded risk rules; RiskManager.evaluate() is the mandatory approval gate
- RiskManager.new_day(capital) resets daily state — capital arg is required
- reward_risk_ratio check uses round(..., 2) to avoid float precision rejections

## Phase 3 — Paper Trading Simulator ✅
Files: broker/base_broker.py, broker/paper_broker.py, execution/order_manager.py,
execution/trade_log.py, execution/portfolio.py
Tests: tests/test_paper_broker.py (23 tests)

Key facts:
- BaseBroker abstract interface: paper and live brokers are interchangeable
- PaperBroker simulates ALL Zerodha costs: ₹20 brokerage + STT + exchange + GST + SEBI + stamp duty
- Default slippage: 0.1% on market orders
- Trade log stored in logs/trades.db (SQLite, created on first run)
- TradeLogger has get_today_trades(), get_daily_pnl(), get_strategy_summary() query methods
- OrderManager auto-squares-off all positions at 3:15 PM IST
- OrderManager.open_symbols is a @property (not a method) — no parentheses

## Phase 4 — Backtesting Engine ✅
Files: backtesting/engine.py, backtesting/performance.py, backtesting/report.py,
scripts/run_backtest.py
Tests: tests/test_backtesting.py (21 tests)

Key facts:
- BacktestEngine strictly prevents lookahead: `day_df.iloc[:i+1]` on every candle
- Auto-selects daily vs 5-min candles: >55-day range → daily (yfinance 60-day intraday limit)
- KITE_TO_YF mapping applied before yfinance fetch
- _estimate_brokerage() mirrors PaperBroker cost model for realistic P&L
- PerformanceMetrics: win_rate, profit_factor, expectancy, Sharpe (simplified), max_drawdown
- generate_report() writes self-contained Plotly HTML (no internet needed to view)
- CLI: `python scripts/run_backtest.py --symbol RELIANCE --strategy ema_crossover --start 2023-01-01 --end 2024-12-31`
- `--all-strategies` flag runs all 3 strategies on same symbol for comparison

## Phase 5 — Streamlit Dashboard ✅
Files: analysis/market_overview.py, analysis/stock_scanner.py,
dashboard/app.py, dashboard/views/home.py, dashboard/views/signals.py,
dashboard/views/backtest.py, dashboard/views/analysis.py,
dashboard/views/bot_control.py, dashboard/views/settings.py,
scripts/run_dashboard.py, scripts/run_bot.py

Key facts:
- Dashboard is multi-page via sidebar radio (views/ NOT pages/ — Streamlit auto-detects pages/)
- Run with: `venv/Scripts/python.exe -m streamlit run dashboard/app.py`
- Home page reads from SQLite trade log (TradeLogger) and shows daily P&L chart
- Signals page runs scanner on all NIFTY50, shows candlestick + entry/SL/target levels
- Backtest page: interactive — pick symbol/strategy/dates/capital → equity curve + HTML report
- Analysis page: NIFTY50 breadth (advance/decline donut), top gainers/losers from yfinance
- Bot Control page: start/stop scheduler, view activity log, next job schedule
- Settings page: read-only view of all config constants; has how-to-go-live guide
- TradeLogger instantiated at module level in views (not inside render()) — avoids repeated DB init on reruns
- NIFTY50_INSTRUMENTS (list of Instrument objects) — use `.kite_symbol` to get symbol strings
- VIRTUAL_CAPITAL is the config constant for starting capital (not INITIAL_CAPITAL)

## Phase 6 — Scheduler + Notifications ✅
Files: scheduler/job_runner.py, scheduler/bot_controller.py,
notifications/telegram_notifier.py, data/nse_holidays.py

Key facts:
- APScheduler BackgroundScheduler (NOT BlockingScheduler — that freezes Streamlit)
- 7 IST-scheduled jobs: pre_market_scan (9:00), market_open (9:15), signal_check (9:20–14:25 every 5m),
  stop_new_entries (14:30), square_off_all (15:15), daily_report (15:30), auto_shutdown (15:35)
- signal_check fetches all symbols in parallel via ThreadPoolExecutor(max_workers=3)
  — max_workers=3 intentionally low to avoid yfinance rate-limiting
- NSE holiday calendar 2024–2026 in data/nse_holidays.py; _is_market_day() checked at start of every job
- Telegram notifier sends entry/exit alerts and EOD report with CSV attachment
- Bot auto-starts at 8:55 AM IST Mon–Fri via Windows Task Scheduler (\TreadingBot\ task)
- Bot self-terminates at 15:35 via auto_shutdown() — no manual intervention needed

## Phase 6b — Live Kite (Deferred) 🔲
Files: data/market_feed.py (stub), broker/kite_broker.py (stub)
- KiteTicker WebSocket + candle builder + reconnection logic (not yet implemented)
- Daily re-auth required: Kite access_token expires every day at midnight (SEBI rule)

## Intraday Short Selling ✅ (April 2026)
Files: broker/paper_broker.py, config/settings.py, backtesting/portfolio_sim.py,
backtesting/day_replay.py, scheduler/job_runner.py
Tests: tests/test_short_selling.py (10 new tests)

Key facts:
- `SHORT_SELLING_ENABLED = True` in config/settings.py is the master switch
- SELL signal = open new short position (when no existing position in symbol)
- Existing long positions still exit via SL/target/EOD price checks only (not via SELL signal)
- Rule #9 (no duplicate symbol) prevents simultaneous long+short in same symbol
- backtesting/engine.py already supported shorts — no change needed there
- paper_broker now: opening short deducts margin; covering short (BUY) returns margin + PnL
- square_off_all() now issues BUY to close short positions (was always SELL before)
- Impact: 2× more trades, win rate 18% → 46%, near-breakeven on recent 5-day down market

## Phase 7 Prep — Strategy Degradation Detection ✅
Files: monitoring/degradation.py, monitoring/__init__.py
Tests: tests/test_degradation.py (21 tests)

Key facts:
- `StrategyHealth` dataclass: baseline_win_rate (from config), rolling_win_rate (last 20 trades), is_degraded flag
- Degraded = has_enough_trades (≥10) AND drop > DEGRADATION_THRESHOLD_PCT (15pp)
- Baselines in config/settings.py: ema_crossover=50%, rsi_macd_combo=45%, opening_range_breakout=50%
- `TradeLogger.get_rolling_win_rate(strategy, n)` added — queries last N closed trades for a strategy
- `check_all_strategies()` returns sorted list (degraded first)
- Bot Monitor page now shows "Strategy Health" panel: 3 metric cards (🔴/🟠/🟡/🟢)

## 2026-04-02 Incident Response + System Upgrades ✅
Files added/changed: strategies/rsi_macd_combo.py, strategies/vwap_bounce.py (new),
config/strategies.py, config/adaptive.py (new), analysis/market_direction.py (new),
data/india_vix.py, risk/risk_manager.py, scheduler/job_runner.py,
dashboard/views/bot_control.py, dashboard/views/home.py, dashboard/views/journal.py,
broker/paper_broker.py, execution/order_manager.py, execution/trade_log.py,
scheduler/bot_controller.py, scripts/backtest_15days.py (new)
Tests: 193 passing (net +11 from before session)

What triggered this:
- Bot ran 8 SELL trades on a TRENDING UP day (NIFTY +1.4%) — all losses — Rs6,348 loss
- Root cause 1: no trend-direction awareness (shorted into uptrend)
- Root cause 2: risk state (consecutive_losses, daily_pnl) reset on every restart
- Bot was restarted 13+ times; each restart cleared the 3-consecutive-loss pause

Fixes applied:
1. rsi_macd_combo now has: EMA alignment gate, VWAP direction filter, RSI oversold gate,
   min SL distance (max 1.5×ATR, 0.75% price), MACD histogram acceleration
2. RiskManager.restore_daily_state() reads closed trades from DB on startup → halts survive restarts
3. Open trade recovery on restart — positions reconstructed from DB, not lost
4. VIX direction bias: india_vix._classify() now checks NIFTY intraday direction to decide
   skip_sells vs skip_buys (not always skip_buys on elevated VIX)
5. VWAP Bounce strategy (#5) — buys VWAP pullbacks on up days, confirmed cross entry
6. AdaptiveStrategyManager — monitors VIX/regime/losses/time every 60s, adjusts rsi_macd_combo
   params at runtime (NORMAL→DEFENSIVE→HALTED), strategies call _reload_params() per signal
7. Intraday direction detector (analysis/market_direction.py) — 3-signal consensus from today's
   candles only (gap vs prev_close, intraday pct at 10AM, green candle fraction 9:15-10:00)
8. NEUT days → sit out entirely (both skip_sells=True and skip_buys=True)
9. scripts/backtest_15days.py — multi-symbol direction-aware backtest for any strategy set
10. Dashboard: adaptive mode panel (mode badge + VIX/regime/direction/losses/P&L), live P&L
    in Today's Trades, historical journal with date filter + CSV export

Key numbers from 2026-04-02 analysis:
- Old bot (no filters): 156 signals/day on 10 symbols → total chaos
- Normal (new filters): 2 signals → still losses on an up-day if direction wrong
- DEFENSIVE (VIX direction bias): 0 signals → Rs 0 (safe but missed opportunity)
- VIX direction bias + VWAP Bounce: 3 BUY signals → Rs +5,959 (3/3 wins, simulated)
- 15-day backtest during tariff sell-off: Rs -545 (-0.55%) vs old bot Rs -6,348 just on day 1

Key DEFENSIVE params (rsi_macd_combo):
  rsi_buy_min: 45, rsi_buy_max: 60, rsi_sell_min: 50, rsi_exit: 85, min_sl_pct: 1.0%
  (rsi_exit must be HIGHER in defensive to generate FEWER short signals, not lower)

Also confirmed already done from earlier sessions:
- #13 MACD histogram acceleration filter: in rsi_macd_combo.py:97-107 (`hist_accelerating` check)
- #14 yfinance retry: in data/historical.py:89-94 (sleep(2) + retry on empty response)

## Windows Environment Notes (March 2026)
- Project migrated from Mac to Windows. Old Mac venv unusable (Unix shebangs, Homebrew paths).
- Rebuilt venv with Python 3.14 (Windows installer from python.org).
- Key version upgrades needed for Python 3.14 + Windows compatibility:
  - pandas: 2.2.1 → 2.3.3 (cp314 wheel)
  - numpy: 1.26.4 → 2.4.4 (cp314 wheel)
  - streamlit: 1.33.0 → 1.55.0 (numpy<2 constraint dropped)
  - sqlalchemy: 2.0.29 → 2.0.48 (Python 3.14 __static_attributes__ fix)
  - yfinance: 0.2.37 → 1.2.0 (Yahoo Finance API change)

**Why:** User is a stock market beginner who wants paper trading first for safety.
**How to apply:** Always confirm TRADING_MODE=paper before any live suggestions. Never suggest live trading until 30+ days paper trading with positive results.
