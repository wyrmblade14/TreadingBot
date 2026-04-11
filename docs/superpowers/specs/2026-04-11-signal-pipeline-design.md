# Signal Pipeline — Design Spec

**Date:** 2026-04-11
**Status:** Approved, pending implementation

---

## Problem

The 7-stage signal filter chain that every trade signal passes through is buried inside `signal_check()` in `scheduler/job_runner.py` as ~200 lines of nested if/else with `continue` statements and bare `except: pass` blocks.

This caused the April 2026 incidents:
- **2026-04-02:** Regime filter was absent — VIX blocked BUYs but not SELLs on a +2% bull day. All 12 short trades lost.
- **2026-04-10 (BHARTIARTL):** Dedup lock was missing — concurrent `signal_check()` threads both passed the guard at the same millisecond. Three identical SELL orders placed.
- **2026-04-10 (AXISBANK):** Cooldown guard was in the wrong layer — symbol re-entered 3× in 4 minutes after 2-second SL exits.

Root cause in all three: **there is no visible pipeline.** You cannot look at the code and see "a BUY signal goes through these 7 checks in this order." Each guard was added in a different place, in a different style, with a different failure mode.

---

## Goal

Make the signal filter chain explicit, named, and auditable — so:
- Every signal rejection has a traceable log line with the filter name and reason
- Adding a new filter (e.g. NIFTY divergence) is one class + one line, not 200 lines to navigate
- Each filter is independently unit-testable
- Filter errors fail-open visibly (logged warning) rather than silently

---

## Architecture

### Core types (`execution/signal_pipeline.py`)

```python
@dataclass
class FilterContext:
    symbol: str
    df: pd.DataFrame
    ltp: float
    nifty_chg: float      # pre-fetched once per signal_check cycle
    candle_ts: object     # 5m candle timestamp — used by DedupFilter

@dataclass
class FilterResult:
    verdict: str                      # "PASS" | "REJECT" | "MODIFY"
    reason: str = ""
    modified_signal: Signal | None = None   # only set on MODIFY

class SignalFilter(ABC):
    name: str

    @abstractmethod
    def evaluate(self, signal: Signal, context: FilterContext) -> FilterResult: ...
```

### Pipeline runner

```python
class SignalPipeline:
    def __init__(self, filters: list[SignalFilter]) -> None:
        self._filters = filters

    def run(
        self, signal: Signal, context: FilterContext
    ) -> tuple[Signal | None, list[FilterResult]]:
        results: list[FilterResult] = []
        for f in self._filters:
            try:
                result = f.evaluate(signal, context)
            except Exception as exc:
                logger.warning(f"[PIPELINE] {f.name} errored ({exc}) — fail-open")
                result = FilterResult(verdict="PASS", reason=f"error:{exc}")
            results.append(result)
            if result.verdict == "REJECT":
                _log_pipeline(signal, context, results, approved=False)
                return None, results
            if result.verdict == "MODIFY":
                signal = result.modified_signal
        _log_pipeline(signal, context, results, approved=True)
        return signal, results
```

### Pipeline flow

```
Signal (from strategy.generate_signal())
    │
    ▼
SignalPipeline.run(signal, context)
    │
    ├─ 1. DedupFilter          PASS / REJECT
    ├─ 2. ShortSellingFilter   PASS / REJECT
    ├─ 3. CatalystFilter       PASS / REJECT / MODIFY(flip direction)
    ├─ 4. FundamentalsFilter   PASS / REJECT
    ├─ 5. RegimeFilter         PASS / REJECT
    └─ 6. DivergenceFilter     PASS / REJECT
    │
    ▼
approved Signal (or None if any filter REJECTs)
    │
    ▼
OrderManager.process_signal()  [unchanged]
    │
    ▼
RiskManager.evaluate() + broker execution  [unchanged]
```

---

## Filters

All 6 filters live in `execution/signal_pipeline.py`. No subdirectory needed at this scale.

### 1. `DedupFilter`
- Checks `(symbol, strategy, candle_ts)` key against a shared set
- Lock makes check+add atomic (prevents concurrent thread race)
- Moves the existing `_last_signal_lock` / `_last_signal_key` logic from `signal_check()`
- REJECT reason: `"duplicate: same candle already fired"`

### 2. `ShortSellingFilter`
- REJECT if `signal.action == Action.SELL and not SHORT_SELLING_ENABLED`
- Moves the existing inline check from `signal_check()`
- REJECT reason: `"short selling disabled"`

### 3. `CatalystFilter`
- Fetches today's catalyst for the symbol from `get_todays_catalysts()`
- If catalyst confidence ≥ 0.70 and direction opposes signal → REJECT
- If catalyst confidence ≥ 0.75 → MODIFY (flip to catalyst direction with 1.5%/3.0% SL/target)
- Moves the existing catalyst block from `signal_check()` verbatim
- REJECT reason: `"catalyst conflict: {cat.reason} ({cat.confidence:.0%})"`
- MODIFY reason: `"catalyst flip: {cat.reason}"`

### 4. `FundamentalsFilter`
- Fetches `FundamentalJudgment` for the symbol
- REJECT if BUY + BEARISH bias + confidence ≥ 0.60
- REJECT if SELL + BULLISH bias + confidence ≥ 0.70
- Skips catalyst-sourced signals (`signal.strategy.startswith("catalyst_")`)
- Moves the existing fundamentals block from `signal_check()` verbatim
- REJECT reason: `"fundamentals: {judgment.summary}"`

### 5. `RegimeFilter`
- Fetches `MarketDirection` and `MarketRegime`
- REJECT SELL if direction=UP + regime=TRENDING
- REJECT BUY if direction=DOWN + regime=TRENDING
- Moves the existing regime block from `signal_check()` verbatim
- REJECT reason: `"regime: {direction.value}+{regime.value}"`

### 6. `DivergenceFilter`
- Calls `get_divergence(symbol, nifty_chg=context.nifty_chg)`
- REJECT if `DivergenceResult.diverging == True`
- New logic — implements the NIFTY divergence filter from the 2026-04-11 spec
- REJECT reason: `"divergence: stock {result.stock_chg:+.1f}% vs NIFTY {result.nifty_chg:+.1f}%"`

---

## Audit log

`_log_pipeline()` is a module-level private helper in `execution/signal_pipeline.py`. It formats and emits one `logger.info` line per signal after the pipeline completes (approved or rejected).

Every signal produces exactly one structured log line:

```
[PIPELINE] AXISBANK  SELL | dedup:PASS short:PASS catalyst:PASS fund:PASS regime:REJECT(UP+TRENDING) | 3ms
[PIPELINE] RELIANCE  BUY  | dedup:PASS short:PASS catalyst:MODIFY(flip→SELL) fund:PASS regime:PASS divergence:PASS | 6ms → APPROVED
[PIPELINE] INFY      BUY  | dedup:REJECT(duplicate) | 0ms
```

Format: `[PIPELINE] {symbol:10} {action} | {filter}:{verdict}(reason)... | {elapsed}ms [→ APPROVED]`

---

## `signal_check()` after refactor

The loop shrinks from ~200 lines to:

```python
for strategy in _strategies:
    signal = strategy.generate_signal(kite_sym, df)
    if signal.action == Action.HOLD:
        continue

    ctx = FilterContext(
        symbol=kite_sym,
        df=df,
        ltp=ltp,
        nifty_chg=_nifty_chg,
        candle_ts=last_candle_ts,
    )
    approved, _ = _pipeline.run(signal, ctx)
    if approved is None:
        continue

    # get_fundamental_judgment() is a cached call (TTL cache) — calling it
    # here a second time (FundamentalsFilter already called it internally)
    # costs zero network I/O and is needed to pass sizing context to RiskManager.
    _judgment = get_fundamental_judgment(kite_sym)
    decision = _risk_mgr.evaluate(approved, judgment=_judgment)
    if not decision.approved:
        logger.info(f"[RISK] {kite_sym} rejected: {decision.reason}")
        continue

    _order_mgr.execute_signal(decision.signal)
```

`OrderManager` internals (cooldown, position limits, RiskManager call) are unchanged.

---

## Files changed

| File | Change |
|---|---|
| `execution/signal_pipeline.py` | **New** — `FilterContext`, `FilterResult`, `SignalFilter`, `SignalPipeline`, all 6 filter classes |
| `scheduler/job_runner.py` | Remove inline filter blocks from `signal_check()`; instantiate `_pipeline` in `setup()` |
| `tests/test_signal_pipeline.py` | **New** — ~15–20 tests, one per filter verdict path |

No other files change. `OrderManager`, `RiskManager`, `PaperBroker`, all strategies — untouched.

---

## Migration plan

One filter at a time. Each step = extract guard → write test → run full suite → commit.

1. Create `SignalPipeline` + `DedupFilter` only — run 272-test suite
2. Add `ShortSellingFilter` — run suite
3. Add `CatalystFilter` — run suite
4. Add `FundamentalsFilter` — run suite
5. Add `RegimeFilter` — run suite
6. Add `DivergenceFilter` — run suite
7. Remove now-empty guard blocks from `signal_check()` — run suite

Each step is independently revertable. If step 3 breaks tests, only `CatalystFilter` needs fixing.

---

## What this does NOT change

- `OrderManager` cooldown logic (execution-layer, not signal-filtering)
- `RiskManager` VIX gates (already integrated into `evaluate()`, correct layer)
- All strategy classes
- Backtesting engine
- Dashboard
- Notifications

---

## Success criteria

- `signal_check()` loop is under 50 lines
- Every REJECT produces a `[PIPELINE]` log line with filter name and reason
- Each of the 6 filters has at least 2 passing unit tests (PASS path + REJECT path)
- Full 272-test suite passes after each migration step
- NIFTY divergence filter works without modifying `signal_check()` — just add to the pipeline list
