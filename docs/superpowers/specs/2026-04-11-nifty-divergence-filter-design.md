# Design: NIFTY Divergence Filter

**Date:** 2026-04-11
**Status:** Approved

---

## Problem

The bot currently evaluates every signal in isolation — it doesn't check whether a stock is actually participating in the market's move. A human trader would immediately notice "NIFTY is up 1.5% but RELIANCE is flat — something is wrong with this stock today" and skip the BUY. Conversely, a stock that refuses to rally with the market is a relative weakness candidate — an attractive short.

---

## Goal

Before executing a signal, compare the stock's intraday % change against NIFTY's intraday % change. Use the divergence to:
- **Suppress BUY** on lagging stocks (NIFTY up ≥1%, stock up <0.3%)
- **Suppress SELL** on leading/strong stocks (NIFTY down ≥1%, stock down <0.3%)
- **Allow (and flag) SELL** on lagging stocks as relative-weakness shorts

---

## Threshold

| Parameter | Value | Rationale |
|---|---|---|
| NIFTY move required | ≥ 1.0% | Below this, "divergence" is just noise |
| Stock divergence cutoff | < 0.3% | Stock must meaningfully lag the index move |
| Before 10:00 AM | Return IN_LINE | Opening noise not settled — same guard as market_direction.py |

---

## Architecture

### New module: `analysis/nifty_correlation.py`

Follows the same pattern as `analysis/market_direction.py` and `analysis/regime_detector.py`.

**Data structures:**

```python
@dataclass
class DivergenceResult:
    nifty_chg_pct: float       # NIFTY intraday % vs 9:15 open
    stock_chg_pct: float       # Stock intraday % vs 9:15 open
    label: str                 # "LAGGING" | "IN_LINE" | "LEADING"
    suppress_buy: bool         # Block BUY on this signal
    suppress_sell: bool        # Block SELL on this signal
    amplify_sell: bool         # LAGGING stock — relative weakness short confirmed
```

**Public API:**

```python
def get_nifty_change() -> float
    # Returns NIFTY's intraday % change vs today's 9:15 open.
    # Uses ^NSEI 5m OHLCV via fetch_ohlcv() (same data source as market_direction.py).
    # Module-level cache — refreshes once per 5-minute signal cycle.
    # Returns 0.0 on any fetch error (fail-open).

def get_divergence(symbol: str, symbol_df: pd.DataFrame, nifty_chg: float) -> DivergenceResult
    # Computes stock's intraday % change from symbol_df (already fetched by signal_check).
    # Classifies against threshold rules.
    # Returns IN_LINE (no suppression) on any error — never blocks a signal on data failure.
```

**Classification rules:**

```
nifty_chg ≥ +1.0% AND stock_chg < +0.3%  →  LAGGING   (suppress_buy=True,  amplify_sell=True)
nifty_chg ≤ −1.0% AND stock_chg > −0.3%  →  LEADING   (suppress_sell=True, amplify_sell=False)
anything else                              →  IN_LINE   (no suppression)
```

**Intraday change calculation:**

```python
# Use today's first candle open as the reference price (9:15 open)
today_df = symbol_df[symbol_df.index.date == date.today()]
if len(today_df) < 2:
    return IN_LINE  # not enough intraday data
open_price = float(today_df["open"].iloc[0])
current_price = float(today_df["close"].iloc[-1])
stock_chg_pct = (current_price - open_price) / open_price * 100
```

---

### Integration: `scheduler/job_runner.py`

NIFTY data fetched **once per scan cycle** before the symbol loop, then passed into `get_divergence()` per symbol. This avoids one HTTP call per symbol.

**Placement in signal pipeline:**

```
strategy.generate_signal()
    → catalyst filter          (existing)
    → fundamental filter       (existing)
    → [NEW] divergence filter  ← inserted here
    → regime filter            (existing)
    → risk_mgr.evaluate()
    → order_mgr.execute_signal()
```

**Code change (~10 lines):**

```python
# Before the symbol loop:
from analysis.nifty_correlation import get_nifty_change, get_divergence
_nifty_chg = get_nifty_change()

# Inside per-strategy block, after fundamental filter:
try:
    div = get_divergence(kite_sym, df, _nifty_chg)
    if div.suppress_buy and signal.action == Action.BUY:
        logger.info(
            f"[DIVERGENCE] Suppressing BUY {kite_sym} — LAGGING "
            f"(NIFTY {div.nifty_chg_pct:+.1f}% / stock {div.stock_chg_pct:+.1f}%)"
        )
        continue
    if div.suppress_sell and signal.action == Action.SELL:
        logger.info(
            f"[DIVERGENCE] Suppressing SELL {kite_sym} — LEADING "
            f"(NIFTY {div.nifty_chg_pct:+.1f}% / stock {div.stock_chg_pct:+.1f}%)"
        )
        continue
except Exception:
    pass  # fail-open — never block a signal on data error
```

`amplify_sell=True` signals pass through as-is. The logger line makes the relative-weakness confirmation visible in logs. Sizing amplification is explicitly out of scope for this iteration — validate signal quality first.

---

### Minor change: `dashboard/views/signals.py`

Add a `Divergence` column to the signals table: `LAGGING ↓` / `IN_LINE` / `LEADING ↑`. Purely display — no logic change.

---

## Testing: `tests/test_nifty_correlation.py`

| # | Scenario | Expected |
|---|---|---|
| 1 | NIFTY +1.2%, stock +0.1% | LAGGING, suppress_buy=True, amplify_sell=True |
| 2 | NIFTY +1.2%, stock +1.0% | IN_LINE — stock participating |
| 3 | NIFTY +1.5%, stock −0.5% | LAGGING, suppress_buy=True, amplify_sell=True |
| 4 | NIFTY −1.0%, stock −0.1% | LEADING, suppress_sell=True |
| 5 | NIFTY +0.5%, stock flat | IN_LINE — NIFTY below 1% threshold |
| 6 | NIFTY data unavailable (exception) | IN_LINE, fail-open |
| 7 | Before 10:00 AM | IN_LINE — too early |
| 8 | amplify_sell=True signal | SELL passes through unblocked |

---

## Files Changed

| File | Type | Description |
|---|---|---|
| `analysis/nifty_correlation.py` | New | Core divergence logic + 5-min cache |
| `scheduler/job_runner.py` | Edit | Fetch NIFTY once, call get_divergence() per signal |
| `tests/test_nifty_correlation.py` | New | 8 unit tests |
| `dashboard/views/signals.py` | Minor edit | Add Divergence column to signals table |

---

## Out of Scope

- Sizing amplification on `amplify_sell` signals (validate signal quality first)
- Historical NIFTY correlation in backtest engine (separate future idea)
- Per-sector divergence (e.g. Bank NIFTY vs banking stocks) — future enhancement
