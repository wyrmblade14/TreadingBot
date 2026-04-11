# Signal Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ~200-line implicit filter chain inside `signal_check()` with an explicit, named `SignalPipeline` of 6 `SignalFilter` classes — each independently testable, each producing a structured audit log line.

**Architecture:** A new `execution/signal_pipeline.py` holds the `SignalPipeline` runner and all 6 filter classes. `job_runner.py` instantiates the pipeline once in `setup()` and calls `pipeline.run(signal, context)` in the signal loop, replacing all inline guard blocks. `OrderManager` and `RiskManager` are untouched.

**Tech Stack:** Python 3.14, `unittest.mock.patch`, `loguru`, existing project types (`Signal`, `Action`, `DivergenceResult`, etc.)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `execution/signal_pipeline.py` | **Create** | `FilterContext`, `FilterResult`, `SignalFilter` ABC, `SignalPipeline`, 6 filter classes, `_log_pipeline` helper |
| `scheduler/job_runner.py` | **Modify** | Add `_pipeline` singleton; replace inline guard blocks in `signal_check()` with `_pipeline.run()` |
| `tests/test_signal_pipeline.py` | **Create** | One test class per filter, helper functions `_make_signal` / `_make_context` |

---

## Task 1: Core types + empty SignalPipeline

**Files:**
- Create: `execution/signal_pipeline.py`
- Create: `tests/test_signal_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_signal_pipeline.py
import pandas as pd
import pytest
from datetime import datetime
from strategies.base_strategy import Action, Signal
from execution.signal_pipeline import (
    FilterContext, FilterResult, SignalFilter, SignalPipeline,
)


# ── Shared test helpers ───────────────────────────────────────────────

def _make_signal(
    symbol: str = "RELIANCE",
    action: Action = Action.BUY,
    strategy: str = "ema_crossover",
) -> Signal:
    price = 2500.0
    if action == Action.BUY:
        return Signal(symbol=symbol, action=action,
                      entry_price=price, stop_loss=price * 0.985,
                      target=price * 1.030, strategy=strategy)
    return Signal(symbol=symbol, action=action,
                  entry_price=price, stop_loss=price * 1.015,
                  target=price * 0.970, strategy=strategy)


def _make_context(
    symbol: str = "RELIANCE",
    ltp: float = 2500.0,
    nifty_chg: float = 0.0,
    candle_ts: object = None,
    df: pd.DataFrame | None = None,
) -> FilterContext:
    if df is None:
        df = pd.DataFrame()
    if candle_ts is None:
        candle_ts = datetime(2026, 4, 11, 9, 25)
    return FilterContext(symbol=symbol, df=df, ltp=ltp,
                        nifty_chg=nifty_chg, candle_ts=candle_ts)


# ── Task 1 tests ──────────────────────────────────────────────────────

def test_empty_pipeline_passes_signal():
    pipeline = SignalPipeline([])
    signal = _make_signal()
    ctx = _make_context()
    approved, results = pipeline.run(signal, ctx)
    assert approved is not None
    assert approved.action == Action.BUY
    assert results == []


def test_pipeline_returns_original_signal_when_no_filters():
    signal = _make_signal(symbol="TCS", action=Action.SELL)
    ctx = _make_context(symbol="TCS")
    pipeline = SignalPipeline([])
    approved, _ = pipeline.run(signal, ctx)
    assert approved is signal
```

- [ ] **Step 2: Run to confirm it fails**

```bash
cd /home/wyrmblade/TreadingBot && source venv/bin/activate
python -m pytest tests/test_signal_pipeline.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'execution.signal_pipeline'`

- [ ] **Step 3: Create `execution/signal_pipeline.py`**

```python
"""
Signal Pipeline — explicit, named filter chain for trade signals.

Every signal produced by a strategy passes through this pipeline before
reaching the Risk Manager. Each filter has one job: PASS, REJECT, or
MODIFY the signal. Any filter failure is logged and treated as PASS
(fail-open), so a data error never silently blocks a trade.

Audit log (one line per signal):
  [PIPELINE] RELIANCE   BUY  | dedup:PASS short:PASS catalyst:PASS ... | 4ms → APPROVED
  [PIPELINE] AXISBANK   SELL | dedup:PASS regime:REJECT(UP+TRENDING) | 2ms
"""

from __future__ import annotations

import threading
import time as _time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
from loguru import logger

from strategies.base_strategy import Action, Signal


# ── Core types ────────────────────────────────────────────────────────

@dataclass
class FilterContext:
    """Immutable context passed to every filter in the pipeline."""
    symbol:    str
    df:        pd.DataFrame
    ltp:       float
    nifty_chg: float    # NIFTY50 intraday % change, pre-fetched once per cycle
    candle_ts: object   # 5-minute candle timestamp — used by DedupFilter


@dataclass
class FilterResult:
    verdict:          str              # "PASS" | "REJECT" | "MODIFY"
    reason:           str = ""
    modified_signal:  Optional[Signal] = None  # only set when verdict == "MODIFY"


class SignalFilter(ABC):
    """Base class for all pipeline filters."""
    name: str

    @abstractmethod
    def evaluate(self, signal: Signal, context: FilterContext) -> FilterResult: ...


# ── Audit log helper ─────────────────────────────────────────────────

def _log_pipeline(
    signal: Signal,
    context: FilterContext,
    results: list[FilterResult],
    approved: bool,
    elapsed_ms: float,
) -> None:
    parts = []
    for r in results:
        tag = r.verdict.lower()
        if r.reason:
            short = r.reason[:30].replace("\n", " ")
            tag = f"{tag}({short})"
        parts.append(f"{r.__class__.__name__.replace('Filter','').lower() or '?'}:{tag}")
    chain = " ".join(parts) if parts else "—"
    suffix = " → APPROVED" if approved else ""
    logger.info(
        f"[PIPELINE] {context.symbol:<12} {signal.action.value:<4} | "
        f"{chain} | {elapsed_ms:.0f}ms{suffix}"
    )


# ── Pipeline runner ───────────────────────────────────────────────────

class SignalPipeline:
    """
    Run a signal through an ordered list of filters.

    Returns (approved_signal, results):
      - approved_signal is None if any filter REJECTs.
      - approved_signal is the (possibly modified) signal on full PASS.
      - results is the list of FilterResult for every filter that ran.
    """

    def __init__(self, filters: list[SignalFilter]) -> None:
        self._filters = filters

    def run(
        self, signal: Signal, context: FilterContext
    ) -> tuple[Optional[Signal], list[FilterResult]]:
        results: list[FilterResult] = []
        start = _time.monotonic()

        for f in self._filters:
            try:
                result = f.evaluate(signal, context)
            except Exception as exc:
                logger.warning(
                    f"[PIPELINE] {f.name} raised {exc!r} for "
                    f"{context.symbol} — treating as PASS (fail-open)"
                )
                result = FilterResult(verdict="PASS", reason=f"error:{exc}")
            results.append(result)

            if result.verdict == "REJECT":
                elapsed = (_time.monotonic() - start) * 1000
                _log_pipeline(signal, context, results, approved=False, elapsed_ms=elapsed)
                return None, results

            if result.verdict == "MODIFY" and result.modified_signal is not None:
                signal = result.modified_signal

        elapsed = (_time.monotonic() - start) * 1000
        _log_pipeline(signal, context, results, approved=True, elapsed_ms=elapsed)
        return signal, results
```

- [ ] **Step 4: Fix the log helper — filter name comes from filter instance, not result class**

The `_log_pipeline` function references `r.__class__.__name__` but `results` is a list of `FilterResult`, not filters. Fix by tracking `(filter_name, result)` pairs inside `run()`:

```python
# Replace the run() method body with this version:
    def run(
        self, signal: Signal, context: FilterContext
    ) -> tuple[Optional[Signal], list[FilterResult]]:
        results: list[FilterResult] = []
        named: list[tuple[str, FilterResult]] = []   # (filter.name, result)
        start = _time.monotonic()

        for f in self._filters:
            try:
                result = f.evaluate(signal, context)
            except Exception as exc:
                logger.warning(
                    f"[PIPELINE] {f.name} raised {exc!r} for "
                    f"{context.symbol} — treating as PASS (fail-open)"
                )
                result = FilterResult(verdict="PASS", reason=f"error:{exc}")
            results.append(result)
            named.append((f.name, result))

            if result.verdict == "REJECT":
                elapsed = (_time.monotonic() - start) * 1000
                _log_pipeline(signal, context, named, approved=False, elapsed_ms=elapsed)
                return None, results

            if result.verdict == "MODIFY" and result.modified_signal is not None:
                signal = result.modified_signal

        elapsed = (_time.monotonic() - start) * 1000
        _log_pipeline(signal, context, named, approved=True, elapsed_ms=elapsed)
        return signal, results
```

And update `_log_pipeline` signature to accept `named: list[tuple[str, FilterResult]]`:

```python
def _log_pipeline(
    signal: Signal,
    context: FilterContext,
    named: list[tuple[str, FilterResult]],
    approved: bool,
    elapsed_ms: float,
) -> None:
    parts = []
    for fname, r in named:
        tag = r.verdict.lower()
        if r.reason:
            short = r.reason[:25].replace("\n", " ")
            tag = f"{tag}({short})"
        parts.append(f"{fname}:{tag}")
    chain = " ".join(parts) if parts else "—"
    suffix = " → APPROVED" if approved else ""
    logger.info(
        f"[PIPELINE] {context.symbol:<12} {signal.action.value:<4} | "
        f"{chain} | {elapsed_ms:.0f}ms{suffix}"
    )
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_signal_pipeline.py -v
```
Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add execution/signal_pipeline.py tests/test_signal_pipeline.py
git commit -m "feat: add SignalPipeline core types and empty runner"
```

---

## Task 2: DedupFilter

Moves the `_last_signal_key` / `_last_signal_lock` dedup logic from `job_runner.py` into a self-contained filter class.

**Files:**
- Modify: `execution/signal_pipeline.py` (add `DedupFilter`)
- Modify: `tests/test_signal_pipeline.py` (add `TestDedupFilter`)

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/test_signal_pipeline.py

from execution.signal_pipeline import DedupFilter


class TestDedupFilter:
    def test_first_signal_passes(self):
        f = DedupFilter()
        sig = _make_signal()
        ctx = _make_context(candle_ts=datetime(2026, 4, 11, 9, 25))
        result = f.evaluate(sig, ctx)
        assert result.verdict == "PASS"

    def test_duplicate_on_same_candle_rejects(self):
        f = DedupFilter()
        sig = _make_signal(strategy="ema_crossover")
        ctx = _make_context(candle_ts=datetime(2026, 4, 11, 9, 25))
        f.evaluate(sig, ctx)                  # first call — registers key
        result = f.evaluate(sig, ctx)         # second call — same key
        assert result.verdict == "REJECT"
        assert "duplicate" in result.reason

    def test_different_candle_ts_passes(self):
        f = DedupFilter()
        sig = _make_signal(strategy="ema_crossover")
        ctx1 = _make_context(candle_ts=datetime(2026, 4, 11, 9, 25))
        ctx2 = _make_context(candle_ts=datetime(2026, 4, 11, 9, 30))
        f.evaluate(sig, ctx1)
        result = f.evaluate(sig, ctx2)        # new candle — should pass
        assert result.verdict == "PASS"

    def test_different_strategy_same_candle_passes(self):
        f = DedupFilter()
        ctx = _make_context(candle_ts=datetime(2026, 4, 11, 9, 25))
        f.evaluate(_make_signal(strategy="ema_crossover"), ctx)
        result = f.evaluate(_make_signal(strategy="rsi_macd_combo"), ctx)
        assert result.verdict == "PASS"
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_signal_pipeline.py::TestDedupFilter -v 2>&1 | head -15
```
Expected: `ImportError` — `DedupFilter` not defined yet.

- [ ] **Step 3: Add `DedupFilter` to `execution/signal_pipeline.py`**

Add after the `SignalPipeline` class:

```python
# ── Filters ───────────────────────────────────────────────────────────

class DedupFilter(SignalFilter):
    """
    Reject a signal if the same (symbol, strategy, candle_ts) key was
    already seen this cycle. Prevents duplicate orders when signal_check()
    is called more frequently than the candle interval.

    The lock makes the check+add atomic so concurrent signal_check()
    threads cannot both pass the guard at the same millisecond.
    """
    name = "dedup"

    def __init__(self) -> None:
        self._seen: set[tuple] = set()
        self._lock = threading.Lock()

    def evaluate(self, signal: Signal, context: FilterContext) -> FilterResult:
        key = (context.symbol, signal.strategy, context.candle_ts)
        with self._lock:
            if key in self._seen:
                return FilterResult(
                    verdict="REJECT",
                    reason="duplicate: same candle already fired",
                )
            self._seen.add(key)
            if len(self._seen) > 200:   # bounded — clear after ~200 unique signals
                self._seen.clear()
        return FilterResult(verdict="PASS")
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_signal_pipeline.py -v
```
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add execution/signal_pipeline.py tests/test_signal_pipeline.py
git commit -m "feat: add DedupFilter to signal pipeline"
```

---

## Task 3: ShortSellingFilter

**Files:**
- Modify: `execution/signal_pipeline.py`
- Modify: `tests/test_signal_pipeline.py`

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/test_signal_pipeline.py

from unittest.mock import patch
from execution.signal_pipeline import ShortSellingFilter


class TestShortSellingFilter:
    def test_buy_always_passes(self):
        f = ShortSellingFilter()
        result = f.evaluate(_make_signal(action=Action.BUY), _make_context())
        assert result.verdict == "PASS"

    def test_sell_passes_when_short_selling_enabled(self):
        f = ShortSellingFilter()
        with patch("execution.signal_pipeline.SHORT_SELLING_ENABLED", True):
            result = f.evaluate(_make_signal(action=Action.SELL), _make_context())
        assert result.verdict == "PASS"

    def test_sell_rejected_when_short_selling_disabled(self):
        f = ShortSellingFilter()
        with patch("execution.signal_pipeline.SHORT_SELLING_ENABLED", False):
            result = f.evaluate(_make_signal(action=Action.SELL), _make_context())
        assert result.verdict == "REJECT"
        assert "short selling disabled" in result.reason
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_signal_pipeline.py::TestShortSellingFilter -v 2>&1 | head -10
```
Expected: `ImportError` — `ShortSellingFilter` not defined.

- [ ] **Step 3: Add `ShortSellingFilter` to `execution/signal_pipeline.py`**

Add the import at the top of the file (after existing imports):

```python
from config.settings import SHORT_SELLING_ENABLED
```

Add the filter class after `DedupFilter`:

```python
class ShortSellingFilter(SignalFilter):
    """Reject SELL signals when short selling is disabled in config."""
    name = "short"

    def evaluate(self, signal: Signal, context: FilterContext) -> FilterResult:
        if signal.action == Action.SELL and not SHORT_SELLING_ENABLED:
            return FilterResult(verdict="REJECT", reason="short selling disabled")
        return FilterResult(verdict="PASS")
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_signal_pipeline.py -v
```
Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add execution/signal_pipeline.py tests/test_signal_pipeline.py
git commit -m "feat: add ShortSellingFilter to signal pipeline"
```

---

## Task 4: CatalystFilter

**Files:**
- Modify: `execution/signal_pipeline.py`
- Modify: `tests/test_signal_pipeline.py`

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/test_signal_pipeline.py

from unittest.mock import patch, MagicMock
from execution.signal_pipeline import CatalystFilter


def _make_catalyst(direction: str, confidence: float, reason: str = "test event") -> MagicMock:
    cat = MagicMock()
    cat.symbol = "RELIANCE"
    cat.direction = direction
    cat.confidence = confidence
    cat.reason = reason
    return cat


def _mock_catalysts(bullish=None, bearish=None):
    summary = MagicMock()
    summary.bullish = bullish or []
    summary.bearish = bearish or []
    return summary


class TestCatalystFilter:
    def test_no_catalyst_passes(self):
        f = CatalystFilter()
        with patch("execution.signal_pipeline.get_todays_catalysts",
                   return_value=_mock_catalysts()):
            result = f.evaluate(_make_signal(action=Action.BUY), _make_context())
        assert result.verdict == "PASS"

    def test_bearish_catalyst_rejects_buy_below_flip_threshold(self):
        # confidence=0.71 → block but don't flip (flip needs ≥0.75)
        f = CatalystFilter()
        cat = _make_catalyst("BEARISH_CATALYST", confidence=0.71)
        with patch("execution.signal_pipeline.get_todays_catalysts",
                   return_value=_mock_catalysts(bearish=[cat])):
            with patch("execution.signal_pipeline.SHORT_SELLING_ENABLED", False):
                result = f.evaluate(_make_signal(action=Action.BUY), _make_context())
        assert result.verdict == "REJECT"
        assert "catalyst conflict" in result.reason

    def test_bearish_catalyst_flips_buy_to_sell_at_high_confidence(self):
        f = CatalystFilter()
        cat = _make_catalyst("BEARISH_CATALYST", confidence=0.80)
        with patch("execution.signal_pipeline.get_todays_catalysts",
                   return_value=_mock_catalysts(bearish=[cat])):
            with patch("execution.signal_pipeline.SHORT_SELLING_ENABLED", True):
                result = f.evaluate(
                    _make_signal(action=Action.BUY),
                    _make_context(ltp=2500.0),
                )
        assert result.verdict == "MODIFY"
        assert result.modified_signal is not None
        assert result.modified_signal.action == Action.SELL
        assert result.modified_signal.strategy == "catalyst_short"

    def test_bullish_catalyst_flips_sell_to_buy_at_high_confidence(self):
        f = CatalystFilter()
        cat = _make_catalyst("BULLISH_CATALYST", confidence=0.80)
        with patch("execution.signal_pipeline.get_todays_catalysts",
                   return_value=_mock_catalysts(bullish=[cat])):
            result = f.evaluate(
                _make_signal(action=Action.SELL),
                _make_context(ltp=2500.0),
            )
        assert result.verdict == "MODIFY"
        assert result.modified_signal.action == Action.BUY
        assert result.modified_signal.strategy == "catalyst_long"

    def test_catalyst_fetch_error_passes(self):
        f = CatalystFilter()
        with patch("execution.signal_pipeline.get_todays_catalysts",
                   side_effect=Exception("network error")):
            result = f.evaluate(_make_signal(), _make_context())
        # Pipeline fail-open catches this at the pipeline level, but
        # CatalystFilter itself should also not raise
        assert result.verdict == "PASS"
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_signal_pipeline.py::TestCatalystFilter -v 2>&1 | head -15
```
Expected: `ImportError` — `CatalystFilter` not defined.

- [ ] **Step 3: Add `CatalystFilter` to `execution/signal_pipeline.py`**

Add this import at the top:

```python
from analysis.catalyst_scanner import get_todays_catalysts
```

Add the filter class after `ShortSellingFilter`:

```python
class CatalystFilter(SignalFilter):
    """
    Block or flip signals that conflict with a high-confidence news catalyst.

    Rules (confidence thresholds):
      ≥ 0.70: reject the conflicting signal
      ≥ 0.75: also flip to trade WITH the catalyst (MODIFY)

    Flip sizing: 1.5% SL / 3.0% target = 2:1 RR so RiskManager's
    minimum-RR check always passes.

    Fails open — any data error is logged at the pipeline level.
    """
    name = "catalyst"

    def evaluate(self, signal: Signal, context: FilterContext) -> FilterResult:
        summary = get_todays_catalysts()
        cat_map = {r.symbol: r for r in (summary.bullish + summary.bearish)}
        cat = cat_map.get(context.symbol)

        if cat is None or cat.confidence < 0.7:
            return FilterResult(verdict="PASS")

        if signal.action == Action.BUY and cat.direction == "BEARISH_CATALYST":
            if SHORT_SELLING_ENABLED and cat.confidence >= 0.75 and context.ltp:
                sl  = round(context.ltp * 1.015, 2)
                tgt = round(context.ltp * 0.970, 2)
                flipped = Signal(
                    symbol=context.symbol,
                    action=Action.SELL,
                    entry_price=context.ltp,
                    stop_loss=sl,
                    target=tgt,
                    strategy="catalyst_short",
                    reason=f"Catalyst flip: {cat.reason}",
                )
                return FilterResult(
                    verdict="MODIFY",
                    reason=f"catalyst flip: {cat.reason}",
                    modified_signal=flipped,
                )
            return FilterResult(
                verdict="REJECT",
                reason=f"catalyst conflict: {cat.reason} ({cat.confidence:.0%})",
            )

        if signal.action == Action.SELL and cat.direction == "BULLISH_CATALYST":
            if context.ltp and cat.confidence >= 0.75:
                sl  = round(context.ltp * 0.985, 2)
                tgt = round(context.ltp * 1.030, 2)
                flipped = Signal(
                    symbol=context.symbol,
                    action=Action.BUY,
                    entry_price=context.ltp,
                    stop_loss=sl,
                    target=tgt,
                    strategy="catalyst_long",
                    reason=f"Catalyst flip: {cat.reason}",
                )
                return FilterResult(
                    verdict="MODIFY",
                    reason=f"catalyst flip: {cat.reason}",
                    modified_signal=flipped,
                )
            return FilterResult(
                verdict="REJECT",
                reason=f"catalyst conflict: {cat.reason} ({cat.confidence:.0%})",
            )

        return FilterResult(verdict="PASS")
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_signal_pipeline.py -v
```
Expected: `14 passed`

- [ ] **Step 5: Commit**

```bash
git add execution/signal_pipeline.py tests/test_signal_pipeline.py
git commit -m "feat: add CatalystFilter to signal pipeline"
```

---

## Task 5: FundamentalsFilter

**Files:**
- Modify: `execution/signal_pipeline.py`
- Modify: `tests/test_signal_pipeline.py`

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/test_signal_pipeline.py

from execution.signal_pipeline import FundamentalsFilter


def _make_judgment(bias: str, confidence: float, summary: str = "test") -> MagicMock:
    j = MagicMock()
    j.bias = bias
    j.confidence = confidence
    j.summary = summary
    return j


class TestFundamentalsFilter:
    def test_no_judgment_passes(self):
        f = FundamentalsFilter()
        with patch("execution.signal_pipeline.get_fundamental_judgment",
                   return_value=None):
            result = f.evaluate(_make_signal(action=Action.BUY), _make_context())
        assert result.verdict == "PASS"

    def test_bearish_judgment_rejects_buy_at_threshold(self):
        f = FundamentalsFilter()
        with patch("execution.signal_pipeline.get_fundamental_judgment",
                   return_value=_make_judgment("BEARISH", 0.65)):
            result = f.evaluate(_make_signal(action=Action.BUY), _make_context())
        assert result.verdict == "REJECT"
        assert "fundamentals" in result.reason

    def test_bearish_judgment_below_threshold_passes_buy(self):
        f = FundamentalsFilter()
        with patch("execution.signal_pipeline.get_fundamental_judgment",
                   return_value=_make_judgment("BEARISH", 0.55)):
            result = f.evaluate(_make_signal(action=Action.BUY), _make_context())
        assert result.verdict == "PASS"

    def test_bullish_judgment_rejects_sell_at_threshold(self):
        f = FundamentalsFilter()
        with patch("execution.signal_pipeline.get_fundamental_judgment",
                   return_value=_make_judgment("BULLISH", 0.75)):
            result = f.evaluate(_make_signal(action=Action.SELL), _make_context())
        assert result.verdict == "REJECT"

    def test_catalyst_signal_skips_fundamentals_check(self):
        f = FundamentalsFilter()
        sig = _make_signal(action=Action.BUY, strategy="catalyst_long")
        with patch("execution.signal_pipeline.get_fundamental_judgment",
                   return_value=_make_judgment("BEARISH", 0.90)):
            result = f.evaluate(sig, _make_context())
        assert result.verdict == "PASS"
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_signal_pipeline.py::TestFundamentalsFilter -v 2>&1 | head -10
```
Expected: `ImportError`.

- [ ] **Step 3: Add `FundamentalsFilter` to `execution/signal_pipeline.py`**

Add this import at the top:

```python
from scheduler.watchlist import get_fundamental_judgment
```

Add the filter class after `CatalystFilter`:

```python
class FundamentalsFilter(SignalFilter):
    """
    Block signals that conflict with high-confidence fundamental analysis.

    Thresholds (different per direction — shorts need higher conviction):
      BUY vs BEARISH bias: confidence ≥ 0.60 → reject
      SELL vs BULLISH bias: confidence ≥ 0.70 → reject

    Catalyst-sourced signals (strategy starts with "catalyst_") bypass
    this check — the catalyst already overrides the technical signal.
    """
    name = "fund"

    def evaluate(self, signal: Signal, context: FilterContext) -> FilterResult:
        if signal.strategy.startswith("catalyst_"):
            return FilterResult(verdict="PASS")

        judgment = get_fundamental_judgment(context.symbol)
        if judgment is None:
            return FilterResult(verdict="PASS")

        if (
            signal.action == Action.BUY
            and judgment.bias == "BEARISH"
            and judgment.confidence >= 0.6
        ):
            return FilterResult(
                verdict="REJECT",
                reason=f"fundamentals: {judgment.summary}",
            )
        if (
            signal.action == Action.SELL
            and judgment.bias == "BULLISH"
            and judgment.confidence >= 0.7
        ):
            return FilterResult(
                verdict="REJECT",
                reason=f"fundamentals: {judgment.summary}",
            )
        return FilterResult(verdict="PASS")
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_signal_pipeline.py -v
```
Expected: `19 passed`

- [ ] **Step 5: Commit**

```bash
git add execution/signal_pipeline.py tests/test_signal_pipeline.py
git commit -m "feat: add FundamentalsFilter to signal pipeline"
```

---

## Task 6: RegimeFilter

**Files:**
- Modify: `execution/signal_pipeline.py`
- Modify: `tests/test_signal_pipeline.py`

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/test_signal_pipeline.py

from execution.signal_pipeline import RegimeFilter
from analysis.market_direction import MarketDirection
from analysis.regime_detector import MarketRegime


class TestRegimeFilter:
    def test_sell_rejected_on_trending_up_market(self):
        f = RegimeFilter()
        with patch("execution.signal_pipeline.get_market_direction",
                   return_value=MarketDirection.UP):
            with patch("execution.signal_pipeline.get_current_regime",
                       return_value=MarketRegime.TRENDING):
                result = f.evaluate(_make_signal(action=Action.SELL), _make_context())
        assert result.verdict == "REJECT"
        assert "regime" in result.reason

    def test_buy_rejected_on_trending_down_market(self):
        f = RegimeFilter()
        with patch("execution.signal_pipeline.get_market_direction",
                   return_value=MarketDirection.DOWN):
            with patch("execution.signal_pipeline.get_current_regime",
                       return_value=MarketRegime.TRENDING):
                result = f.evaluate(_make_signal(action=Action.BUY), _make_context())
        assert result.verdict == "REJECT"

    def test_sell_passes_on_trending_down_market(self):
        f = RegimeFilter()
        with patch("execution.signal_pipeline.get_market_direction",
                   return_value=MarketDirection.DOWN):
            with patch("execution.signal_pipeline.get_current_regime",
                       return_value=MarketRegime.TRENDING):
                result = f.evaluate(_make_signal(action=Action.SELL), _make_context())
        assert result.verdict == "PASS"

    def test_ranging_market_does_not_suppress_either_side(self):
        f = RegimeFilter()
        with patch("execution.signal_pipeline.get_market_direction",
                   return_value=MarketDirection.UP):
            with patch("execution.signal_pipeline.get_current_regime",
                       return_value=MarketRegime.RANGING):
                sell_result = f.evaluate(_make_signal(action=Action.SELL), _make_context())
                buy_result  = f.evaluate(_make_signal(action=Action.BUY),  _make_context())
        assert sell_result.verdict == "PASS"
        assert buy_result.verdict  == "PASS"
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_signal_pipeline.py::TestRegimeFilter -v 2>&1 | head -10
```
Expected: `ImportError`.

- [ ] **Step 3: Add `RegimeFilter` to `execution/signal_pipeline.py`**

Add these imports at the top:

```python
from analysis.market_direction import get_market_direction, MarketDirection
from analysis.regime_detector import get_current_regime, MarketRegime
```

Add the filter class after `FundamentalsFilter`:

```python
class RegimeFilter(SignalFilter):
    """
    Suppress counter-trend signals when the market is clearly trending.

    This covers the gap left by the VIX filter in RiskManager:
    VIX blocks BUYs on high fear but not SELLs on a bull trending day.

    Rules:
      SELL + market Trending UP   → REJECT (shorting into a bull trend)
      BUY  + market Trending DOWN → REJECT (buying into a bear trend)
    """
    name = "regime"

    def evaluate(self, signal: Signal, context: FilterContext) -> FilterResult:
        direction = get_market_direction()
        regime    = get_current_regime()

        if (
            signal.action == Action.SELL
            and direction == MarketDirection.UP
            and regime == MarketRegime.TRENDING
        ):
            return FilterResult(
                verdict="REJECT",
                reason=f"regime: {direction.value}+{regime.value}",
            )
        if (
            signal.action == Action.BUY
            and direction == MarketDirection.DOWN
            and regime == MarketRegime.TRENDING
        ):
            return FilterResult(
                verdict="REJECT",
                reason=f"regime: {direction.value}+{regime.value}",
            )
        return FilterResult(verdict="PASS")
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_signal_pipeline.py -v
```
Expected: `23 passed`

- [ ] **Step 5: Commit**

```bash
git add execution/signal_pipeline.py tests/test_signal_pipeline.py
git commit -m "feat: add RegimeFilter to signal pipeline"
```

---

## Task 7: DivergenceFilter

**Files:**
- Modify: `execution/signal_pipeline.py`
- Modify: `tests/test_signal_pipeline.py`

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/test_signal_pipeline.py

import pandas as pd
from analysis.nifty_correlation import DivergenceResult
from execution.signal_pipeline import DivergenceFilter


def _make_divergence(label: str) -> DivergenceResult:
    return DivergenceResult(
        nifty_chg_pct=1.2 if label == "LAGGING" else -1.2 if label == "LEADING" else 0.0,
        stock_chg_pct=0.1 if label == "LAGGING" else -0.1 if label == "LEADING" else 0.0,
        label=label,
        suppress_buy=label == "LAGGING",
        suppress_sell=label == "LEADING",
        amplify_sell=label == "LAGGING",
    )


class TestDivergenceFilter:
    def test_in_line_stock_passes_both_directions(self):
        f = DivergenceFilter()
        with patch("execution.signal_pipeline.get_divergence",
                   return_value=_make_divergence("IN_LINE")):
            buy_result  = f.evaluate(_make_signal(action=Action.BUY),  _make_context())
            sell_result = f.evaluate(_make_signal(action=Action.SELL), _make_context())
        assert buy_result.verdict  == "PASS"
        assert sell_result.verdict == "PASS"

    def test_lagging_stock_rejects_buy(self):
        f = DivergenceFilter()
        with patch("execution.signal_pipeline.get_divergence",
                   return_value=_make_divergence("LAGGING")):
            result = f.evaluate(_make_signal(action=Action.BUY), _make_context())
        assert result.verdict == "REJECT"
        assert "LAGGING" in result.reason

    def test_lagging_stock_passes_sell(self):
        # suppress_buy=True but amplify_sell=True — relative weakness confirms short
        f = DivergenceFilter()
        with patch("execution.signal_pipeline.get_divergence",
                   return_value=_make_divergence("LAGGING")):
            result = f.evaluate(_make_signal(action=Action.SELL), _make_context())
        assert result.verdict == "PASS"

    def test_leading_stock_rejects_sell(self):
        f = DivergenceFilter()
        with patch("execution.signal_pipeline.get_divergence",
                   return_value=_make_divergence("LEADING")):
            result = f.evaluate(_make_signal(action=Action.SELL), _make_context())
        assert result.verdict == "REJECT"
        assert "LEADING" in result.reason
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_signal_pipeline.py::TestDivergenceFilter -v 2>&1 | head -10
```
Expected: `ImportError`.

- [ ] **Step 3: Add `DivergenceFilter` to `execution/signal_pipeline.py`**

Add this import at the top:

```python
from analysis.nifty_correlation import get_divergence
```

Add the filter class after `RegimeFilter`:

```python
class DivergenceFilter(SignalFilter):
    """
    Suppress signals when a stock is diverging from the NIFTY index.

    Uses the pre-fetched NIFTY intraday % change stored in FilterContext
    so no extra network call is needed per symbol.

    Rules (from analysis/nifty_correlation.py):
      LAGGING + BUY  → REJECT  (stock not participating in rally — skip long)
      LEADING + SELL → REJECT  (stock holding up in sell-off — skip short)
      LAGGING + SELL → PASS    (relative weakness confirms the short)
    """
    name = "divergence"

    def evaluate(self, signal: Signal, context: FilterContext) -> FilterResult:
        result = get_divergence(context.symbol, context.df, context.nifty_chg)

        if result.suppress_buy and signal.action == Action.BUY:
            return FilterResult(
                verdict="REJECT",
                reason=(
                    f"LAGGING NIFTY {result.nifty_chg_pct:+.1f}% "
                    f"/ stock {result.stock_chg_pct:+.1f}%"
                ),
            )
        if result.suppress_sell and signal.action == Action.SELL:
            return FilterResult(
                verdict="REJECT",
                reason=(
                    f"LEADING NIFTY {result.nifty_chg_pct:+.1f}% "
                    f"/ stock {result.stock_chg_pct:+.1f}%"
                ),
            )
        return FilterResult(verdict="PASS")
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_signal_pipeline.py -v
```
Expected: `27 passed`

- [ ] **Step 5: Commit**

```bash
git add execution/signal_pipeline.py tests/test_signal_pipeline.py
git commit -m "feat: add DivergenceFilter to signal pipeline"
```

---

## Task 8: Wire pipeline into `signal_check()` and remove inline guards

This is the migration step. The pipeline is now complete with all 6 filters. Replace the inline guard blocks in `signal_check()` with a single `_pipeline.run()` call.

**Files:**
- Modify: `scheduler/job_runner.py`

- [ ] **Step 1: Add `_pipeline` singleton and imports to `job_runner.py`**

At the top of `scheduler/job_runner.py`, add to the existing imports:

```python
from execution.signal_pipeline import (
    SignalPipeline, FilterContext,
    DedupFilter, ShortSellingFilter, CatalystFilter,
    FundamentalsFilter, RegimeFilter, DivergenceFilter,
)
```

After the existing module-level singletons (around line 78), add:

```python
_pipeline: Optional[SignalPipeline] = None
```

- [ ] **Step 2: Initialise the pipeline in `setup()`**

At the end of the `setup()` function body (after the risk state restore block), add:

```python
    global _pipeline
    _pipeline = SignalPipeline([
        DedupFilter(),
        ShortSellingFilter(),
        CatalystFilter(),
        FundamentalsFilter(),
        RegimeFilter(),
        DivergenceFilter(),
    ])
    logger.info("SignalPipeline initialised with 6 filters")
```

- [ ] **Step 3: Replace inline guards in the strategy loop inside `signal_check()`**

Find the inner `for strategy in _strategies:` loop. Replace everything from `signal: Signal = strategy.generate_signal(...)` through the closing `except Exception as e: logger.warning(...)` with this:

```python
        for strategy in _strategies:
            try:
                signal: Signal = strategy.generate_signal(kite_sym, df)
                if signal.action == Action.HOLD:
                    continue

                # ── Pipeline: dedup, short-selling, catalyst, fundamentals,
                #              regime, divergence ─────────────────────────
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

                # ── Risk Manager: position sizing + time/capital gates ───
                # get_fundamental_judgment() is cached — zero network cost
                # to call again here for the sizing context it needs.
                _judgment = get_fundamental_judgment(kite_sym)
                decision = _risk_mgr.evaluate(approved, judgment=_judgment)
                if not decision.approved:
                    logger.debug(
                        f"Signal rejected [{kite_sym} / {strategy.name}]: "
                        f"{decision.reason}"
                    )
                    continue

                # ── Execute ──────────────────────────────────────────────
                placed = _order_mgr.execute_signal(decision.signal)
                if placed:
                    _risk_mgr.on_position_opened(kite_sym)
                    logger.info(
                        f"ORDER PLACED | {kite_sym} | {approved.action.value} "
                        f"| strategy={strategy.name} "
                        f"| entry={approved.entry_price:.2f} "
                        f"| sl={approved.stop_loss:.2f} "
                        f"| target={approved.target:.2f}"
                    )
                    _today_trades = _trade_log.get_today_trades() if _trade_log else []
                    _trade_num    = len(_today_trades) + 1
                    _day_pnl      = sum(t.get("net_pnl") or 0 for t in _today_trades)
                    try:
                        from config.adaptive import get_current_mode
                        _adp_mode = get_current_mode().value
                    except Exception:
                        _adp_mode = ""
                    get_notifier().notify_entry(
                        symbol=kite_sym,
                        action=approved.action.value,
                        price=approved.entry_price,
                        sl=approved.stop_loss,
                        target=approved.target,
                        strategy=strategy.name,
                        qty=decision.signal.quantity or 0,
                        trade_num=_trade_num,
                        day_pnl=_day_pnl,
                        adaptive_mode=_adp_mode,
                    )
                break  # one signal per symbol per cycle (first strategy wins)
            except Exception as e:
                logger.warning(f"Strategy error [{kite_sym} / {strategy.name}]: {e}")
```

- [ ] **Step 4: Remove the now-dead module-level dedup globals from `job_runner.py`**

Delete these three lines from `job_runner.py` (they were around line 121–123):

```python
import threading as _threading
_last_signal_key: set[tuple] = set()
_last_signal_lock = _threading.Lock()
```

Also remove the `import threading as _threading` line — `threading` is no longer needed in `job_runner.py` directly (it moved into `DedupFilter`).

- [ ] **Step 5: Run the full test suite**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: `272 passed` (or more, including the 27 new pipeline tests). Zero failures.

- [ ] **Step 6: Verify `signal_check()` loop is compact**

```bash
python -c "
import ast, sys
src = open('scheduler/job_runner.py').read()
tree = ast.parse(src)
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == 'signal_check':
        print(f'signal_check: lines {node.lineno}–{node.end_lineno} ({node.end_lineno - node.lineno} lines)')
"
```
Expected: the function spans fewer lines than before (~120 lines or less, down from ~220).

- [ ] **Step 7: Commit**

```bash
git add scheduler/job_runner.py
git commit -m "refactor: wire SignalPipeline into signal_check(), remove inline guards

All 6 filter stages (dedup, short-sell, catalyst, fundamentals, regime,
divergence) now run through SignalPipeline.run(). Every rejection emits
a [PIPELINE] audit log line with filter name and reason. Inline guard
blocks and module-level _last_signal_key/_last_signal_lock removed.

Closes: 2026-04-11-signal-pipeline-design.md"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| `FilterContext`, `FilterResult`, `SignalFilter` ABC | Task 1 |
| `SignalPipeline.run()` with fail-open per-filter | Task 1 |
| `_log_pipeline` audit line per signal | Task 1 |
| `DedupFilter` with lock | Task 2 |
| `ShortSellingFilter` | Task 3 |
| `CatalystFilter` with MODIFY | Task 4 |
| `FundamentalsFilter` with catalyst bypass | Task 5 |
| `RegimeFilter` | Task 6 |
| `DivergenceFilter` (new) | Task 7 |
| `signal_check()` loop replacement | Task 8 |
| Remove `_last_signal_key` / `_last_signal_lock` | Task 8 |
| `_pipeline` initialised in `setup()` | Task 8 |
| 272-test suite passes throughout | Task 8 step 5 |

No gaps found.

**Type consistency check:**
- `FilterContext` fields (`symbol`, `df`, `ltp`, `nifty_chg`, `candle_ts`) used consistently in all filter `evaluate()` calls — confirmed.
- `FilterResult.modified_signal` is `Optional[Signal]` — `CatalystFilter` always sets it before returning `MODIFY` — confirmed.
- `get_divergence(symbol, symbol_df, nifty_chg)` signature matches `analysis/nifty_correlation.py` — confirmed.
- `_risk_mgr.evaluate(signal, judgment=...)` matches `risk/risk_manager.py:146` — confirmed.
- `_order_mgr.execute_signal(decision.signal)` matches `execution/order_manager.py:100` — confirmed.
