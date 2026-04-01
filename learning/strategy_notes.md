# Strategy Notes

How each strategy works, current parameters, known issues, and tuning ideas.

---

## EMA Crossover (`strategies/ema_crossover.py`)

### How it works
Uses three EMAs: fast (9), medium (21), slow (50).
- **BUY signal**: EMA9 crosses above EMA21, AND price is above EMA50, AND VWAP bias ≥ 0
- **SELL signal**: EMA9 crosses below EMA21, AND price is below EMA50, AND VWAP bias ≤ 0
- Entry: current close. Stop: 1.5×ATR below entry. Target: 3.0×ATR above entry (2:1 RR).

### Current performance (Session 1)
- **5m, 50 days**: Mixed. RELIANCE -2.5%, TCS -0.1%, INFY +0.7%
- **1h, 450 days**: RELIANCE +0.7%, TCS -4.0%, INFY -3.7%, HDFCBANK -2.9%
- Actual RR achieved: only 1.41:1 (target is 2:1) — target never gets hit, exits are EOD squareoff

### Known issues
- Target (3.0×ATR) is rarely reached intraday — most exits are EOD squareoff
- Volume filter may be too lenient
- Works better on trending stocks (RELIANCE) than range-bound ones (TCS)

### Tuning ideas
- Try EMA 5/13/34 (faster signals)
- Add volume surge filter: volume > 1.5× 20-bar average at signal
- Consider partial profit take at 1×ATR, move stop to breakeven

---

## RSI+MACD (`strategies/rsi_macd_combo.py`)

### How it works
Combines RSI and MACD for momentum confirmation:
- **BUY signal**: RSI exits oversold zone (crosses above 40) + MACD line crosses above signal line
- **SELL signal**: RSI exits overbought zone (crosses below 60) + MACD line crosses below signal line
- Entry: current close. Stop: 1.5×ATR. Target: 3.0×ATR.

### Current performance (Session 1)
- **5m, 50 days**: Positive on all 3 stocks! RELIANCE +5.9%, TCS +0.8%, INFY +0.3%
- **1h, 450 days**: Mixed. RELIANCE -5.9%, TCS +1.7%, INFY -9.7%, HDFCBANK +0.1%
- **Best strategy on 5m candles**

### Known issues
- On 1h candles, generates too many signals (28% win rate on RELIANCE)
- RSI neutral zone (40–60) may be too wide — catches too many fake reversals
- **Generates SELL signals that were being sent as short entries (now fixed)** — SELL signals
  are skipped if no long position is open; only `check_exits()` handles actual exits

### Tuning ideas
- Tighten RSI zone: require RSI to cross 45 (not just 40) for BUY
- Add MACD histogram acceleration: histogram must be increasing for 2 bars
- Add minimum MACD histogram magnitude threshold

---

## Opening Range Breakout / ORB (`strategies/opening_range_breakout.py`)

### How it works
Defines the opening range as the high/low of the first 15 minutes (9:15–9:30 AM).
- **BUY signal**: price breaks above orb_high, AND VWAP bias ≥ 0
- **SELL signal**: price breaks below orb_low, AND VWAP bias ≤ 0
- Stop: orb_low (for BUY) or orb_high (for SELL). Target: orb_high + 2×range.

### Current performance (Session 1)
- **0 trades on every stock, every timeframe**
- Signals are generated but blocked by RiskManager

### Root cause
The ORB target formula: `target = orb_high + 2 × (orb_high - orb_low)`
The stop distance: `entry - orb_low` (can be large if breakout happened late)
If the breakout happens well above orb_high, the entry-to-stop distance is large
and the 2:1 RR check fails.

With 1h candles: opening range = first 1h candle (9:15–10:15 AM) → range is huge.
With 5m candles: opening range = 3 candles × 5m → should be small, but still 0 trades.

### Bugs fixed
- **Target formula** (2026-03-27): `max(orb_high + 1.5×range, entry + 2×ATR)` gave
  only 1.5:1 RR. Fixed to `max(orb_high + 2×range, entry + 2×risk)` where
  `risk = entry − orb_low`. Now always achieves 2:1.

### Bugs pending
- **Multi-day opening range** (2026-03-27): `_get_opening_range()` uses the entire
  visible slice (all historical days), so orb_high/orb_low is the max/min opening
  candle across months. Fix: filter by `df.index.date == today`.

### Tuning ideas
- After fixing the multi-day bug: expect ORB to fire at 9:35–10:00 AM, much more trades
- Add volume surge filter: only take ORB on days where opening volume > 1.5× avg
- Consider adding a "no ORB after 11 AM" rule — late breakouts are usually false

---

## VWAP Filter (`indicators/vwap.py`)

Applied as a filter on top of EMA and ORB signals.

### How it works
- VWAP = cumulative sum(typical_price × volume) / cumulative sum(volume) per day
- Filter: BUY signals only when price > VWAP, SELL signals only when price < VWAP
- Returns 0 (neutral) for daily candles where VWAP isn't meaningful

### Known bugs fixed
- **Zero-volume crash** (2026-03-27): `vwap[group_idx] = filtered_series` caused
  ValueError when zero-volume candles were present. Fixed using `.replace(0, NaN)`.
