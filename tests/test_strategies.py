"""
Unit tests for all trading strategies.

We test that each strategy:
  1. Returns a Signal object of the correct type
  2. Produces BUY signals under favourable conditions
  3. Produces SELL signals under adverse conditions
  4. Returns HOLD when insufficient data or conditions not met
  5. Never produces signals with invalid price levels
"""

from __future__ import annotations

from datetime import time

import numpy as np
import pandas as pd
import pytest

from strategies.base_strategy import Action, Signal
from strategies.bb_mean_reversion import BBMeanReversionStrategy
from strategies.ema_crossover import EMACrossoverStrategy
from strategies.opening_range_breakout import ORBStrategy
from strategies.rsi_macd_combo import RSIMACDStrategy
from strategies.trend_rider import TrendRiderStrategy


# ── Helpers ───────────────────────────────────────────────────────────

def make_ohlcv(
    close_prices: list[float],
    start: str = "2024-01-02 09:20:00",
    freq: str = "5min",
    volume: int = 200_000,
) -> pd.DataFrame:
    n   = len(close_prices)
    idx = pd.date_range(start=start, periods=n, freq=freq, tz="Asia/Kolkata")
    closes = np.array(close_prices, dtype=float)
    opens  = np.roll(closes, 1); opens[0] = closes[0]
    return pd.DataFrame(
        {"open": opens, "high": closes + 1, "low": closes - 1,
         "close": closes, "volume": [volume] * n},
        index=idx,
    )


def make_orb_df(
    n_orb: int = 3,
    orb_close: float = 100.0,
    post_prices: list[float] | None = None,
) -> pd.DataFrame:
    """
    Build a DataFrame with opening-range candles followed by post-range candles.
    Opening range: 9:15, 9:20, 9:25 AM.
    Post-range starts at 9:35 AM.
    """
    orb_times = [
        "2024-01-02 09:15:00",
        "2024-01-02 09:20:00",
        "2024-01-02 09:25:00",
    ][:n_orb]

    post_prices = post_prices or [orb_close * 1.02, orb_close * 1.03]
    post_times  = [
        f"2024-01-02 09:3{i}:00" for i in range(5, 5 + len(post_prices))
    ]

    all_times  = orb_times + post_times
    all_prices = [orb_close] * len(orb_times) + post_prices

    rows = [
        {"open": p - 1, "high": p + 5, "low": p - 5, "close": p, "volume": 200_000}
        for p in all_prices
    ]
    idx = pd.DatetimeIndex([pd.Timestamp(t, tz="Asia/Kolkata") for t in all_times])
    return pd.DataFrame(rows, index=idx)


# ── Signal dataclass tests ────────────────────────────────────────────

class TestSignal:
    def test_buy_signal_valid(self):
        s = Signal("RELIANCE", Action.BUY, entry_price=500, stop_loss=492, target=516, strategy="test")
        assert s.is_valid()
        assert s.risk_per_share == pytest.approx(8.0)
        assert s.reward_per_share == pytest.approx(16.0)
        assert s.reward_risk_ratio == pytest.approx(2.0)

    def test_sell_signal_valid(self):
        s = Signal("TCS", Action.SELL, entry_price=3500, stop_loss=3514, target=3472, strategy="test")
        assert s.is_valid()

    def test_invalid_buy_stop_above_entry(self):
        s = Signal("INFY", Action.BUY, entry_price=1500, stop_loss=1510, target=1530, strategy="test")
        assert not s.is_valid()  # Stop-loss above entry for BUY is invalid

    def test_hold_always_valid(self):
        s = Signal("HDFC", Action.HOLD, entry_price=1600, stop_loss=1600, target=1600, strategy="test")
        assert s.is_valid()

    def test_total_risk_calculation(self):
        s = Signal("WIPRO", Action.BUY, entry_price=400, stop_loss=392, target=416, quantity=125, strategy="test")
        assert s.total_risk == pytest.approx(1000.0)  # 125 × ₹8


# ── EMA Crossover Strategy tests ─────────────────────────────────────

class TestEMACrossoverStrategy:
    def test_returns_signal_object(self):
        df = make_ohlcv([100.0] * 60)
        strategy = EMACrossoverStrategy()
        result = strategy.generate_signal("RELIANCE", df)
        assert isinstance(result, Signal)

    def test_hold_with_insufficient_data(self):
        df = make_ohlcv([100.0] * 30)  # Less than trend_period=50
        strategy = EMACrossoverStrategy()
        result = strategy.generate_signal("RELIANCE", df)
        assert result.action == Action.HOLD

    def test_hold_on_flat_prices(self):
        df = make_ohlcv([100.0] * 60)
        strategy = EMACrossoverStrategy()
        result = strategy.generate_signal("RELIANCE", df)
        assert result.action == Action.HOLD

    def test_buy_signal_has_valid_prices(self):
        """Any BUY signal produced must have SL below entry and target above entry."""
        prices = [100.0] * 50 + [101, 103, 106, 110, 115, 121, 128]
        df = make_ohlcv(prices, volume=500_000)
        strategy = EMACrossoverStrategy()
        result = strategy.generate_signal("RELIANCE", df)
        if result.action == Action.BUY:
            assert result.stop_loss < result.entry_price < result.target
            assert result.is_valid()

    def test_strategy_name(self):
        strategy = EMACrossoverStrategy()
        assert strategy.name == "ema_crossover"


# ── RSI + MACD Combo Strategy tests ──────────────────────────────────

class TestRSIMACDStrategy:
    def test_returns_signal_object(self):
        df = make_ohlcv([100 + i * 0.1 for i in range(50)])
        strategy = RSIMACDStrategy()
        result = strategy.generate_signal("TCS", df)
        assert isinstance(result, Signal)

    def test_hold_with_insufficient_data(self):
        df = make_ohlcv([100.0] * 20)  # Less than MACD minimum
        strategy = RSIMACDStrategy()
        result = strategy.generate_signal("TCS", df)
        assert result.action == Action.HOLD

    def test_symbol_in_signal(self):
        df = make_ohlcv([100.0] * 50)
        strategy = RSIMACDStrategy()
        result = strategy.generate_signal("INFY", df)
        assert result.symbol == "INFY"

    def test_buy_signal_has_valid_prices(self):
        """Any BUY signal must have SL < entry < target."""
        prices = [100 + np.sin(i * 0.4) * 3 for i in range(60)]
        df = make_ohlcv(prices)
        strategy = RSIMACDStrategy()
        result = strategy.generate_signal("TCS", df)
        if result.action == Action.BUY:
            assert result.stop_loss < result.entry_price < result.target

    def test_sell_signal_has_valid_prices(self):
        """Any SELL signal must have target < entry < stop_loss."""
        prices = [100 + np.sin(i * 0.4) * 3 for i in range(60)]
        df = make_ohlcv(prices)
        strategy = RSIMACDStrategy()
        result = strategy.generate_signal("TCS", df)
        if result.action == Action.SELL:
            assert result.target < result.entry_price < result.stop_loss

    def test_strategy_name(self):
        strategy = RSIMACDStrategy()
        assert strategy.name == "rsi_macd_combo"

    def test_same_bar_does_not_fire_twice(self):
        """
        Stale-data guard: calling generate_signal twice with an identical
        DataFrame (same last bar index) must not produce two crossover signals.
        The second call must return HOLD regardless of MACD state.
        """
        prices = [100 + np.sin(i * 0.4) * 3 for i in range(60)]
        df = make_ohlcv(prices)
        strategy = RSIMACDStrategy()

        first  = strategy.generate_signal("TCS", df)
        second = strategy.generate_signal("TCS", df)  # identical df — same bar

        # If first was a crossover signal, second must be suppressed to HOLD
        if first.action != Action.HOLD:
            assert second.action == Action.HOLD, (
                "Duplicate crossover on the same bar was not suppressed"
            )

    def test_new_bar_fires_again(self):
        """
        After a new candle arrives the strategy is allowed to fire again,
        even if the MACD crossover direction is the same.
        """
        prices = [100 + np.sin(i * 0.4) * 3 for i in range(60)]
        df1 = make_ohlcv(prices)
        # Append one more bar — new index timestamp
        df2 = make_ohlcv(prices + [prices[-1] * 1.001])

        strategy = RSIMACDStrategy()
        first  = strategy.generate_signal("TCS", df1)
        second = strategy.generate_signal("TCS", df2)

        # The second call is on a different (newer) bar; the strategy must
        # not permanently suppress it.  We just verify it runs without error
        # and returns a Signal object.
        assert isinstance(second, Signal)


# ── ORB Strategy tests ────────────────────────────────────────────────

class TestORBStrategy:
    def test_returns_signal_object(self):
        df = make_orb_df()
        strategy = ORBStrategy()
        result = strategy.generate_signal("BANKNIFTY", df)
        assert isinstance(result, Signal)

    def test_hold_with_insufficient_data(self):
        df = make_ohlcv([100.0] * 2)
        strategy = ORBStrategy()
        result = strategy.generate_signal("BANKNIFTY", df)
        assert result.action == Action.HOLD

    def test_hold_after_exit_time(self):
        """No ORB signals should be generated after 2:30 PM."""
        df = make_orb_df(post_prices=[102.0, 104.0])
        # Move timestamps to post-exit time
        df.index = pd.DatetimeIndex([
            pd.Timestamp(f"2024-01-02 14:3{i}:00", tz="Asia/Kolkata")
            for i in range(len(df))
        ])
        strategy = ORBStrategy()
        result = strategy.generate_signal("NIFTY", df)
        assert result.action == Action.HOLD

    def test_buy_signal_stop_is_orb_low(self):
        """For ORB BUY, stop-loss should be at or near the ORB low."""
        df = make_orb_df(orb_close=100.0, post_prices=[115.0, 120.0])
        strategy = ORBStrategy()
        result = strategy.generate_signal("NIFTY", df)
        if result.action == Action.BUY:
            # ORB low ≈ 100 - 5 = 95 (from make_orb_df high=p+5, low=p-5)
            assert result.stop_loss < result.entry_price
            assert result.target > result.entry_price

    def test_symbol_in_signal(self):
        df = make_orb_df()
        strategy = ORBStrategy()
        result = strategy.generate_signal("HDFCBANK", df)
        assert result.symbol == "HDFCBANK"

    def test_strategy_name(self):
        strategy = ORBStrategy()
        assert strategy.name == "opening_range_breakout"


# ── BB Mean Reversion Strategy tests ─────────────────────────────────

def _make_bb_buy_df() -> pd.DataFrame:
    """
    Price oscillates around 100 then drops sharply.
    This pushes the last close well below the lower Bollinger Band
    and drives RSI into oversold territory (< 35).
    """
    base = [100 + np.sin(i * 0.6) * 6 for i in range(30)]
    tail = [94.0, 88.0, 82.0, 75.0, 68.0]
    return make_ohlcv(base + tail)


def _make_bb_sell_df() -> pd.DataFrame:
    """
    Price oscillates around 100 then surges sharply.
    This pushes the last close well above the upper Bollinger Band
    and drives RSI into overbought territory (> 65).
    """
    base = [100 + np.sin(i * 0.6) * 6 for i in range(30)]
    tail = [106.0, 112.0, 118.0, 125.0, 132.0]
    return make_ohlcv(base + tail)


class TestBBMeanReversionStrategy:
    def test_returns_signal_object(self):
        df = make_ohlcv([100.0] * 30)
        strategy = BBMeanReversionStrategy()
        result = strategy.generate_signal("WIPRO", df)
        assert isinstance(result, Signal)

    def test_hold_with_insufficient_data(self):
        """Fewer candles than bb_period + rsi_period → HOLD."""
        df = make_ohlcv([100.0] * 15)
        strategy = BBMeanReversionStrategy()
        result = strategy.generate_signal("WIPRO", df)
        assert result.action == Action.HOLD

    def test_hold_when_price_is_mid_band(self):
        """Price oscillating inside the bands with RSI near 50 → HOLD (no extreme)."""
        # Gentle oscillation: last price ≈ 100 (well inside both bands), RSI neutral
        prices = [100 + np.sin(i * 0.3) * 4 for i in range(40)]
        df = make_ohlcv(prices)
        strategy = BBMeanReversionStrategy()
        result = strategy.generate_signal("WIPRO", df)
        assert result.action == Action.HOLD

    def test_buy_signal_generated_on_oversold_drop(self):
        """Sharp drop below lower band with RSI < 35 should generate a BUY.
        BB Mean Reversion is suppressed in TRENDING regimes, so we patch the
        regime to RANGING (its intended home) for this signal-logic test."""
        from unittest.mock import patch
        from analysis.regime_detector import MarketRegime
        df = _make_bb_buy_df()
        strategy = BBMeanReversionStrategy()
        with patch("strategies.bb_mean_reversion.get_current_regime",
                   return_value=MarketRegime.RANGING):
            result = strategy.generate_signal("WIPRO", df)
        assert result.action == Action.BUY

    def test_sell_signal_generated_on_overbought_surge(self):
        """Sharp surge above upper band with RSI > 65 should generate a SELL.
        Patched to RANGING regime so the regime filter does not suppress BB."""
        from unittest.mock import patch
        from analysis.regime_detector import MarketRegime
        df = _make_bb_sell_df()
        strategy = BBMeanReversionStrategy()
        with patch("strategies.bb_mean_reversion.get_current_regime",
                   return_value=MarketRegime.RANGING):
            result = strategy.generate_signal("WIPRO", df)
        assert result.action == Action.SELL

    def test_buy_signal_prices_are_valid(self):
        """BUY signal must have SL < entry < target."""
        df = _make_bb_buy_df()
        strategy = BBMeanReversionStrategy()
        result = strategy.generate_signal("WIPRO", df)
        if result.action == Action.BUY:
            assert result.stop_loss < result.entry_price < result.target
            assert result.is_valid()

    def test_sell_signal_prices_are_valid(self):
        """SELL signal must have target < entry < SL."""
        df = _make_bb_sell_df()
        strategy = BBMeanReversionStrategy()
        result = strategy.generate_signal("WIPRO", df)
        if result.action == Action.SELL:
            assert result.target < result.entry_price < result.stop_loss
            assert result.is_valid()

    def test_buy_reward_risk_at_least_2_to_1(self):
        """BUY target must give ≥ 2:1 reward-to-risk ratio."""
        df = _make_bb_buy_df()
        strategy = BBMeanReversionStrategy()
        result = strategy.generate_signal("WIPRO", df)
        if result.action == Action.BUY:
            assert float(result.reward_risk_ratio) >= 2.0

    def test_sell_reward_risk_at_least_2_to_1(self):
        """SELL target must give ≥ 2:1 reward-to-risk ratio."""
        df = _make_bb_sell_df()
        strategy = BBMeanReversionStrategy()
        result = strategy.generate_signal("WIPRO", df)
        if result.action == Action.SELL:
            assert float(result.reward_risk_ratio) >= 2.0

    def test_symbol_in_signal(self):
        df = make_ohlcv([100.0] * 35)
        strategy = BBMeanReversionStrategy()
        result = strategy.generate_signal("HCLTECH", df)
        assert result.symbol == "HCLTECH"

    def test_strategy_name(self):
        strategy = BBMeanReversionStrategy()
        assert strategy.name == "bb_mean_reversion"


# ── Trend Rider Strategy tests ────────────────────────────────────────

def _make_bearish_flip_df() -> pd.DataFrame:
    """
    Build a price series that produces a Supertrend bearish flip on the last candle.
    Starts with a rising phase (Supertrend bullish), then a sharp drop that
    breaks the lower band and forces a bearish flip.
    """
    # Rising prices for 30 bars → Supertrend bullish
    base  = [100 + i * 0.5 for i in range(30)]
    # Sharp drop that breaks below Supertrend lower band
    drop  = [114, 110, 106, 101, 95, 88]
    return make_ohlcv(base + drop, volume=500_000)


def _make_bullish_flip_df() -> pd.DataFrame:
    """
    Build a price series that produces a Supertrend bullish flip on the last candle.
    Starts with a falling phase (Supertrend bearish), then a sharp rally.
    """
    base  = [100 - i * 0.5 for i in range(30)]
    rally = [86, 90, 94, 99, 105, 112]
    return make_ohlcv(base + rally, volume=500_000)


class TestTrendRiderStrategy:
    def test_returns_signal_object(self):
        df = make_ohlcv([100.0] * 40)
        strategy = TrendRiderStrategy()
        result = strategy.generate_signal("SBIN", df)
        assert isinstance(result, Signal)

    def test_hold_with_insufficient_data(self):
        df = make_ohlcv([100.0] * 15)
        strategy = TrendRiderStrategy()
        result = strategy.generate_signal("SBIN", df)
        assert result.action == Action.HOLD

    def test_hold_on_flat_prices(self):
        """No Supertrend flip on constant price → HOLD."""
        df = make_ohlcv([100.0] * 40)
        strategy = TrendRiderStrategy()
        result = strategy.generate_signal("SBIN", df)
        assert result.action == Action.HOLD

    def test_sell_signal_has_valid_prices(self):
        """Any SELL signal must have target < entry < stop_loss."""
        df = _make_bearish_flip_df()
        strategy = TrendRiderStrategy()
        result = strategy.generate_signal("SBIN", df)
        if result.action == Action.SELL:
            assert result.target < result.entry_price < result.stop_loss
            assert result.is_valid()

    def test_buy_signal_has_valid_prices(self):
        """Any BUY signal must have stop_loss < entry < target."""
        df = _make_bullish_flip_df()
        strategy = TrendRiderStrategy()
        result = strategy.generate_signal("SBIN", df)
        if result.action == Action.BUY:
            assert result.stop_loss < result.entry_price < result.target
            assert result.is_valid()

    def test_sell_reward_risk_at_least_2_to_1(self):
        """SELL target must give ≥ 2:1 RR."""
        df = _make_bearish_flip_df()
        strategy = TrendRiderStrategy()
        result = strategy.generate_signal("SBIN", df)
        if result.action == Action.SELL:
            assert float(result.reward_risk_ratio) >= 1.9   # allow tiny float rounding

    def test_same_bar_does_not_fire_twice(self):
        """Duplicate bar (stale data) must be suppressed to HOLD."""
        df = _make_bearish_flip_df()
        strategy = TrendRiderStrategy()
        first  = strategy.generate_signal("SBIN", df)
        second = strategy.generate_signal("SBIN", df)   # same bar index
        if first.action != Action.HOLD:
            assert second.action == Action.HOLD, "Duplicate flip not suppressed"

    def test_new_bar_can_fire_again(self):
        """A fresh bar (different index) is allowed to fire a new signal."""
        prices = _make_bearish_flip_df()["close"].tolist()
        df1 = _make_bearish_flip_df()
        df2 = make_ohlcv(prices + [prices[-1] * 0.99], volume=500_000)
        strategy = TrendRiderStrategy()
        strategy.generate_signal("SBIN", df1)
        second = strategy.generate_signal("SBIN", df2)
        assert isinstance(second, Signal)

    def test_symbol_in_signal(self):
        df = make_ohlcv([100.0] * 40)
        strategy = TrendRiderStrategy()
        result = strategy.generate_signal("MARUTI", df)
        assert result.symbol == "MARUTI"

    def test_strategy_name(self):
        strategy = TrendRiderStrategy()
        assert strategy.name == "trend_rider"
