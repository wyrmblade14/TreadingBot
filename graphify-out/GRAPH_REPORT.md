# Graph Report - .  (2026-04-12)

## Corpus Check
- 133 files · ~115,575 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1818 nodes · 4589 edges · 122 communities detected
- Extraction: 50% EXTRACTED · 50% INFERRED · 0% AMBIGUOUS · INFERRED: 2290 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## God Nodes (most connected - your core abstractions)
1. `Action` - 235 edges
2. `Signal` - 181 edges
3. `PaperBroker` - 100 edges
4. `TradeLogger` - 96 edges
5. `RiskManager` - 94 edges
6. `OrderType` - 85 edges
7. `TransactionType` - 85 edges
8. `BaseStrategy` - 84 edges
9. `EMACrossoverStrategy` - 78 edges
10. `OrderStatus` - 69 edges

## Surprising Connections (you probably didn't know these)
- `analysis/nifty_correlation.py (NIFTY Divergence Filter)` --semantically_similar_to--> `analysis/regime_detector.py (Trending/Ranging/Volatile)`  [INFERRED] [semantically similar]
  docs/superpowers/specs/2026-04-11-nifty-divergence-filter-design.md → README.md
- `Day Replay CLI — replay a past trading day through all strategies.  Usage exampl` --uses--> `DayReplayEngine`  [INFERRED]
  scripts/run_replay.py → backtesting/day_replay.py
- `India VIX — market fear gauge fetched from yfinance.  What is India VIX?   India` --uses--> `MarketDirection`  [INFERRED]
  data/india_vix.py → analysis/market_direction.py
- `Return current India VIX with TTL cache.      Returns a dict with keys:` --uses--> `MarketDirection`  [INFERRED]
  data/india_vix.py → analysis/market_direction.py
- `Return (level_str, skip_buys, skip_sells, skip_all) for a given VIX value.` --uses--> `MarketDirection`  [INFERRED]
  data/india_vix.py → analysis/market_direction.py

## Hyperedges (group relationships)
- **Incident-Driven Safety Improvements (April 2026 bugs → fixes)** — incident_20260402, incident_20260410, concept_signal_dedup, concept_cooldown_reentry, concept_regime_filter_signal_loop, concept_risk_state_persistence [EXTRACTED 0.90]
- **Market Context Awareness System (VIX + direction + regime + divergence)** — arch_data_india_vix, arch_analysis_market_direction, arch_analysis_regime_detector, arch_analysis_nifty_correlation [INFERRED 0.85]
- **Signal Pipeline Filter Chain (strategy → catalyst → fundamental → divergence → regime → risk → order)** — arch_strategy_ema_crossover, arch_analysis_catalyst_scanner, arch_analysis_fundamental_analyst, arch_analysis_nifty_correlation, arch_analysis_regime_detector, arch_risk_manager, arch_execution_order_manager [EXTRACTED 0.92]
- **Signal Pipeline Filter Chain (6 ordered filters)** — filter_dedup, filter_shortselling, filter_catalyst, filter_fundamentals, filter_regime, filter_divergence [EXTRACTED 1.00]
- **April 2026 Incidents → Pipeline Refactor Motivation** — incident_20260402, incident_20260410_bhartiartl, incident_20260410_axisbank, rationale_explicit_pipeline [EXTRACTED 1.00]

## Communities

### Community 0 - "Strategy Core & Signal Types"
Cohesion: 0.04
Nodes (182): Simulate one trading day. Returns list of trade dicts., 3-signal consensus direction at 10:00 AM. No look-ahead.     Returns (skip_sells, Action, BaseStrategy, Basic sanity checks on the signal values., Abstract base class that all trading strategies must inherit from.      Subclass, Convenience method to return a HOLD signal., Calculate ATR (Average True Range) for stop-loss placement.          ATR measure (+174 more)

### Community 1 - "Broker Abstraction Layer"
Cohesion: 0.03
Nodes (115): BaseBroker, Order, OrderStatus, OrderType, Position, Abstract broker interface.  Both the Paper Broker (simulated) and the Live Kite, Represents a single order submitted to the broker., Represents an open position in the portfolio. (+107 more)

### Community 2 - "Technical Indicators"
Cohesion: 0.04
Nodes (77): BaseIndicator, Abstract base class that all indicators inherit from., BaseIndicator, Strategy 1: EMA Crossover  This is the simplest and most beginner-friendly strat, EMAIndicator, EMA (Exponential Moving Average) Crossover Indicator.  What is EMA?   An EMA is, Computes EMA crossover signals using 9/21/50 period EMAs.      Args:         sho, Append EMA columns to the DataFrame.          New columns added:           ema_s (+69 more)

### Community 3 - "Backtesting Engine"
Cohesion: 0.04
Nodes (52): Backtest page — run a strategy on historical data interactively.  What is backte, 30-Day Portfolio Simulation tab.      Runs ALL strategies across ALL selected sy, render(), _render_portfolio_sim(), _render_single_backtest(), _render_walk_forward(), BacktestEngine, BacktestResult (+44 more)

### Community 4 - "Fundamental Analysis"
Cohesion: 0.04
Nodes (48): Analysis page — NIFTY50 market overview, breadth, top movers.  What you see here, FundamentalAnalyst, FundamentalJudgment, Fundamental Analyst — Claude AI-powered fundamental synthesis.  Why fundamentals, Analyzes fundamental metrics for a NIFTY50 stock and returns a structured     tr, Analyze fundamental metrics for a stock and return a judgment.          Uses Cla, Call Claude API (claude-haiku-4-5) with a structured prompt and parse         th, Simple rule-based judgment without AI.          Used as fallback when: (+40 more)

### Community 5 - "Fundamental Filtering"
Cohesion: 0.04
Nodes (49): _check_book(), _check_debt(), _check_earnings_trend(), _check_margin(), _check_pe(), FundamentalScore, _neutral_score(), Fundamental Filter — sector-relative fundamental scoring for NIFTY50 stocks.  Wh (+41 more)

### Community 6 - "News Catalyst Scanner"
Cohesion: 0.07
Nodes (41): CatalystSummary, get_todays_catalysts(), Catalyst Scanner — parallel pre-market scan of all NIFTY50 stocks.  What this do, Return the day's catalyst summary.      Returns the cached result if scan_all_ca, Wrapper that catches all exceptions so pool workers never crash., Result of a full watchlist catalyst scan., Scan the given symbol list (or full NIFTY50 if None) for catalysts.      Fetches, _safe_get_catalyst() (+33 more)

### Community 7 - "System Architecture Docs"
Cohesion: 0.04
Nodes (59): analysis/fundamental_analyst.py (FundamentalAnalyst), analysis/market_direction.py (intraday NIFTY direction), analysis/nifty_correlation.py (NIFTY Divergence Filter), analysis/regime_detector.py (Trending/Ranging/Volatile), dashboard/app.py (Streamlit entry point), data/historical.py (fetch_ohlcv), data/kite_feed.py, data/kite_ticker.py (+51 more)

### Community 8 - "Fundamentals Data Cache"
Cohesion: 0.06
Nodes (33): FundamentalsCache, _parse_date(), Fundamentals page — fundamental health analysis for all NIFTY50 stocks.  What is, Return a dict of fundamental metrics for *symbol*.          Keys (all values are, Classify the company's recent EPS trajectory using last 4 quarters.          Met, Return the next upcoming earnings date for *symbol*, or None.          Only retu, Return True if today falls within the earnings volatility window.          The w, Best-effort conversion of an unknown date-like object to a Python date.     Hand (+25 more)

### Community 9 - "Adaptive Strategy Config"
Cohesion: 0.05
Nodes (41): ABC, AdaptiveMode, _apply_params(), get_current_mode(), get_nifty50_fundamental_health(), get_state(), Adaptive Strategy Manager — continuously adjusts strategy parameters based on re, Classify the aggregate fundamental health of NIFTY50 stocks.      Calls score_fu (+33 more)

### Community 10 - "Trade Notifications"
Cohesion: 0.06
Nodes (33): get_notifier(), _h(), Telegram Notifier — sends intelligent trade alerts to your phone.  Why Telegram?, Alert: new trade entered — includes day context., Alert: trade closed — includes outcome context and running P&L., 9:00 AM pre-market briefing — sent once per day., Alert: adaptive mode shifted (e.g. NORMAL → DEFENSIVE)., Alert: risk manager halted trading. (+25 more)

### Community 11 - "Strategy Degradation Monitor"
Cohesion: 0.07
Nodes (14): check_all_strategies(), check_strategy(), Strategy Degradation Detection — catches when a strategy stops working.  What is, Check degradation for a single strategy.      Args:         strategy: Strategy n, Check degradation for all strategies defined in STRATEGY_BASELINES.      Args:, Health snapshot for one strategy., StrategyHealth, _make_health() (+6 more)

### Community 12 - "Strategy Unit Tests"
Cohesion: 0.08
Nodes (9): _make_bb_buy_df(), _make_bb_sell_df(), make_ohlcv(), make_orb_df(), TestBBMeanReversionStrategy, TestEMACrossoverStrategy, TestORBStrategy, TestRSIMACDStrategy (+1 more)

### Community 13 - "Broker Unit Tests"
Cohesion: 0.14
Nodes (6): _ist_dt(), make_broker(), TestPaperBrokerOrders, TestPaperBrokerPortfolio, TestPaperBrokerPositions, TestPaperBrokerSquareOff

### Community 14 - "Signal Pipeline Tests"
Cohesion: 0.13
Nodes (10): _in_line(), _lagging(), _leading(), _make_catalyst(), _make_context(), _make_judgment(), _make_signal(), _mock_catalysts() (+2 more)

### Community 15 - "Kite Live Feed (Deferred)"
Cohesion: 0.08
Nodes (18): _bucket_ts(), get_ticker_feed(), KiteTickerFeed, _normalise_ts_for_pandas(), KiteTicker real-time candle builder.  Streams live NSE tick data via Zerodha's W, Manages a KiteTicker WebSocket connection and builds live OHLCV candles.      Th, Connect to KiteTicker and start streaming ticks.          Args:             watc, Disconnect WebSocket and stop the feed. (+10 more)

### Community 16 - "Risk Manager Tests"
Cohesion: 0.12
Nodes (4): _make_judgment(), make_signal(), TestPositionScaling, TestRiskManager

### Community 17 - "Strategy Comparison Dashboard"
Cohesion: 0.11
Nodes (24): _build_stats(), _colour_metric(), _profit_factor(), Strategy Head-to-Head Comparison — live performance from paper trade data.  Why, Return green/red colour string based on whether value is above threshold., Banner showing which strategy is currently leading on P&L., Render one strategy's KPI card in the given column., Cumulative P&L line chart — one line per strategy, plotted on shared time axis. (+16 more)

### Community 18 - "NIFTY Divergence Tests"
Cohesion: 0.12
Nodes (21): _make_df(), Tests for analysis/nifty_correlation.py — NIFTY divergence filter.  Each test in, Empty DataFrame → IN_LINE (data error never blocks a signal)., None DataFrame → IN_LINE (fail-open)., LAGGING stock + SELL signal: suppress_buy=True but suppress_sell=False → SELL pa, get_nifty_change() returns 0.0 before 10:00 AM IST (opening noise)., Build a minimal 5m DataFrame with two rows for today.     First row = opening ca, NIFTY +1.2%, stock +0.1% → LAGGING: suppress_buy=True, amplify_sell=True. (+13 more)

### Community 19 - "Trade Logging & Database"
Cohesion: 0.11
Nodes (13): DeclarativeBase, One-shot migration: copy all rows from logs/trades.db (SQLite) into PostgreSQL., Base, init_db(), Trade Log — persists every trade to a SQLite database.  Why log trades?   The on, Record a new trade entry. Returns the database row ID.         Use this ID later, Return today's trades that are still open (exit_price IS NULL)., Return all trades for today. (+5 more)

### Community 20 - "Community 20"
Cohesion: 0.13
Nodes (9): BotController, get_controller(), BotController — singleton that manages the trading bot lifecycle from the UI.  W, Stop the scheduler and square off all open positions.          Works whether the, Return current bot status — reads the shared state file.          Works cross-pr, Return recent log events, newest first. Only available in the owning process., Return the process-wide singleton BotController., Thread-safe singleton for start/stop/status of the paper trading bot.      get_s (+1 more)

### Community 21 - "Community 21"
Cohesion: 0.12
Nodes (3): _check_exit_signal(), _close_trade(), _estimate_brokerage()

### Community 22 - "Community 22"
Cohesion: 0.12
Nodes (9): CandleStore, In-memory candle store for the live trading session.  During live/paper trading,, Thread-safe in-memory store for intraday OHLCV candles.      Each symbol has its, Add a completed candle to the store for a given symbol., Return all candles for a symbol as a DataFrame., Return the most recent n candles for a symbol., Return list of all symbols currently in the store., Clear all candle data (called at start of each trading day). (+1 more)

### Community 23 - "Community 23"
Cohesion: 0.21
Nodes (16): auto_shutdown(), build_scheduler(), daily_report(), _fetch_symbol_data(), _get_ltp(), _is_market_day(), market_open(), _on_tick_exit() (+8 more)

### Community 24 - "Community 24"
Cohesion: 0.15
Nodes (13): _check_macd(), _check_rsi(), _check_trend(), _check_volume(), _check_vwap(), Signal Confidence Scorer — rates every signal from 0 to 5.  Why this exists:   Y, Score a trading signal against 5 independent technical checks.      Args:, Price above EMA50 for BUY, below EMA50 for SELL. (+5 more)

### Community 25 - "Community 25"
Cohesion: 0.23
Nodes (14): get_current_crontab(), install(), main(), Scheduler helper — install, remove, or check the TreadingBot scheduled jobs.  Wh, # NOTE: cron times assume system TZ = Asia/Kolkata., Create a single Windows Task Scheduler entry., remove(), set_crontab() (+6 more)

### Community 26 - "Community 26"
Cohesion: 0.19
Nodes (15): _entry_hour(), _exit_type(), _friendly_strategy(), _hold_duration(), _hold_minutes(), _pnl_colour(), Trade Journal — every paper trade as a readable logbook entry.  Why this page ex, Return the reward:risk ratio actually captured at exit. (+7 more)

### Community 27 - "Community 27"
Cohesion: 0.17
Nodes (13): indicators/ema.py (EMA 9/21/50), indicators/orb.py (Opening Range), indicators/vwap.py (VWAP daily reset), strategies/ema_crossover.py, strategies/opening_range_breakout.py, ORB Bug: Opening range spans multiple days not just today, VWAP Bug: Zero-volume candle crash (fixed), Finding: 5m candles better than 1h for intraday bot (+5 more)

### Community 28 - "Community 28"
Cohesion: 0.24
Nodes (9): fetch_kite_ohlcv(), get_kite_ltp(), _load_instrument_tokens(), _normalise_record_datetime(), Kite Connect data feed — precise NSE market data.  Replaces yfinance during mark, Fetch OHLCV data from Kite Connect REST API.      Returns a DataFrame in the sam, Fetch Last Traded Price for multiple symbols via Kite REST API.      Args:, Convert Kite candle timestamps to pandas-safe ZoneInfo datetimes.      Kite retu (+1 more)

### Community 29 - "Community 29"
Cohesion: 0.24
Nodes (8): clear(), _pid_alive(), Shared bot state — persisted to disk so any process can read it.  Why a file?, Check if a process is still running without killing it., Return state dict if file exists and the recorded PID is still alive., Terminate a bot running in another process. Returns True if sent., read(), stop_remote()

### Community 30 - "Community 30"
Cohesion: 0.24
Nodes (6): Tests for data/kite_feed.py.  These keep Kite API calls mocked so they run offli, Tata Motors demerger changed NSE symbol from TATAMOTORS to TMPV., Kite returns pytz-aware datetimes. pandas/Python 3.14 can fail if those, _reset_token_cache(), TestKiteFeed, TestKiteSymbols

### Community 31 - "Community 31"
Cohesion: 0.32
Nodes (7): compute_vwap(), get_vwap_signal(), _is_daily(), VWAP — Volume Weighted Average Price.  What is VWAP and why does it matter?   VW, True if the DataFrame contains daily (not intraday) candles.      Daily candles, Compute VWAP for each candle, resetting at the start of each trading day.      A, Return VWAP directional bias for the latest candle.      Returns:          1  —

### Community 32 - "Community 32"
Cohesion: 0.39
Nodes (7): _is_alive(), Bot lifecycle manager — start, stop, or restart the TreadingBot.  Usage:     pyt, Check if a process is alive (cross-platform)., Read the bot's PID from bot_state.json; return None if not running., _running_pid(), _start(), _stop()

### Community 33 - "Community 33"
Cohesion: 0.32
Nodes (7): fetch_daily_ohlcv(), fetch_multiple(), fetch_ohlcv(), Historical OHLCV data fetcher using yfinance.  OHLCV explained (every candle has, Download daily OHLCV data for backtesting.      Daily candles are available for, Download OHLCV data for multiple symbols in one call.      Returns a dict mappin, Download intraday OHLCV data from Yahoo Finance.      Args:         yf_symbol: N

### Community 34 - "Community 34"
Cohesion: 0.32
Nodes (7): _classify(), get_vix_data(), India VIX — market fear gauge fetched from yfinance.  What is India VIX?   India, Return (level_str, skip_buys, skip_sells, skip_all) for a given VIX value., Return the cached value if available, else a fail-open default., Return current India VIX with TTL cache.      Returns a dict with keys:, _safe_default()

### Community 35 - "Community 35"
Cohesion: 0.25
Nodes (7): isolated_test_db(), mock_fundamentals(), mock_india_vix(), pytest configuration and shared fixtures.  Auto-patches external network calls s, Patch India VIX to return a safe, non-restrictive value for all tests., Patch earnings blackout to return False so Rule 11 doesn't block tests.      Rul, Point every test at a fresh SQLite DB in a temp directory.      Tests never touc

### Community 36 - "Community 36"
Cohesion: 0.29
Nodes (7): _fetch_nifty_5m(), get_divergence(), get_nifty_change(), NIFTY Divergence Filter — detects when a stock is diverging from the index.  Why, Compare symbol's intraday % change vs NIFTY's pre-fetched change.      Args:, Fetch NIFTY50 5-minute candles. Kite first, yfinance fallback., Return NIFTY50's intraday % change vs today's 9:15 open. Cached 5 min.      Retu

### Community 37 - "Community 37"
Cohesion: 0.29
Nodes (6): get_instrument(), get_symbols_by_sector(), Instrument, NIFTY50 instruments registry.  NIFTY50 is India's flagship stock index containin, Return the Instrument dataclass for a given Kite symbol., Return all Kite symbols for a given sector.

### Community 38 - "Community 38"
Cohesion: 0.33
Nodes (5): check_circuit_risk(), check_market_circuit(), Circuit breaker checker for NSE stocks and indices.  What is a circuit breaker?, Check if a stock is approaching its circuit limit.      Args:         symbol:, Check if the broad NIFTY market has triggered a circuit breaker.      Args:

### Community 39 - "Community 39"
Cohesion: 0.6
Nodes (5): _load_baseline(), main(), run_weekly(), _save_baseline(), _send_alert()

### Community 40 - "Community 40"
Cohesion: 0.4
Nodes (5): is_trading_day(), next_trading_day(), NSE Trading Holiday Calendar.  NSE publishes a list of market holidays each year, Return True if the given date is a regular NSE trading day.      A trading day i, Return the next trading day on or after from_date.

### Community 41 - "Community 41"
Cohesion: 0.33
Nodes (5): get_kite_client(), is_kite_available(), Kite Connect authentication helper.  Kite Connect requires a fresh access_token, Return an authenticated KiteConnect instance, or None if not configured.      Re, Quick check: returns True if Kite credentials are fully configured.

### Community 42 - "Community 42"
Cohesion: 0.47
Nodes (5): _get_live_ltp(), _pnl_colour(), Home page — Portfolio summary, today's trades, capital breakdown.  Reads from SQ, Try to get a live price for symbol from available sources:       1. KiteTickerFe, render()

### Community 43 - "Community 43"
Cohesion: 0.33
Nodes (6): memory/ideas_and_improvements.md, memory/MEMORY.md (index), memory/lessons_learned.md, memory/project_planned.md, memory/project_built.md, memory/user_profile.md (beginner trader)

### Community 44 - "Community 44"
Cohesion: 0.5
Nodes (4): main(), Daily Kite Connect token generator.  Run this ONCE each morning before the marke, Update or insert a key=value line in .env., _update_env()

### Community 45 - "Community 45"
Cohesion: 0.5
Nodes (3): get_first_candle_levels(), First Candle Anchor — extracts the high and low of the 9:15–9:20 candle.  What i, Return (high, low) of the 9:15–9:20 candle for today.      Args:         df: OHL

### Community 46 - "Community 46"
Cohesion: 0.5
Nodes (3): calculate_quantity(), Position Sizer — calculates how many shares to buy.  This is one of the most imp, Calculate the number of shares to trade using fixed fractional sizing.      Args

### Community 47 - "Community 47"
Cohesion: 0.83
Nodes (3): main(), nifty_direction_at_10am(), simulate_day()

### Community 48 - "Community 48"
Cohesion: 0.67
Nodes (3): main(), _parse_args(), Day Replay CLI — replay a past trading day through all strategies.  Usage exampl

### Community 49 - "Community 49"
Cohesion: 0.83
Nodes (3): main(), run_single(), run_walk_forward()

### Community 50 - "Community 50"
Cohesion: 0.5
Nodes (4): indicators/macd.py (MACD 12,26,9), indicators/rsi.py (RSI 14), strategies/rsi_macd_combo.py, RSI+MACD Strategy Notes

### Community 51 - "Community 51"
Cohesion: 0.5
Nodes (4): broker/base_broker.py (BaseBroker interface), broker/paper_broker.py (PaperBroker), Intraday Short Selling (SELL opens short), Zerodha Brokerage Cost Simulation (6 components)

### Community 52 - "Community 52"
Cohesion: 0.67
Nodes (1): Launch the TreadingBot Streamlit dashboard.  Usage:     python scripts/run_dashb

### Community 53 - "Community 53"
Cohesion: 0.67
Nodes (1): TreadingBot — main entry point for automated paper trading.  What this does:   S

### Community 54 - "Community 54"
Cohesion: 0.67
Nodes (1): Settings page — view and understand the bot's configuration.  This page shows al

### Community 55 - "Community 55"
Cohesion: 0.67
Nodes (1): Day Replay page — replay any past trading day candle-by-candle.  What is day rep

### Community 56 - "Community 56"
Cohesion: 0.67
Nodes (3): analysis/fundamental_filter.py (sector-relative 0-5 scoring), analysis/fundamental_selector.py, Fundamentals-Ranked Bot Watchlist

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (1): Strategy configuration registry.  Each strategy is a dict of parameters that can

### Community 58 - "Community 58"
Cohesion: 1.0
Nodes (1): Market, signal, catalyst, and fundamental analysis helpers.

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (1): TreadingBot Dashboard — Streamlit multi-page app.  Run with:     streamlit run d

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (2): Risk Gates (ATR-based, 1% per trade, 3% daily halt), Rationale: ATR-based stop-loss outside normal noise

### Community 61 - "Community 61"
Cohesion: 1.0
Nodes (2): backtesting/engine.py (tiered intervals, no-lookahead), Walk-Forward Backtesting (anti-overfitting)

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (2): notifications/telegram_notifier.py, Once-Per-Day Notification Dedup (_once_today)

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (2): NIFTY Divergence Threshold: >=1.0% move required, Rationale: NIFTY >=1% threshold (below is noise, not divergence)

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (1): Compute the indicator values and append them as new columns.          Args:

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (1): Return the signal for the most recent candle.          Returns:             +1

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (1): Profit or loss if position were closed right now.

### Community 67 - "Community 67"
Cohesion: 1.0
Nodes (1): Current market value of the position.

### Community 68 - "Community 68"
Cohesion: 1.0
Nodes (1): Place a new order.          Args:             symbol:           NSE symbol, e.g.

### Community 69 - "Community 69"
Cohesion: 1.0
Nodes (1): Cancel a pending or open order.          Returns:             True if successful

### Community 70 - "Community 70"
Cohesion: 1.0
Nodes (1): Return the current state of an order by its ID.

### Community 71 - "Community 71"
Cohesion: 1.0
Nodes (1): Return all currently open positions.

### Community 72 - "Community 72"
Cohesion: 1.0
Nodes (1): Return the Last Traded Price for a symbol.         In paper mode this reads from

### Community 73 - "Community 73"
Cohesion: 1.0
Nodes (1): Return available cash balance.

### Community 74 - "Community 74"
Cohesion: 1.0
Nodes (1): Close all open positions immediately at market price.         Called at 3:15 PM

### Community 75 - "Community 75"
Cohesion: 1.0
Nodes (1): How much you lose per share if stop-loss is hit.

### Community 76 - "Community 76"
Cohesion: 1.0
Nodes (1): How much you gain per share if target is hit.

### Community 77 - "Community 77"
Cohesion: 1.0
Nodes (1): Reward-to-risk ratio.         A ratio of 2.0 means you stand to gain ₹2 for ever

### Community 78 - "Community 78"
Cohesion: 1.0
Nodes (1): Total money at risk on this trade = risk_per_share × quantity.

### Community 79 - "Community 79"
Cohesion: 1.0
Nodes (1): Analyse the latest candle data and return a trading signal.          Args:

### Community 80 - "Community 80"
Cohesion: 1.0
Nodes (1): CSS colour for a score badge — matches analysis/signal_scorer.py ScoreResult.col

### Community 81 - "Community 81"
Cohesion: 1.0
Nodes (1): Short text label for the score tier.

### Community 82 - "Community 82"
Cohesion: 1.0
Nodes (1): pandas >=2.2.3

### Community 83 - "Community 83"
Cohesion: 1.0
Nodes (1): numpy >=2.1.0

### Community 84 - "Community 84"
Cohesion: 1.0
Nodes (1): plotly 5.20.0

### Community 85 - "Community 85"
Cohesion: 1.0
Nodes (1): python-dotenv 1.0.1

### Community 86 - "Community 86"
Cohesion: 1.0
Nodes (1): loguru 0.7.2

### Community 87 - "Community 87"
Cohesion: 1.0
Nodes (1): pytest 8.1.1

### Community 88 - "Community 88"
Cohesion: 1.0
Nodes (1): config/settings.py

### Community 89 - "Community 89"
Cohesion: 1.0
Nodes (1): config/strategies.py

### Community 90 - "Community 90"
Cohesion: 1.0
Nodes (1): data/instruments.py (KITE_TO_YF map)

### Community 91 - "Community 91"
Cohesion: 1.0
Nodes (1): data/fundamentals.py

### Community 92 - "Community 92"
Cohesion: 1.0
Nodes (1): data/news_catalyst.py

### Community 93 - "Community 93"
Cohesion: 1.0
Nodes (1): data/kite_auth.py

### Community 94 - "Community 94"
Cohesion: 1.0
Nodes (1): data/nse_holidays.py

### Community 95 - "Community 95"
Cohesion: 1.0
Nodes (1): strategies/gap_and_go.py

### Community 96 - "Community 96"
Cohesion: 1.0
Nodes (1): strategies/bb_mean_reversion.py

### Community 97 - "Community 97"
Cohesion: 1.0
Nodes (1): broker/kite_broker.py (deferred)

### Community 98 - "Community 98"
Cohesion: 1.0
Nodes (1): execution/portfolio.py

### Community 99 - "Community 99"
Cohesion: 1.0
Nodes (1): backtesting/performance.py (Sharpe, drawdown, win rate)

### Community 100 - "Community 100"
Cohesion: 1.0
Nodes (1): backtesting/report.py (Plotly HTML report)

### Community 101 - "Community 101"
Cohesion: 1.0
Nodes (1): scheduler/bot_controller.py (BackgroundScheduler singleton)

### Community 102 - "Community 102"
Cohesion: 1.0
Nodes (1): analysis/stock_scanner.py

### Community 103 - "Community 103"
Cohesion: 1.0
Nodes (1): analysis/market_overview.py

### Community 104 - "Community 104"
Cohesion: 1.0
Nodes (1): analysis/catalyst_scanner.py

### Community 105 - "Community 105"
Cohesion: 1.0
Nodes (1): scripts/run_backtest.py

### Community 106 - "Community 106"
Cohesion: 1.0
Nodes (1): Rationale: VIX direction checks NIFTY intraday (VIX=fear not direction)

### Community 107 - "Community 107"
Cohesion: 1.0
Nodes (1): User: Beginner Trader (paper-first, no prior market knowledge)

### Community 108 - "Community 108"
Cohesion: 1.0
Nodes (1): AdaptiveMode (NORMAL/DEFENSIVE/HALTED)

### Community 109 - "Community 109"
Cohesion: 1.0
Nodes (1): Market Regime (Trending/Ranging/Volatile)

### Community 110 - "Community 110"
Cohesion: 1.0
Nodes (1): Stock Divergence Cutoff: <0.3% stock move

### Community 111 - "Community 111"
Cohesion: 1.0
Nodes (1): Live Bot Error: yfinance returns None (rate-limited)

### Community 112 - "Community 112"
Cohesion: 1.0
Nodes (1): Live Bot Error: Capital not synced between symbols in cycle

### Community 113 - "Community 113"
Cohesion: 1.0
Nodes (1): CLAUDE.md — TreadingBot Project Instructions

### Community 114 - "Community 114"
Cohesion: 1.0
Nodes (1): FilterContext — immutable signal evaluation context

### Community 115 - "Community 115"
Cohesion: 1.0
Nodes (1): FilterResult — verdict dataclass (PASS/REJECT/MODIFY)

### Community 116 - "Community 116"
Cohesion: 1.0
Nodes (1): Pipeline Audit Log — one structured log line per signal

### Community 117 - "Community 117"
Cohesion: 1.0
Nodes (1): Paper Trading Mode (TRADING_MODE=paper)

### Community 118 - "Community 118"
Cohesion: 1.0
Nodes (1): NIFTY50 Cash Segment Universe

### Community 119 - "Community 119"
Cohesion: 1.0
Nodes (1): Zerodha Kite Connect Broker

### Community 120 - "Community 120"
Cohesion: 1.0
Nodes (1): Rationale: ta library not pandas-ta (Python 3.14 numba incompatibility)

### Community 121 - "Community 121"
Cohesion: 1.0
Nodes (1): Rationale: BackgroundScheduler avoids freezing Streamlit

## Knowledge Gaps
- **292 isolated node(s):** `VWAP — Volume Weighted Average Price.  What is VWAP and why does it matter?   VW`, `Compute VWAP for each candle, resetting at the start of each trading day.      A`, `Return VWAP directional bias for the latest candle.      Returns:          1  —`, `True if the DataFrame contains daily (not intraday) candles.      Daily candles`, `First Candle Anchor — extracts the high and low of the 9:15–9:20 candle.  What i` (+287 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 57`** (2 nodes): `strategies.py`, `Strategy configuration registry.  Each strategy is a dict of parameters that can`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (2 nodes): `__init__.py`, `Market, signal, catalyst, and fundamental analysis helpers.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (2 nodes): `app.py`, `TreadingBot Dashboard — Streamlit multi-page app.  Run with:     streamlit run d`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (2 nodes): `Risk Gates (ATR-based, 1% per trade, 3% daily halt)`, `Rationale: ATR-based stop-loss outside normal noise`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 61`** (2 nodes): `backtesting/engine.py (tiered intervals, no-lookahead)`, `Walk-Forward Backtesting (anti-overfitting)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (2 nodes): `notifications/telegram_notifier.py`, `Once-Per-Day Notification Dedup (_once_today)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (2 nodes): `NIFTY Divergence Threshold: >=1.0% move required`, `Rationale: NIFTY >=1% threshold (below is noise, not divergence)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (1 nodes): `Compute the indicator values and append them as new columns.          Args:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (1 nodes): `Return the signal for the most recent candle.          Returns:             +1`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (1 nodes): `Profit or loss if position were closed right now.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 67`** (1 nodes): `Current market value of the position.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 68`** (1 nodes): `Place a new order.          Args:             symbol:           NSE symbol, e.g.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 69`** (1 nodes): `Cancel a pending or open order.          Returns:             True if successful`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 70`** (1 nodes): `Return the current state of an order by its ID.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 71`** (1 nodes): `Return all currently open positions.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 72`** (1 nodes): `Return the Last Traded Price for a symbol.         In paper mode this reads from`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 73`** (1 nodes): `Return available cash balance.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 74`** (1 nodes): `Close all open positions immediately at market price.         Called at 3:15 PM`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 75`** (1 nodes): `How much you lose per share if stop-loss is hit.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 76`** (1 nodes): `How much you gain per share if target is hit.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 77`** (1 nodes): `Reward-to-risk ratio.         A ratio of 2.0 means you stand to gain ₹2 for ever`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 78`** (1 nodes): `Total money at risk on this trade = risk_per_share × quantity.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 79`** (1 nodes): `Analyse the latest candle data and return a trading signal.          Args:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 80`** (1 nodes): `CSS colour for a score badge — matches analysis/signal_scorer.py ScoreResult.col`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 81`** (1 nodes): `Short text label for the score tier.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 82`** (1 nodes): `pandas >=2.2.3`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 83`** (1 nodes): `numpy >=2.1.0`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 84`** (1 nodes): `plotly 5.20.0`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 85`** (1 nodes): `python-dotenv 1.0.1`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 86`** (1 nodes): `loguru 0.7.2`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 87`** (1 nodes): `pytest 8.1.1`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 88`** (1 nodes): `config/settings.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 89`** (1 nodes): `config/strategies.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 90`** (1 nodes): `data/instruments.py (KITE_TO_YF map)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 91`** (1 nodes): `data/fundamentals.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 92`** (1 nodes): `data/news_catalyst.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 93`** (1 nodes): `data/kite_auth.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 94`** (1 nodes): `data/nse_holidays.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 95`** (1 nodes): `strategies/gap_and_go.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 96`** (1 nodes): `strategies/bb_mean_reversion.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 97`** (1 nodes): `broker/kite_broker.py (deferred)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 98`** (1 nodes): `execution/portfolio.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 99`** (1 nodes): `backtesting/performance.py (Sharpe, drawdown, win rate)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 100`** (1 nodes): `backtesting/report.py (Plotly HTML report)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 101`** (1 nodes): `scheduler/bot_controller.py (BackgroundScheduler singleton)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 102`** (1 nodes): `analysis/stock_scanner.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 103`** (1 nodes): `analysis/market_overview.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 104`** (1 nodes): `analysis/catalyst_scanner.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 105`** (1 nodes): `scripts/run_backtest.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 106`** (1 nodes): `Rationale: VIX direction checks NIFTY intraday (VIX=fear not direction)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 107`** (1 nodes): `User: Beginner Trader (paper-first, no prior market knowledge)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 108`** (1 nodes): `AdaptiveMode (NORMAL/DEFENSIVE/HALTED)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 109`** (1 nodes): `Market Regime (Trending/Ranging/Volatile)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 110`** (1 nodes): `Stock Divergence Cutoff: <0.3% stock move`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 111`** (1 nodes): `Live Bot Error: yfinance returns None (rate-limited)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 112`** (1 nodes): `Live Bot Error: Capital not synced between symbols in cycle`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 113`** (1 nodes): `CLAUDE.md — TreadingBot Project Instructions`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 114`** (1 nodes): `FilterContext — immutable signal evaluation context`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 115`** (1 nodes): `FilterResult — verdict dataclass (PASS/REJECT/MODIFY)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 116`** (1 nodes): `Pipeline Audit Log — one structured log line per signal`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 117`** (1 nodes): `Paper Trading Mode (TRADING_MODE=paper)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 118`** (1 nodes): `NIFTY50 Cash Segment Universe`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 119`** (1 nodes): `Zerodha Kite Connect Broker`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 120`** (1 nodes): `Rationale: ta library not pandas-ta (Python 3.14 numba incompatibility)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 121`** (1 nodes): `Rationale: BackgroundScheduler avoids freezing Streamlit`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Action` connect `Strategy Core & Signal Types` to `Broker Abstraction Layer`, `Technical Indicators`, `Backtesting Engine`, `Fundamental Analysis`, `Adaptive Strategy Config`, `Strategy Unit Tests`, `Risk Manager Tests`, `Community 24`?**
  _High betweenness centrality (0.168) - this node is a cross-community bridge._
- **Why does `DailyWatchlist` connect `Strategy Core & Signal Types` to `Fundamental Analysis`?**
  _High betweenness centrality (0.101) - this node is a cross-community bridge._
- **Why does `TradeLogger` connect `Broker Abstraction Layer` to `Strategy Core & Signal Types`, `Community 42`, `Strategy Degradation Monitor`, `Strategy Comparison Dashboard`, `Trade Logging & Database`, `Community 55`, `Community 26`?**
  _High betweenness centrality (0.101) - this node is a cross-community bridge._
- **Are the 232 inferred relationships involving `Action` (e.g. with `RiskState` and `RiskDecision`) actually correct?**
  _`Action` has 232 INFERRED edges - model-reasoned connections that need verification._
- **Are the 176 inferred relationships involving `Signal` (e.g. with `RiskState` and `RiskDecision`) actually correct?**
  _`Signal` has 176 INFERRED edges - model-reasoned connections that need verification._
- **Are the 81 inferred relationships involving `PaperBroker` (e.g. with `BaseBroker` and `Order`) actually correct?**
  _`PaperBroker` has 81 INFERRED edges - model-reasoned connections that need verification._
- **Are the 85 inferred relationships involving `TradeLogger` (e.g. with `APScheduler Job Runner — automates the trading day in paper mode.  What this doe` and `Called from the KiteTicker WebSocket thread on every live tick.      Checks SL/t`) actually correct?**
  _`TradeLogger` has 85 INFERRED edges - model-reasoned connections that need verification._