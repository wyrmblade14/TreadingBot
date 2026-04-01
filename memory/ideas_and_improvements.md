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

---

## Done
*(move entries here when implemented)*

## Dropped
*(move entries here with reason)*
