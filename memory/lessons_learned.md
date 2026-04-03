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

## EMA NaN at Session Start
- At 9:40 AM with only 5 intraday candles, EMA9/EMA21 return NaN (not enough history).
- `if len(df) >= 21` check is NOT sufficient — EMA can still be NaN if all 21 rows are from today.
- Fix: always check `if math.isnan(ema9_val)` after computing EMA, return hold_signal if NaN.
- This applies to any indicator with a warm-up period (MACD, ATR, etc.).
