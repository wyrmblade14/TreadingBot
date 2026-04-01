# Backtest Analysis Log

Every time we run a backtest, the results and conclusions go here.

---

## Session 1 — 2026-03-27

### Setup
- Capital: ₹1,00,000
- Stocks: RELIANCE, TCS, INFY, HDFCBANK
- Date range A: 2025-01-01 → 2026-03-27 (15 months, **1h candles**)
- Date range B: 2026-02-05 → 2026-03-27 (50 days, **5m candles**)

---

### Results — 1h candles (450-day range)

| Symbol | Strategy | Trades | Net P&L | Return | Win Rate |
|---|---|---|---|---|---|
| RELIANCE | EMA Crossover | 12 | +₹651 | +0.7% | 50% |
| RELIANCE | RSI+MACD | 67 | -₹5,926 | -5.9% | 28% |
| RELIANCE | ORB | 0 | ₹0 | 0.0% | — |
| TCS | EMA Crossover | 20 | -₹3,989 | -4.0% | — |
| TCS | RSI+MACD | 44 | +₹1,677 | +1.7% | — |
| TCS | ORB | 0 | ₹0 | 0.0% | — |
| INFY | EMA Crossover | 17 | -₹3,680 | -3.7% | — |
| INFY | RSI+MACD | 51 | -₹9,687 | -9.7% | — |
| INFY | ORB | 0 | ₹0 | 0.0% | — |
| HDFCBANK | EMA Crossover | 22 | -₹2,896 | -2.9% | — |
| HDFCBANK | RSI+MACD | 46 | +₹138 | +0.1% | — |
| HDFCBANK | ORB | 0 | ₹0 | 0.0% | — |

---

### Results — 5m candles (50-day range, more representative of live bot)

| Symbol | Strategy | Trades | Net P&L | Return |
|---|---|---|---|---|
| RELIANCE | EMA Crossover | 10 | -₹2,487 | -2.5% |
| RELIANCE | RSI+MACD | 49 | +₹5,924 | **+5.9%** |
| RELIANCE | ORB | 0 | ₹0 | 0.0% |
| TCS | EMA Crossover | 17 | -₹68 | -0.1% |
| TCS | RSI+MACD | 40 | +₹804 | +0.8% |
| TCS | ORB | 0 | ₹0 | 0.0% |
| INFY | EMA Crossover | 13 | +₹652 | +0.7% |
| INFY | RSI+MACD | 44 | +₹289 | +0.3% |
| INFY | ORB | 0 | ₹0 | 0.0% |

---

### Detailed: EMA Crossover on RELIANCE (1h)

| Metric | Value |
|---|---|
| Trades | 12 (6 wins / 6 losses) |
| Win rate | 50% |
| Avg win | ₹376 |
| Avg loss | ₹268 |
| Actual RR | 1.41:1 (target is 2:1) |
| Profit factor | 1.41 |
| Expectancy | +₹54/trade |
| Max drawdown | -1.3% |
| Sharpe | 0.42 |

### Detailed: RSI+MACD on RELIANCE (1h)

| Metric | Value |
|---|---|
| Trades | 67 (19 wins / 48 losses) |
| Win rate | 28.4% |
| Avg win | ₹380 |
| Avg loss | ₹274 |
| Actual RR | 1.39:1 |
| Profit factor | 0.55 |
| Expectancy | -₹88/trade |
| Max drawdown | -7.5% |
| Sharpe | -1.94 |

---

### Key Findings

#### 1. ORB gets 0 trades on ALL stocks (both 1h and 5m)
- **Root cause**: ORB stop-loss = orb_low, target = orb_high + 2×ORB_range.
  The opening range is wide on NSE large-caps. The risk (entry - orb_low) is often
  larger than the reward, failing the 2:1 RR requirement in RiskManager.
- **Deeper issue with 1h**: First 1h candle = 9:15–10:15 AM, so "opening range"
  spans a full hour. Stop is enormous.
- **Still 0 on 5m**: Need to investigate — maybe ORB range itself is too wide,
  or VWAP filter is rejecting all signals.
- **TODO**: Debug ORB with debug logs; print every rejected signal and reason.

#### 2. Target never reached (exits are 100% EOD squareoff or stop loss)
- On 1h candles: trade entered at noon leaves only 3-4 candles before 15:15 squareoff.
  2×ATR target unreachable in so little time.
- **Implication**: The 2:1 RR target is too ambitious for intraday on 1h data.
  The bot's live 5m data should be better — more candles before squareoff.
- **TODO**: On 5m data, check if any trades hit target vs EOD squareoff.

#### 3. RSI+MACD performs better on 5m than 1h
- 1h RELIANCE: -5.9%, only 28% win rate
- 5m RELIANCE: **+5.9%**, need to check win rate and exits
- RSI crossovers on 5m capture shorter momentum swings better

#### 4. EMA is inconsistent across stocks
- Wins on RELIANCE and INFY (5m), loses on TCS
- Suggests EMA works better on trending stocks, struggles on range-bound ones

#### 5. 1h backtest is misleading for this bot
- The live bot uses 5m candles. 1h results systematically underestimate
  strategy quality because there is no time to reach targets.
- **Going forward**: Use 5m (≤55 days) as the primary backtest timeframe.

---

### Changes Made

1. **Fixed VWAP bug** — `compute_vwap()` crashed on zero-volume candles.
   `vwap[group_idx] = ...` had a length mismatch when `with_vol` filtered some rows.
   Fixed by replacing zero cumulative volume with NaN before dividing.
   File: `indicators/vwap.py` line 64–67.

---

---

## Session 1 — Continued (same day)

### ORB Fix: Target formula was wrong

**Problem**: `target = max(orb_high + 1.5×range, entry + 2×ATR)` only produces ~1.5:1 RR.
The 2×ATR part is smaller than the risk taken (entry − orb_low).
So every ORB signal was rejected by the engine's inline `RR < 2.0` check.

**Fix** (`strategies/opening_range_breakout.py`):
```python
risk = current_price - orb_low
target = max(orb_high + orb_width * 2.0, current_price + 2.0 * risk)
```
This guarantees 2:1 RR from the actual entry price.

**Result after fix (5m, 50 days)**:

| Symbol | Trades | Win Rate | PF | Net P&L |
|---|---|---|---|---|
| RELIANCE | 6 | 16.7% | 0.27 | -₹439 |
| TCS | 10 | 10.0% | 0.02 | -₹1,087 |
| INFY | 7 | 28.6% | 0.79 | -₹59 |

Performance is still poor — all exits are EOD squareoff, no target or stop hits.

### ORB Bug #2: Multi-day opening range (NOT YET FIXED)

**Problem**: `_get_opening_range()` in `indicators/orb.py` uses:
```python
orb_mask = df.index.time <= self.orb_end_time
```
The `df` passed to it is `visible = df_all.iloc[:abs_idx+1]` — the **entire historical
slice** across all days. So `orb_mask` selects 9:15–9:30 candles from every historical
day, and takes the max high / min low across all of them. This gives an artificially
wide "opening range" from months of data.

**Effect**: ORB signals fire very late (11 AM–2 PM) because the stock needs to break out
of a range that was set by the highest/lowest opening candle across months of history.

**Fix needed** (`indicators/orb.py` → `_get_opening_range()`):
```python
today = df.index[-1].date()
orb_mask = (df.index.date == today) & (df.index.time <= self.orb_end_time)
```
Restrict the opening range to **today's date only**.

Status: **TODO — not yet implemented.**

---

### Next Investigations

- [ ] **Fix ORB multi-day range bug** — restrict opening range to today's date only
- [ ] After ORB fix: re-run 5m backtest, check if ORB fires at 9:35–10:00 as expected
- [ ] Check 5m RSI+MACD exit reasons (target hits vs EOD squareoff)
- [ ] RSI+MACD on 1h: is the 28% win rate due to too many MACD noise signals?
       Possible fix: require MACD histogram > 0 AND > previous bar (accelerating)
- [ ] EMA on TCS: why does it lose? Check if TCS was range-bound Jan-Mar 2026.

---

## Session 2 — 2026-03-27 (live bot run)

### Live Bot Errors Found & Fixed

#### Error 1: `'NoneType' object is not subscriptable` (every symbol, every 5-min cycle)
- **Root cause**: yfinance `ticker.history()` returns `None` when Yahoo Finance
  rate-limits concurrent requests. `fetch_ohlcv()` had no `None` guard before calling `.empty`.
- **Fix** (`data/historical.py`): changed `if df.empty:` → `if df is None or df.empty:`
- **Also**: reduced `ThreadPoolExecutor(max_workers=5)` → `max_workers=3` in `job_runner.py`
  to reduce concurrent request pressure on Yahoo Finance API.

#### Error 2: `Order REJECTED (oversell): Cannot sell N shares; holding 0`
- **Root cause**: RSI+MACD and EMA generate SELL signals (bearish momentum) as new entries.
  NSE cash segment is long-only — we cannot open short positions.
  OrderManager correctly rejects the short sell, but spams the log with warnings.
- **Fix** (`scheduler/job_runner.py`): added check in `signal_check()` —
  if `signal.action == Action.SELL` and no existing long position → skip silently (DEBUG log).
  SELL signals are valid only as exits (handled by `check_exits()`), not new entries.

#### Error 3: `Order REJECTED (insufficient funds): need ₹98k, have ₹80`
- **Root cause**: Capital was synced from broker once at start of the 5-min cycle.
  After Symbol 1 used ₹99,920, Symbol 2–10 still saw ₹1,00,000 as available capital
  → position sizer computed qty=20 → broker rejected with "insufficient funds".
- **Fix** (`scheduler/job_runner.py`): moved capital sync inside the per-symbol loop
  (just before entry evaluation). Each symbol now sees cash AFTER any trades placed
  earlier in the same cycle.

### Status
- All 114 tests passing
- Bot is now long-only (no erroneous short entries)
- Capital tracking is accurate within a single 5-min cycle
- yfinance rate-limit failures handled gracefully (symbol skipped, no crash)
