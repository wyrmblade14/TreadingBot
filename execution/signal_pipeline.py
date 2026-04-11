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
from dataclasses import dataclass
from typing import Optional

import pandas as pd
from loguru import logger

from analysis.catalyst_scanner import get_todays_catalysts
from config.settings import SHORT_SELLING_ENABLED
from scheduler.watchlist import get_fundamental_judgment
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
        f"[PIPELINE] {context.symbol:<10} {signal.action.value:<4} | "
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


class ShortSellingFilter(SignalFilter):
    """Reject SELL signals when short selling is disabled in config."""
    name = "short"

    def evaluate(self, signal: Signal, context: FilterContext) -> FilterResult:
        if signal.action == Action.SELL and not SHORT_SELLING_ENABLED:
            return FilterResult(verdict="REJECT", reason="short selling disabled")
        return FilterResult(verdict="PASS")


class CatalystFilter(SignalFilter):
    """
    Block or flip signals that conflict with a high-confidence news catalyst.

    Rules (confidence thresholds):
      ≥ 0.70: reject the conflicting signal
      ≥ 0.75: also flip to trade WITH the catalyst (MODIFY)

    Flip sizing: 1.5% SL / 3.0% target = 2:1 RR so RiskManager's
    minimum-RR check always passes.

    Fails open — any data error returns PASS.
    """
    name = "catalyst"

    def evaluate(self, signal: Signal, context: FilterContext) -> FilterResult:
        try:
            summary = get_todays_catalysts()
        except Exception:
            return FilterResult(verdict="PASS")

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
