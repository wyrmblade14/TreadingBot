---
name: Technical Lessons Learned
description: Key technical decisions, gotchas, and non-obvious choices made during TreadingBot development
type: project
---

## Library Compatibility
- pandas-ta requires numba, numba does NOT support Python 3.14 (as of March 2026)
- Use `ta` library instead: same API surface, no C/Fortran extensions
  - EMA: ta.trend.EMAIndicator(close, window=N).ema_indicator()
  - RSI: ta.momentum.RSIIndicator(close, window=14).rsi()
  - MACD: ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
    - .macd() = MACD line, .macd_signal() = signal line, .macd_diff() = histogram
  - ATR: ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()

## Pandas Copy-on-Write
- The `ta` library internally assigns to sliced DataFrames, triggering FutureWarnings in pandas 2.x
- Fix: compute all new columns as a pd.DataFrame first, then use pd.concat([result, new_cols], axis=1)
- Never do: result["col"] = ta.something()  ← triggers CoW warning
- Always do: new_cols = pd.DataFrame({...}); return pd.concat([result, new_cols], axis=1)

## ORB Strategy Target Edge Case
- When current price has already moved beyond the projected ORB target at time of signal,
  target would equal entry_price, making is_valid() return False
- Fix: target = max(orb_projected_target, entry_price + 2×ATR) for BUY
       target = min(orb_projected_target, entry_price - 2×ATR) for SELL

## Risk Manager Mocking in Tests
- RiskManager uses datetime.now(IST) internally for time-based rules
- Must mock as: `with patch("risk.risk_manager.datetime") as mock_dt:`
  then set `mock_dt.now.return_value = datetime.fromisoformat("2024-01-02 09:25:00+05:30")`
- Test time must be AFTER 9:20 AM (blackout) and BEFORE 2:30 PM for valid signals

## Zerodha Brokerage Simulation
- All 6 cost components must be simulated for accurate paper P&L:
  1. ₹20 flat brokerage (both buy and sell)
  2. STT 0.025% on sell-side turnover (intraday equity)
  3. Exchange transaction charges 0.00325% on total turnover
  4. GST 18% on (brokerage + exchange charges)
  5. SEBI charges ₹10 per ₹1 crore of turnover
  6. Stamp duty 0.003% on buy-side turnover
- Without these, paper P&L is optimistic by ~0.1–0.2% per round trip

## ATR-Based Stop-Loss
- ATR (Average True Range) = average of max(H-L, |H-prev_close|, |L-prev_close|) over 14 periods
- Stop-loss at entry - 1.5×ATR sits outside "normal" price noise
- For NIFTY50 stocks on 5-min candles, ATR is typically 0.2–0.5% of price
- Fallback when insufficient data: 0.5% of current price

## SQLAlchemy ORM for Trade Log
- DeclarativeBase (new style, SQLAlchemy 2.x) used instead of deprecated declarative_base()
- Session pattern: `with SessionLocal() as session:` (context manager auto-closes)
- Trade log is append-only; never update/delete historical records
- SQLAlchemy 2.0.29 is incompatible with Python 3.14 — it crashes on __static_attributes__ and
  __firstlineno__ (new Python 3.14 class attributes). Must use SQLAlchemy >= 2.0.36.

## Indian Market Specific
- NIFTY50 stocks use `.NS` suffix in yfinance but no suffix in Kite Connect
- Pre-market (9:00–9:15) sets the opening price; first 5 min (9:15–9:20) are chaotic
- ORB window is 9:15–9:45 AM (widened from 9:30); signals only valid after 9:45 AM and before 2:30 PM
- All timestamps must be IST (pytz Asia/Kolkata) — never naive datetimes
- Market days: Mon–Fri except NSE holidays (handled by data/nse_holidays.py)

## yfinance Compatibility
- yfinance 0.2.37 broke in early 2026 — Yahoo Finance changed their API endpoint.
  Symptom: all fetches return empty data or "Expecting value: line 1 column 1 (char 0)".
  Fix: upgrade to yfinance >= 0.2.54 (1.2.0 confirmed working as of March 2026).
- yfinance 1.2.0 introduces new dependencies: curl_cffi, websockets, platformdirs.
- Multi-ticker yf.download() still returns MultiIndex DataFrame with (metric, ticker) columns —
  access as data["Close"]["RELIANCE.NS"] (unchanged from 0.2.x).
- period="1d" with interval="5m" returns today's live intraday data during market hours,
  building up candle-by-candle. At start of day (9:15 AM) returns previous day until
  first candle is published. Candle count grows from ~1 → 75 over the trading session.

## Python 3.14 on Windows — venv Pitfalls
- venvs are NOT portable across operating systems. A venv created on Mac (with Homebrew Python)
  has Unix shebangs (/opt/homebrew/...) and cannot run on Windows.
- On Windows, Python installs scripts in venv/Scripts/ (not venv/bin/).
- Git Bash on Windows cannot execute .exe files via path (venv/Scripts/streamlit fails with
  exit code 127). Use python -m streamlit instead, or call the .exe directly:
  venv/Scripts/python.exe -m streamlit run dashboard/app.py
- pandas 2.2.1 and numpy 1.26.4 have no pre-built wheels for Python 3.14 on Windows —
  they require a C compiler (Visual Studio). Pin to pandas>=2.2.3, numpy>=2.1.0 which do
  have cp314 wheels.
- streamlit 1.33.0 requires numpy<2, incompatible with Python 3.14 wheels. Use streamlit>=1.35.0.

## Scheduler / APScheduler
- open_symbols in OrderManager is a @property (returns list), NOT a method.
  Always use _order_mgr.open_symbols (no parentheses).
  Calling _order_mgr.open_symbols() raises: TypeError: 'list' object is not callable.
- RiskManager.new_day(capital) requires the current cash balance as argument.
  Always fetch from broker first: capital = _broker.get_summary().get("cash", VIRTUAL_CAPITAL)
  then call _risk_mgr.new_day(capital=capital).
  Calling new_day() without capital raises: TypeError: missing 1 required positional argument.
- Use BackgroundScheduler (not BlockingScheduler) when running alongside Streamlit —
  BlockingScheduler freezes the main thread and Streamlit stops responding.

## Reward:Risk Float Precision
- Signal.reward_risk_ratio can compute as 1.9999999... due to float arithmetic,
  displaying as "2.00x" but failing the check `< 2.0`.
  Fix: use `round(signal.reward_risk_ratio, 2) < MIN_REWARD_RISK_RATIO` in risk_manager.py.

## Windows Task Scheduler for Bot Auto-Start
- Bot auto-starts at 8:55 AM IST Mon–Fri via Windows Task Scheduler (task path: \TreadingBot\).
- Uses venv/Scripts/python.exe directly (not the streamlit/python wrapper scripts).
- Bot self-terminates at 15:35 IST via auto_shutdown() job — no need to kill manually.
- NSE holidays are handled inside the bot (_is_market_day() check) — scheduler fires but
  bot exits cleanly with no trades on holidays.
- Manage with PowerShell: Get-ScheduledTask / Disable-ScheduledTask / Unregister-ScheduledTask
  -TaskPath '\TreadingBot\' -TaskName 'TreadingBot'

## VIX Direction Bias (learned 2026-04-02)
- India VIX > 22 does NOT simply mean "suppress BUYs." High VIX means fear, not direction.
- On 2026-04-02: VIX=25.4, NIFTY +1.42% — suppressing BUYs was dead wrong, shorts lost Rs6,348.
- Correct logic: VIX 22–30 → check intraday NIFTY direction → suppress the WRONG side:
    - NIFTY trending UP   → skip_sells=True  (fear from shorts being squeezed)
    - NIFTY trending DOWN → skip_buys=True   (fear from longs panicking out)
    - NIFTY neutral       → skip_buys=True   (conservative default)
  VIX > 30 → skip_all=True (extreme crash — no trades either side).
- Implemented in data/india_vix.py _classify() using analysis/market_direction.py.

## Intraday Direction Detection — Use Today's Candles Only
- Multi-day 5m EMAs (EMA9/EMA21 computed across 22 days) track the MACRO trend, not today's direction.
- During the March–April 2026 tariff sell-off, EMA9 < EMA21 across all 22 days — even on +1.42% days.
- Correct approach: 3 signals all from today only (no multi-day EMA):
    1. Gap pct: (today_open - prev_close) / prev_close
    2. Intra pct: (price_at_10am - today_open) / today_open
    3. Green candle fraction 9:15–10:00 (>= 60% for UP, <= 40% for DOWN)
  All 3 must agree → directional call. Any disagreement → NEUTRAL → no trades.
- NEUTRAL = sit out entirely. Don't interpret neutral as "trade both sides."

## V-Reversal Days Are Unwinnable
- 2026-04-02: NIFTY gap-down 1.4% from prev_close, fell further to -0.75% by 10AM, then V-reversed
  to close +1.42% vs open. Every 10AM direction signal correctly said DOWN — market reversed anyway.
- No intraday system can predict a V-reversal from 10AM data. The correct response is:
  direction system fires → SHORT trades → get stopped out → accept the loss as cost of doing business.
- If the 15-day test period contains a V-reversal day, that one day's loss is noise, not signal.

## Build & Ops Optimization (April 2026)
- **Docker Multi-Stage Builds**: Separating the build environment (compiler, development headers) from the runtime environment reduces the final image size and minimizes the attack surface.
- **Next.js Standalone Output**: Configuring Next.js for `output: 'standalone'` is essential for lean Docker images. It automatically traces and copies only the necessary `node_modules` into a small `server.js` bundle.
- **Docker Context and .dockerignore**: A bloated Docker build context (e.g., including `node_modules`, `venv`, or large `logs/`) is the #1 cause of slow builds. Explicitly excluding everything *except* what's needed for the build ensures fast iterative development.
- **Parallel Docker Builds**: Using `docker-compose build --parallel` is significantly faster on modern multi-core machines, as independent service images can be built simultaneously.
- **GEMINI.md for AI Context**: Keeping high-level architecture and common commands in a dedicated `GEMINI.md` file significantly improves the performance and accuracy of AI agents working in the repository.

## Kite API Rate Limiting
- Kite REST API rate limit: ~3 req/s. Fetching 12+ symbols sequentially without delay hits it.
- Symptom: "Too many requests" warning, fetch returns None for all subsequent calls.
- Fix: add time.sleep(0.4) between symbol fetches in any batch-fetch loop.
- For backtesting historical data (not live), use yfinance — no rate limit issues.
- Kite API is only needed for live/paper trading, not historical research.

## VWAP Bounce — Entry Confirmation Required
- Proximity to VWAP (within 0.3%) alone is NOT enough to enter. Price can drift near VWAP
  for many candles without bouncing, generating repeated false signals.
- Require VWAP cross confirmation: prev_candle closed on opposite side of VWAP from current candle.
  BUY: prev_close < prev_vwap AND current_close >= vwap (confirmed bounce, not approach)
  SELL: prev_close > prev_vwap AND current_close <= vwap (confirmed rejection)
- This eliminates "near VWAP but still drifting" false entries.

## VWAP Bounce Time Filter — Use Candle Timestamp, Not Wall Clock
- If generate_signal() uses datetime.now(IST) for the time filter, backtests running after
  market hours will always block all signals (current time is 15:30+, past 13:30 cutoff).
- Fix: use df.index[-1].tz_convert(IST).time() — the last candle's timestamp.
  This makes backtesting work correctly and is also more accurate in live trading
  (the candle is the event, not the wall clock at analysis time).

## Adaptive rsi_exit Parameter — Direction Matters
- In DEFENSIVE mode, setting rsi_exit=72 (lower than NORMAL's 80) backfired.
  rsi_exit triggers a SELL signal when RSI reaches that level.
  Lower rsi_exit = RSI hits 72 more often on upward-trending stocks = MORE short entries, not fewer.
- DEFENSIVE mode should have rsi_exit=85 (HIGHER than normal) to require extreme RSI before shorting.
  Lesson: think about whether a parameter change increases or decreases signal frequency before applying.

## Macro Sell-Off Periods Are Not Valid Strategy Test Windows
- March–April 2026 (US tariff war) saw NIFTY fall from ~23,500 to ~22,000 in 3 weeks.
  In this environment: EMA crossovers, MACD signals, VWAP bounces all generated false signals
  because stocks were in free-fall with constant pullback rallies that immediately continued lower.
- Backtest result for this 15-day window: -10% to -16% depending on system — ALL strategies lose.
- The correct interpretation: direction filter + NEUT sit-out reduced losses from -16% to -0.55%.
  That's the win, not profit. Capital preservation during a macro shock IS the goal.
- For meaningful strategy validation, pick normal VIX (12–18) trending periods, not crash windows.

## Risk State Must Survive Bot Restarts
- Before fix: RiskManager was initialised fresh on every bot startup with daily_pnl=0, consecutive_losses=0.
- Effect: after 3 consecutive losses (1-hour pause triggered), restarting the bot bypassed the pause.
  On 2026-04-02, the bot was restarted 13+ times, resetting the counter each time → 8 total losses.
- Fix: restore_daily_state() in RiskManager reads today's closed trades from DB on startup,
  reconstructs daily_pnl and consecutive_losses, re-applies halts if already breached.
- Call order in setup(): restore open trades FIRST, then restore risk state.

## V-Reversal Early Exit — VWAP Cross-Back Within 30 Min
- On V-reversal days, a SHORT entered correctly at 10AM (direction=DOWN) sees price rally back above VWAP.
- Waiting for the full SL costs the entire 1% risk allowance. The VWAP cross-back is an earlier, cheaper exit signal.
- Implemented in OrderManager.check_reversal_exit(symbol, price, vwap):
    - SELL: if current_price > vwap AND entry within 30 min → exit immediately
    - BUY: if current_price < vwap AND entry within 30 min → exit immediately
    - NaN/zero VWAP, no open trade, or elapsed > 30 min → return None (no exit)
- Called in signal_check() BEFORE check_exits() — reversal takes priority over SL/target.
- VWAP is computed from the same df already fetched for the symbol that cycle.
- Window is 30 min (configurable via _REVERSAL_WINDOW_SECS in order_manager.py).
- Typical saving: 40–60% of max loss on V-reversal days (exit near VWAP, not at full SL).

## Injecting Positions in Tests — Use restore_position(), Not _positions Dict
- PaperBroker._positions stores Position objects (a dataclass), not plain dicts.
- update_ltp() calls self._positions[symbol].current_price = price — fails on dict with AttributeError.
- To inject a position in tests without going through place_order():
    broker.restore_position(symbol, TransactionType.BUY/SELL, quantity=N, avg_price=P)
  This creates the correct Position object and adjusts cash.

## EMA NaN at Session Start
- At 9:40 AM with only 5 intraday candles, EMA9/EMA21 return NaN (not enough history).
- `if len(df) >= 21` check is NOT sufficient — EMA can still be NaN if all 21 rows are from today.
- Fix: always check `if math.isnan(ema9_val)` after computing EMA, return hold_signal if NaN.
- This applies to any indicator with a warm-up period (MACD, ATR, etc.).

## Fundamentals Watchlist Must Fail Open
- Fundamentals data comes from yfinance/Yahoo and can fail independently of market candle data.
- Do not stop the paper bot just because fundamentals are unavailable.
- Correct design:
  1. Rank by `analysis.fundamental_selector.select_fundamental_watchlist()`.
  2. Prefer non-blackout, higher FundamentalScore stocks with sector diversification.
  3. If ranking fails or returns nothing, fall back to the old static first-N NIFTY50 order.
  4. Let RiskManager remain the final earnings-blackout and quantity-sizing gate.
- Implemented wrapper: `scheduler/watchlist.py::select_daily_watchlist()`.

## Keep Job Runner as Orchestrator, Not Domain Logic
- `scheduler/job_runner.py` was becoming a large mixed-responsibility module.
- Boundary after April 2026 refactor:
  - `scheduler/job_runner.py`: APScheduler job functions, market-day checks, data fetch loop, strategy execution orchestration.
  - `scheduler/watchlist.py`: daily watchlist selection and fundamental judgment lookup.

## Duplicate Order Race Condition — `_last_signal_key` Must Be Locked
- Root cause (2026-04-10): `signal_check()` runs every minute via APScheduler. If one execution takes >60s (e.g. slow yfinance), a second starts while the first is still running. Both reach the dedup guard simultaneously, both see `sig_key not in _last_signal_key`, both add it and both place orders. This produced 2–3 identical orders in the same millisecond (BHARTIARTL SELL ×3 at 12:29:00.385/.388/.389).
- Fix: wrap the check+add in `_last_signal_lock = threading.Lock()` so it's atomic.
- The set itself is fine — it just needs the check+add to be one indivisible operation.
- Also added a fallback guard at the top of `OrderManager._execute_signal_locked()`: if `signal.symbol in self._open_trades`, return False immediately. Belt-and-suspenders.

## Per-Symbol Cooldown After Exit Prevents Re-Entry Loops
- Root cause (2026-04-10): AXISBANK BUY entered at 14:07, hit SL in 2 seconds, symbol removed from `_open_trades`, same EMA crossover signal still active → bot re-entered at 14:10, exited in 1 second, re-entered again at 14:11. Total: 3 identical failing trades in 4 minutes, -₹1,053.
- Fix: `OrderManager._cooldown: dict[str, tuple[datetime, Action]]` set on every `_close_trade()`. Two rules enforced in `_execute_signal_locked()`:
  1. 30-min cooldown: if elapsed < 1800s and same session → reject
  2. Direction block: if same session and `last_action != signal.action` → reject (prevents two strategies from fighting each other — one going long, one going short on the same symbol same day)
- The direction block also catches VWAP SELL + EMA BUY type conflicts that would otherwise overwrite each other.

## Regime Filter Must Be in Signal Loop, Not Just Pre-Market Log
- Root cause (2026-04-02): VIX=26 correctly blocked BUY signals on high-fear days. But the market that day went UP +1.5–2.3%. `rsi_macd_combo` fired SELL (short) signals on every stock — all of them lost because shorts on an up day always lose. The market direction + regime was computed at 09:00 and logged to Telegram, but **never consulted during signal_check()**.
- Fix: In `signal_check()` signal loop, call `get_market_direction()` and `get_current_regime()`. Suppress `Action.SELL` when `MarketDirection.UP + MarketRegime.TRENDING`. Suppress `Action.BUY` when `MarketDirection.DOWN + MarketRegime.TRENDING`. Wrapped in `try/except` — fail-open (never block trading on data error).
- Note on enum names: `MarketDirection.UP` / `MarketDirection.DOWN` (not BULLISH/BEARISH), `MarketRegime.TRENDING` (not Regime.TRENDING). Import both from their respective modules.
  - `analysis/fundamental_selector.py`: pure ranking/selection rules for fundamentals.
  - `risk/risk_manager.py`: final approval, sizing, VIX/blackout gates.
- When adding new pre-trade intelligence, put scoring/ranking in `analysis/`, scheduler glue in `scheduler/watchlist.py`, and only call it from `job_runner.py`.

## Kite Feed: Stale Symbols and pytz Datetimes
- A Kite warning like `Kite: no token found for ['SYMBOL']` means `kite.instruments("NSE")`
  did not contain an exact `tradingsymbol` match. Check for NSE symbol changes before
  assuming Kite is down.
- 2026-04-07 case: Tata Motors demerger made `TATAMOTORS` stale for this watchlist.
  Use `TMPV` / `TMPV.NS` for Tata Motors Passenger Vehicles.
- Kite historical candles can return pytz-aware datetimes. pandas on Python 3.14 can fail
  while building a DataFrame from those with `'NoneType' object has no attribute 'timezone'`.
- Fix in `data/kite_feed.py`: normalise each Kite record's `date` to stdlib
  `ZoneInfo("Asia/Kolkata")` before `pd.DataFrame(records)`.
