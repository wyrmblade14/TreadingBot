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


# ── Task 3 tests ──────────────────────────────────────────────────────

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


# ── Task 4 tests ──────────────────────────────────────────────────────

from unittest.mock import MagicMock
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
        # CatalystFilter catches its own exceptions and returns PASS
        assert result.verdict == "PASS"


# ── Task 5 tests ──────────────────────────────────────────────────────

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


# ── Task 6 tests ──────────────────────────────────────────────────────

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


# ── Task 7 tests — DivergenceFilter ───────────────────────────────────

from unittest.mock import patch
from execution.signal_pipeline import DivergenceFilter
from analysis.nifty_correlation import DivergenceResult


def _lagging() -> DivergenceResult:
    return DivergenceResult(
        nifty_chg_pct=1.2, stock_chg_pct=0.1,
        label="LAGGING", suppress_buy=True, suppress_sell=False, amplify_sell=True,
    )


def _leading() -> DivergenceResult:
    return DivergenceResult(
        nifty_chg_pct=-1.1, stock_chg_pct=-0.1,
        label="LEADING", suppress_buy=False, suppress_sell=True, amplify_sell=False,
    )


def _in_line() -> DivergenceResult:
    return DivergenceResult(
        nifty_chg_pct=0.5, stock_chg_pct=0.4,
        label="IN_LINE", suppress_buy=False, suppress_sell=False, amplify_sell=False,
    )


class TestDivergenceFilter:
    def test_lagging_rejects_buy(self):
        f = DivergenceFilter()
        with patch("execution.signal_pipeline.get_divergence", return_value=_lagging()):
            result = f.evaluate(_make_signal(action=Action.BUY), _make_context())
        assert result.verdict == "REJECT"
        assert "divergence" in result.reason

    def test_lagging_passes_sell(self):
        """LAGGING stock + SELL = relative-weakness short — should pass."""
        f = DivergenceFilter()
        with patch("execution.signal_pipeline.get_divergence", return_value=_lagging()):
            result = f.evaluate(_make_signal(action=Action.SELL), _make_context())
        assert result.verdict == "PASS"

    def test_leading_rejects_sell(self):
        f = DivergenceFilter()
        with patch("execution.signal_pipeline.get_divergence", return_value=_leading()):
            result = f.evaluate(_make_signal(action=Action.SELL), _make_context())
        assert result.verdict == "REJECT"
        assert "divergence" in result.reason

    def test_in_line_passes_both_sides(self):
        f = DivergenceFilter()
        with patch("execution.signal_pipeline.get_divergence", return_value=_in_line()):
            buy  = f.evaluate(_make_signal(action=Action.BUY),  _make_context())
            sell = f.evaluate(_make_signal(action=Action.SELL), _make_context())
        assert buy.verdict  == "PASS"
        assert sell.verdict == "PASS"
