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


# ── Task 2 tests ──────────────────────────────────────────────────────

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
