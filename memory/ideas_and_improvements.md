# Ideas & Improvements Log

Format: `Impact H/M/L | Effort H/M/L | Phase`
Status: Idea | In Progress | DONE | DROPPED(reason)

---

| # | Title | Impact | Effort | Phase | Status |
|---|---|---|---|---|---|
| 1 | VWAP as institutional trend filter | H | M | Ph2 enh | DONE |
| 2 | NSE holiday calendar check in scheduler | H | L | Ph6 | DONE |
| 3 | Supertrend indicator (replace 50 EMA filter) | M | M | Ph2 enh | DONE |
| 4 | Walk-forward backtesting (anti-overfitting) | H | H | Ph4 enh | DONE |
| 5 | Telegram/WhatsApp trade notifications | H | M | Ph6 enh | DONE |
| 6 | GTT orders on Kite (stops survive crashes) | H | M | Ph6 | Idea |
| 7 | Strategy degradation auto-detection | M | M | Ph7 | DONE |
| 8 | NSE F&O / PCR for market sentiment | M | H | Future | Idea |
| 9 | Drawdown shading on equity curve chart | M | L | Ph5 enh | DONE |
| 10 | Paper broker partial fill simulation | L | M | Ph3 enh | DONE |
| 11 | Fix ORB multi-day opening range bug | H | L | Ph6 bug | DONE |
| 12 | "No ORB after 11 AM" rule | M | L | Ph2 enh | DONE |
| 13 | MACD histogram acceleration filter (RSI+MACD) | M | L | Ph2 enh | DONE |
| 14 | yfinance retry with backoff on None response | M | L | Ph6 enh | DONE |
| 15 | Bollinger Band Mean Reversion strategy | M | M | Ph2 enh | DONE |
| 16 | Gap & Go morning gap strategy | M | M | Ph2 enh | DONE |
| 17 | VWAP Retest Entry strategy | H | M | Ph2 enh | Idea |
| 18 | Sector rotation / market breadth signal bias | M | M | Ph5 enh | Idea |
| 19 | Trailing stop after 1× ATR profit | H | M | Ph3 enh | DONE |
| 20 | Time-based force-exit at 2:00 PM | M | L | Ph2 enh | DONE |
| 21 | Volatility-scaled position sizing | M | M | Ph2 enh | Idea |
| 22 | Trade Journal dashboard view | H | M | Ph5 enh | DONE |
| 23 | Strategy head-to-head live comparison panel | H | L | Ph5 enh | DONE |
| 24 | Signal confidence score (visual, 0–5) | M | L | Ph5 enh | DONE |
| 25 | Daily P&L heatmap (calendar view) | M | L | Ph5 enh | DONE |
| 26 | Market regime detector (Trending/Ranging/Volatile) | H | M | Ph7 | DONE |
| 27 | Per-strategy auto-disable on win rate drop | M | L | Ph7 | Idea |
| 28 | Best entry time analysis from paper trade data | M | L | Ph7 | Idea |
| 29 | Swing trading mode (overnight holds for BB Mean Reversion) | M | H | Future | Idea |
| 30 | Realistic slippage 0.2%/side in backtest engine | H | L | Ph4 enh | DONE |
| 31 | First 5-min candle (9:15–9:20) anchor filter on EMA Crossover | H | M | Ph2 enh | DONE |
| 32 | RSI period 14→6 for intraday sensitivity (5m charts) | M | L | Ph2 enh | DONE |
| 33 | India VIX as market fear filter (VIX>20 suppress BUY, >25 all) | H | M | Ph6 enh | DONE |
| 34 | ORB window widened 15→30 min (9:15–9:45 to avoid open chaos) | M | L | Ph2 enh | DONE |
| 35 | Open trade recovery on restart (restore positions from DB) | H | M | Ph6 enh | DONE |
| 36 | Risk state persistence across restarts (daily_pnl + consecutive_losses from DB) | H | M | Ph6 enh | DONE |
| 37 | Live P&L in Today's Trades dashboard table (LTP + unrealised P&L) | M | M | Ph5 enh | DONE |
| 38 | Historical trade analytics with date range filter + CSV export | M | M | Ph5 enh | DONE |
| 39 | Single per-day log file (append on restart, merge old timestamped files) | M | L | Ph6 enh | DONE |
| 40 | EMA trend alignment filter in rsi_macd_combo (block counter-trend signals) | H | L | Ph2 enh | DONE |
| 41 | VWAP direction filter in rsi_macd_combo (only short above VWAP) | H | L | Ph2 enh | DONE |
| 42 | RSI oversold gate on SELL signals (skip if RSI < 40 — already oversold) | H | L | Ph2 enh | DONE |
| 43 | Minimum SL distance (max(1.5×ATR, 0.75% of price)) to prevent noise-hits | M | L | Ph2 enh | DONE |
| 44 | AdaptiveStrategyManager — runtime param adjustment via VIX/regime/losses/time | H | H | Ph6 enh | DONE |
| 45 | VIX direction bias — suppress correct side based on NIFTY intraday direction | H | M | Ph6 enh | DONE |
| 46 | VWAP Bounce strategy (5th strategy — VWAP cross confirmation entry) | H | M | Ph2 enh | DONE |
| 47 | Intraday direction detector (analysis/market_direction.py) for VIX logic | M | M | Ph6 enh | DONE |
| 48 | 15-day backtest script (scripts/backtest_15days.py) — multi-symbol, direction-aware | M | M | Ph4 enh | DONE |
| 49 | NEUTRAL day sit-out: when direction unclear, skip both sides entirely | H | L | Ph6 enh | DONE |
| 50 | Early reversal detection — exit short quickly if market V-reverses within 30 min | M | H | Future | DONE |
| 51 | Sector correlation filter — only trade stocks moving WITH NIFTY on up days | M | M | Future | Idea |
| 52 | Per-day VIX history in backtest (fetch historical ^INDIAVIX for each day) | M | M | Ph4 enh | Idea |
| 53 | Claude AI fundamental synthesis (FundamentalAnalyst) — position_scale from P/E + debt + margins + earnings growth | H | M | Future | DONE |
| 54 | Kite login environment preflight (detect wrong venv Python / missing deps) | M | L | Ph6b ops | Idea |
| 55 | Fundamentals-ranked bot watchlist — select trade universe from sector-relative fundamental scores before signal scan | H | M | Ph6 enh | DONE |
| 56 | Scheduler watchlist module refactor — keep job_runner focused on timed jobs, move universe selection to scheduler/watchlist.py | M | L | Structure | DONE |

---

## Detail notes (non-obvious ideas only)

**#1 VWAP**: `vwap = cumsum(close×vol) / cumsum(vol)` reset at 9:15 AM. Above VWAP = institutional buy bias. More dynamic than 50 EMA. Add as additional filter to EMA Crossover + ORB.

**#4 Walk-forward**: Split data into rolling train/test windows (Jan–Jun train, Jul–Sep test, etc). Prevents overfitting to one market regime. Gold standard before going live.

**#6 GTT orders**: After entry, place OCO GTT on Kite (stop + target). Survives bot restart/crash. Critical for live mode safety. `kite.place_gtt()` API.

**#7 Strategy degradation**: If rolling 20-trade win rate drops >15% below backtest baseline → alert + optional auto-disable. Detects regime change.

**#11 ORB multi-day range bug**: `_get_opening_range()` in `indicators/orb.py` uses entire visible slice across all days. Fix: add `(df.index.date == today)` to the orb_mask filter. This is the primary reason ORB gets 0 trades.

**#12 No ORB after 11 AM**: Late breakouts are mostly false. Add `if now_ist.time() > time(11, 0): return HOLD` at the start of ORB signal generation.

**#13 MACD acceleration filter**: Require MACD histogram to be both positive AND larger than the previous bar for 2 consecutive bars before firing. Reduces noise signals that cause RSI+MACD 28% win rate on 1h.

**#14 yfinance retry**: When `ticker.history()` returns None (rate-limited), retry once after 2 seconds before returning None. Reduces missed signals during parallel fetches.

**#15 Bollinger Band Mean Reversion**: Buy when price touches lower band + RSI < 35, targeting the mean (middle band). Adds counter-trend diversity — the main intraday strategies are mostly momentum, so they can fail together in choppy markets.
  ⚠️ Backtested RELIANCE Jul–Dec 2025: win rate 47.8%, profit factor 0.70, −2% return. Root cause: EOD square-off cuts trades before the middle-band target is reached — this is a multi-day reversion strategy, not intraday. Needs swing trading mode (overnight holds) to work properly. Deferred to future phase.

**#16 Gap & Go**: Enter stocks that open >0.5% above previous close with a volume surge in the first 15 minutes. Reuses ORB infrastructure. Classic intraday pattern, strong on NIFTY50 large caps.

**#17 VWAP Retest Entry**: Price breaks above VWAP, pulls back to touch it, then bounces — enter on the bounce with tight stop below VWAP. Higher quality entries than current breakout-only VWAP filter; reduces false positives.

**#18 Sector rotation bias**: Use `market_overview.py` breadth data (advance/decline ratio) to bias signals. If NIFTY50 breadth >70% bullish → long-only mode. If <30% → suppress all signals or short-only. Overlay on existing strategies, not a new one.

**#19 Trailing stop after 1× ATR profit**: Once trade is up 1× ATR, move stop to breakeven. Once up 2× ATR, trail stop at 1× ATR below price. Locks in profit on big movers without cutting winners short prematurely.

**#20 Time-based force-exit at 2:00 PM**: Exit any open trade not yet at SL or target by 2:00 PM. Avoids holding through low-liquidity afternoon. Especially useful for ORB trades which are morning-only signals.

**#21 Volatility-scaled position sizing**: On days where NIFTY ATR > 1.5× its 20-day average, reduce qty by 25–50%. Prevents oversizing on chaotic days where SL is more likely to be hit.

**#22 Trade Journal view**: New dashboard page. Each closed paper trade shown with: strategy that fired, entry time, signal confidence indicators at entry, NIFTY trend at the time, and outcome. Readable like a logbook. Single biggest confidence builder before going live.

**#23 Strategy head-to-head panel**: Dashboard panel showing live win rate, avg P&L per trade, and Sharpe for strategies side by side — updated from actual paper trade data in real time. No need to run separate backtests to compare.

**#24 Signal confidence score**: Each signal on the Signals page shows a score 0–5: one point each for trend aligned, volume confirmed, VWAP confirmed, RSI not extreme, MACD direction matches. Visual bar or colour indicator. No logic changes — pure visibility.

**#25 Daily P&L heatmap**: Calendar heatmap (GitHub-style green/red squares) on the dashboard. Immediately reveals if losses cluster on specific days, post-gap days, or at start/end of week. Hard to spot from equity curve alone.

**#26 Market regime detector**: Classify each trading day as Trending / Ranging / Volatile using NIFTY's ADX + daily ATR. Run momentum strategies (EMA, ORB) only on Trending days. Suppress all signals on Volatile days. Highest-leverage single improvement for reducing bad-day losses.

**#27 Per-strategy auto-disable**: Extend existing degradation detector (#7) to actually disable a strategy (not just alert) when its rolling 10-trade win rate drops below 35%. Prevents continuing to trade a broken strategy during a regime change.

**#28 Best entry time analysis**: Analyse paper trade data to find which hours of day each strategy wins vs loses. If EMA signals before 10:30 AM show <35% win rate, add a time filter. Turns paper trading data into concrete rule refinements.

**#44 Adaptive mode**: config/adaptive.py — `AdaptiveMode` enum (NORMAL/DEFENSIVE/HALTED). Runs every 60s from signal_check(). Checks VIX, regime (ADX), consecutive_losses, day_pnl_pct, time of day. Updates cfg.STRATEGY_CONFIGS["rsi_macd_combo"] in-place. Strategies call _reload_params() at start of generate_signal(). Dashboard shows live mode + reason + 5 metrics.

**#45 VIX direction bias**: data/india_vix.py now returns skip_sells in addition to skip_buys. _classify() calls analysis/market_direction.py to get NIFTY intraday UP/DOWN/NEUTRAL. RiskManager checks both skip_sells (block SELL) and skip_buys (block BUY). Key lesson from 2026-04-02: VIX=25.4 + NIFTY UP → should block SHORTS, not LONGS.

**#46 VWAP Bounce**: strategies/vwap_bounce.py. Entry: price cross of VWAP (was below, now above for BUY). Filters: EMA9>EMA21, RSI(6) 35-65, volume >= 1.2× avg, time 9:45-13:30. Uses df.index[-1] for time check (not datetime.now — so backtests work). DEFENSIVE rsi_exit=85 (not 72 — lower rsi_exit creates MORE shorts, not fewer).

**#49 NEUTRAL sit-out**: Direction check returns 4-tuple (skip_sells, skip_buys, eod_chg, bias_label). NEUT means both True = no trades at all. Previous default was "trade both sides on NEUT" which caused all losses in the 15-day test during a macro sell-off.

**#50 Early reversal detection** ✅ DONE: `OrderManager.check_reversal_exit(symbol, price, vwap)`.
- SELL: price crosses back above VWAP within 30 min → exit. BUY: price falls below VWAP within 30 min → exit.
- Window: `_REVERSAL_WINDOW_SECS = 1800` (execution/order_manager.py).
- Called in signal_check() BEFORE check_exits() — reversal takes priority over SL/target.
- NaN/zero VWAP or window expired → returns None (no exit). 9 tests in tests/test_reversal_exit.py.

**#51 Sector correlation filter**: On NIFTY UP days, some stocks still decline (sector rotation). Before entering VWAP bounce BUY, check stock's last 10 candles are mostly green (>60% green). Filters out laggard stocks that don't participate in the day's rally.

**#52 Historical VIX in backtest**: The 15-day backtest uses no VIX data — it tests direction logic only. Adding historical ^INDIAVIX per day would let the backtest simulate the full VIX suppression logic too. Fetch daily VIX close from yfinance at start, use it in simulate_day().

**#54 Kite login preflight**: `scripts/kite_login.py` can fail with confusing import errors when `.venv/bin/python` points at a different Python than `.venv/bin/pip` installed packages for. Add a small startup diagnostic that prints the interpreter, Python version, and the exact `pip install -r requirements.txt` / venv recreation command when imports fail.

**#55 Fundamentals-ranked bot watchlist** ✅ DONE: `analysis/fundamental_selector.py` ranks the NIFTY50 with existing `score_fundamentals()`, avoids earnings-blackout names when alternatives exist, caps sector concentration, and fails open to the static NIFTY50 order when fundamentals data is unavailable. `scheduler/job_runner.py` now uses that selector at setup and pre-market refresh, then passes a per-symbol `FundamentalJudgment` into `RiskManager.evaluate()` so position sizing reflects company quality.

**#56 Scheduler watchlist refactor** ✅ DONE: `scheduler/watchlist.py` now owns `DailyWatchlist`, static fallback selection, fundamentals-ranked daily selection, and cached fundamental judgment lookup. `scheduler/job_runner.py` remains the timed-job orchestrator. Added `tests/test_scheduler_watchlist.py`. Full suite after refactor: 272 passed, 1 Loguru deprecation warning.

---

## Done
*(move entries here when implemented)*

## Dropped
*(move entries here with reason)*
