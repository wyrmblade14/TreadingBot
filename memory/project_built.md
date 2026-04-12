---
name: What Has Been Built
description: Completed phases of the TreadingBot — modules, files, test counts, and key functionality
type: project
---

All code lives at the project root, grouped by domain package:
`data/`, `indicators/`, `strategies/`, `risk/`, `broker/`, `execution/`,
`analysis/`, `scheduler/`, `dashboard/`, `backtesting/`, `notifications/`,
`monitoring/`, `scripts/`, and `tests/`.

Virtual environment: `venv/`.
- macOS/Linux: `source venv/bin/activate`
- Windows: `venv/Scripts/python.exe` (not `venv/bin/`)

Current test status: 275 passing, 0 failures (April 2026, Python 3.14).

Current architecture boundaries:
- `analysis/` owns market/fundamental/catalyst/regime scoring and stock-universe selection.
- `scheduler/watchlist.py` owns daily bot watchlist selection and fundamental judgment lookup.
- `scheduler/job_runner.py` owns timed trading-day jobs only.
- `risk/risk_manager.py` remains the mandatory approval gate and position-size scaler.
- `execution/order_manager.py` owns entry/exit lifecycle and V-reversal exits.
- `broker/paper_broker.py` owns paper fills, margin, short support, slippage, and costs.

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
Tests: tests/test_strategies.py, tests/test_risk_manager.py

Key facts:
- Signal dataclass has is_valid(), reward_risk_ratio, total_risk properties
- ORB strategy uses ATR fallback for target when price already exceeds ORB projection
- RiskManager has RiskState dataclass tracking daily_pnl, consecutive_losses, halt_until
- Position sizing: qty = floor((capital × 0.01) / abs(entry - stop_loss))
- RiskManager.evaluate() is the mandatory approval gate for all new entries
- RiskManager.new_day(capital) resets daily state — capital arg is required
- reward_risk_ratio check uses round(..., 2) to avoid float precision rejections

## Phase 3 — Paper Trading Simulator ✅
Files: broker/base_broker.py, broker/paper_broker.py, execution/order_manager.py,
execution/trade_log.py, execution/portfolio.py
Tests: tests/test_paper_broker.py (23 tests)

Key facts:
- BaseBroker abstract interface: paper and live brokers are interchangeable
- PaperBroker simulates ALL Zerodha costs: ₹20 brokerage + STT + exchange + GST + SEBI + stamp duty
- Default slippage: 0.2% per side on market orders
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
- `--all-strategies` flag runs every configured strategy on the same symbol for comparison

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
Files: scheduler/job_runner.py, scheduler/watchlist.py, scheduler/bot_controller.py,
scheduler/bot_state.py, notifications/telegram_notifier.py, data/nse_holidays.py

Key facts:
- APScheduler BackgroundScheduler (NOT BlockingScheduler — that freezes Streamlit)
- 7 IST-scheduled jobs: pre_market_scan (9:00), market_open (9:15), signal_check (9:20–14:25 every 5m),
  stop_new_entries (14:30), square_off_all (15:15), daily_report (15:30), auto_shutdown (15:35)
- scheduler/watchlist.py selects the daily fundamentals-ranked NIFTY50 watchlist and fails open to static first-N if fundamentals data is unavailable
- signal_check fetches all symbols in parallel via ThreadPoolExecutor(max_workers=3)
  — max_workers=3 intentionally low to avoid yfinance rate-limiting
- NSE holiday calendar 2024–2026 in data/nse_holidays.py; _is_market_day() checked at start of every job
- Telegram notifier sends entry/exit alerts and EOD report with CSV attachment
- Bot auto-starts at 8:55 AM IST Mon–Fri via Windows Task Scheduler (\TreadingBot\ task)
- Bot self-terminates at 15:35 via auto_shutdown() — no manual intervention needed

## Phase 6b — Live Kite (Deferred) 🔲
Built so far: data/kite_auth.py, data/kite_feed.py, data/kite_ticker.py
Still deferred: broker/kite_broker.py live order execution and daily re-auth UI helper.
- KiteTicker WebSocket + candle builder exists and is used by job_runner when Kite is available
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
Tests at that point: 193 passing (net +11 from before session)

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

## V-Reversal Exit + Notification Dedup (April 2026) ✅
Files changed: execution/order_manager.py, scheduler/job_runner.py,
notifications/telegram_notifier.py
Tests added: tests/test_reversal_exit.py (9 tests)
Tests at that point: 202

Features:
1. **V-reversal early exit** — OrderManager.check_reversal_exit(symbol, price, vwap):
   - SELL trade: price crosses back above VWAP within 30 min → exit at market
   - BUY trade: price falls back below VWAP within 30 min → exit at market
   - Triggered from signal_check() BEFORE the normal SL/target check
   - VWAP computed from the df already fetched for that cycle
   - Saves ~40–60% of max loss on V-reversal days (exit near VWAP, not at full SL)
   - 30-min window constant: _REVERSAL_WINDOW_SECS in execution/order_manager.py

2. **Once-per-day notification dedup** — TelegramNotifier._once_today(key):
   - Prevents pre_market briefing and bot_started alerts from firing again on bot restart
   - _sent_today dict: event_key → YYYY-MM-DD string; checked/set inside self._lock
   - Applied to notify_premarket() and notify_bot_started()

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

## Fundamentals Watchlist + Structure Refactor (April 2026) ✅
Files added/changed: analysis/fundamental_selector.py, scheduler/watchlist.py,
scheduler/job_runner.py, tests/test_fundamental_selector.py,
tests/test_scheduler_watchlist.py, README.md, memory/*.md.

Key facts:
- Bot no longer blindly scans the first N NIFTY50 symbols. It selects a daily
  fundamentals-ranked watchlist before trading.
- analysis/fundamental_selector.py ranks by sector-relative FundamentalScore,
  avoids earnings blackout names when alternatives exist, caps sector concentration,
  and fails open if yfinance fundamentals data is unavailable.
- scheduler/watchlist.py owns DailyWatchlist, static fallback selection,
  fundamental selection, and per-symbol FundamentalJudgment lookup.
- scheduler/job_runner.py now stays focused on scheduled jobs and passes
  FundamentalJudgment into RiskManager.evaluate() for size scaling.
- Full suite after refactor: 272 passed, 1 Loguru deprecation warning.

## Apr 10 Post-Mortem Bug Fixes (April 2026) ✅
Files changed: execution/order_manager.py, scheduler/job_runner.py.
Test count: 275 passing.

Post-mortem of April 10 trades (13 trades, 0 wins, -₹5,411) and April 2 (-₹11,557) revealed 3 bugs:

1. **Race condition on `_last_signal_key`** (scheduler/job_runner.py): The signal dedup set had no
   lock. Concurrent `signal_check()` executions both passed the guard simultaneously, producing
   2–3 identical orders in the same millisecond. Fix: `_last_signal_lock = threading.Lock()` wraps
   the check+add atomically. Also added last-resort guard in `OrderManager._execute_signal_locked()`:
   if symbol in `_open_trades`, return False immediately.

2. **Re-entry loop after fast SL exit** (execution/order_manager.py): After a 2-second SL hit, the
   same signal re-fired on the next tick. AXISBANK was entered 3× in 4 minutes (-₹1,053 extra).
   Fix: `_cooldown: dict[str, tuple[datetime, Action]]` — 30-min block after any exit, plus a
   same-session direction lock (prevents two strategies from taking opposite sides on the same symbol).
   Cooldown is set in `_close_trade()` and checked at top of `_execute_signal_locked()`.

3. **Regime filter not wired into signal loop** (scheduler/job_runner.py): On April 2, VIX=26
   correctly blocked BUY signals but not SELL signals. Market went UP +2%. All 12 short trades lost.
   `get_market_direction()` and `get_current_regime()` were computed at 09:00 but never consulted
   during intraday scanning. Fix: check both in `signal_check()` before `_risk_mgr.evaluate()`.
   Suppress SELL when `MarketDirection.UP + MarketRegime.TRENDING`, BUY when DOWN + TRENDING.
   Wrapped in try/except — fail-open.
