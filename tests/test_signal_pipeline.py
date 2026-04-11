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
