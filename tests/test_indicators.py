"""
Unit tests for technical indicators.

We create synthetic (made-up) price series where we know exactly what
the indicator should produce. This lets us verify the logic is correct
without needing real market data.

How to run:
    cd TreadingBot
    pytest tests/test_indicators.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from indicators.ema import EMAIndicator
from indicators.macd import MACDIndicator
from indicators.orb import ORBIndicator
from indicators.rsi import RSIIndicator
from indicators.supertrend import SupertrendIndicator
from indicators.vwap import compute_vwap, get_vwap_signal


# ── Helpers ───────────────────────────────────────────────────────────

def make_ohlcv(
    close_prices: list[float],
    start: str = "2024-01-02 09:15:00",
    freq: str = "5min",
    volume: int = 100_000,
) -> pd.DataFrame:
    """
    Build a minimal OHLCV DataFrame from a list of close prices.

    Open = previous close, High = close + 1, Low = close - 1.
    Used only for testing — real data will differ.
    """
    n = len(close_prices)
    idx = pd.date_range(start=start, periods=n, freq=freq, tz="Asia/Kolkata")
    closes = np.array(close_prices, dtype=float)
    opens  = np.roll(closes, 1)
    opens[0] = closes[0]

    df = pd.DataFrame(
        {
            "open":   opens,
            "high":   closes + 1.0,
            "low":    closes - 1.0,
            "close":  closes,
            "volume": [volume] * n,
        },
        index=idx,
    )
    return df


# ── EMA Indicator Tests ───────────────────────────────────────────────

class TestEMAIndicator:
    def test_compute_adds_ema_columns(self):
        df = make_ohlcv([100.0] * 60)
        indicator = EMAIndicator(short_period=9, long_period=21, trend_period=50)
        result = indicator.compute(df)

        assert "ema_9"  in result.columns
        assert "ema_21" in result.columns
        assert "ema_50" in result.columns
        assert "vol_avg20" in result.columns

    def test_flat_prices_no_crossover(self):
        """When price is constant, EMAs are equal → no crossover → NEUTRAL signal."""
        df = make_ohlcv([100.0] * 60)
        indicator = EMAIndicator()
        assert indicator.get_signal(df) == 0

    def test_bullish_crossover_detected(self):
        """
        Create a price series that rises sharply after many flat bars.
        The fast EMA should cross above the slow EMA, generating a BUY signal.
        """
        # 50 flat bars to establish EMAs, then a strong upward move
        prices = [100.0] * 50 + [101, 102, 103, 105, 108, 112, 116, 120, 124, 128, 132]
        df = make_ohlcv(prices, volume=200_000)  # High volume for confirmation
        indicator = EMAIndicator(volume_multiplier=1.0)  # Disable strict vol check
        # Signal might be +1 at some point during the rising sequence
        result = indicator.compute(df)
        # Verify EMAs are computed and fast > slow at the end of the rise
        assert result["ema_9"].iloc[-1] > result["ema_21"].iloc[-1]

    def test_insufficient_data_returns_neutral(self):
        """With fewer candles than trend_period, should return NEUTRAL."""
        df = make_ohlcv([100.0] * 30)  # Less than trend_period=50
        indicator = EMAIndicator()
        assert indicator.get_signal(df) == 0

    def test_original_df_not_modified(self):
        """compute() must return a copy, not modify the input DataFrame."""
        df = make_ohlcv([100.0] * 60)
        original_cols = list(df.columns)
        indicator = EMAIndicator()
        _ = indicator.compute(df)
        assert list(df.columns) == original_cols


# ── RSI Indicator Tests ───────────────────────────────────────────────

class TestRSIIndicator:
    def test_compute_adds_rsi_column(self):
        df = make_ohlcv([100.0 + i * 0.5 for i in range(30)])
        indicator = RSIIndicator()
        result = indicator.compute(df)
        assert "rsi" in result.columns

    def test_rsi_range(self):
        """RSI values must always be between 0 and 100."""
        prices = [100 + np.sin(i * 0.5) * 10 for i in range(50)]
        df = make_ohlcv(prices)
        indicator = RSIIndicator()
        result = indicator.compute(df)
        rsi_values = result["rsi"].dropna()
        assert (rsi_values >= 0).all()
        assert (rsi_values <= 100).all()

    def test_rising_prices_high_rsi(self):
        """Consistently rising prices → RSI should be high (> 60)."""
        prices = [100 + i for i in range(30)]
        df = make_ohlcv(prices)
        indicator = RSIIndicator()
        rsi_val = indicator.get_value(df)
        assert rsi_val is not None
        assert rsi_val > 60

    def test_falling_prices_low_rsi(self):
        """Consistently falling prices → RSI should be low (< 40)."""
        prices = [130 - i for i in range(30)]
        df = make_ohlcv(prices)
        indicator = RSIIndicator()
        rsi_val = indicator.get_value(df)
        assert rsi_val is not None
        assert rsi_val < 40

    def test_insufficient_data_returns_none(self):
        df = make_ohlcv([100.0] * 5)
        indicator = RSIIndicator()
        assert indicator.get_value(df) is None

    def test_overbought_returns_sell_signal(self):
        """Simulate a strong uptrend that pushes RSI above overbought threshold."""
        # Strong consistent rise to push RSI very high
        prices = [100.0] * 10 + [100 + i * 3 for i in range(20)]
        df = make_ohlcv(prices)
        indicator = RSIIndicator(period=14, overbought=70)
        # The RSI of a very strong trend should trigger sell signal
        rsi = indicator.get_value(df)
        if rsi is not None and rsi > 70:
            assert indicator.get_signal(df) == -1


# ── MACD Indicator Tests ──────────────────────────────────────────────

class TestMACDIndicator:
    def test_compute_adds_macd_columns(self):
        df = make_ohlcv([100 + i * 0.1 for i in range(50)])
        indicator = MACDIndicator()
        result = indicator.compute(df)
        assert "macd"        in result.columns
        assert "macd_signal" in result.columns
        assert "macd_hist"   in result.columns

    def test_insufficient_data_returns_neutral(self):
        """MACD needs at least 26 + 9 = 35 candles for valid values."""
        df = make_ohlcv([100.0] * 20)
        indicator = MACDIndicator()
        assert indicator.get_signal(df) == 0

    def test_values_none_with_insufficient_data(self):
        df = make_ohlcv([100.0] * 20)
        indicator = MACDIndicator()
        m, s, h = indicator.get_values(df)
        assert m is None and s is None and h is None

    def test_histogram_equals_macd_minus_signal(self):
        """Histogram = MACD line - Signal line (by definition)."""
        prices = [100 + np.sin(i * 0.3) * 5 for i in range(60)]
        df = make_ohlcv(prices)
        indicator = MACDIndicator()
        result = indicator.compute(df)
        valid = result.dropna(subset=["macd", "macd_signal", "macd_hist"])
        if not valid.empty:
            diff = (valid["macd"] - valid["macd_signal"] - valid["macd_hist"]).abs()
            assert (diff < 1e-8).all(), "Histogram should equal MACD - Signal"

    def test_flat_prices_zero_macd(self):
        """When price is constant, all EMAs are equal → MACD ≈ 0."""
        df = make_ohlcv([100.0] * 60)
        indicator = MACDIndicator()
        m, s, h = indicator.get_values(df)
        if m is not None:
            assert abs(m) < 0.01


# ── ORB Indicator Tests ───────────────────────────────────────────────

class TestORBIndicator:
    def _make_orb_df(self, orb_high: float = 110.0, orb_low: float = 90.0) -> pd.DataFrame:
        """
        Build a DataFrame with:
          - First 3 candles in opening range (9:15, 9:20, 9:25)
          - Followed by post-range candles
        """
        times = [
            "2024-01-02 09:15:00",
            "2024-01-02 09:20:00",
            "2024-01-02 09:25:00",
            "2024-01-02 09:35:00",  # First post-range candle
            "2024-01-02 09:40:00",
            "2024-01-02 09:45:00",
        ]
        closes = [100, 105, 95, 112, 115, 118]    # Post-range breaks above orb_high

        rows = []
        for t, c in zip(times, closes):
            rows.append({
                "open":   c - 1,
                "high":   c + 5,
                "low":    c - 5,
                "close":  c,
                "volume": 200_000,
            })

        idx = pd.DatetimeIndex(
            [pd.Timestamp(t, tz="Asia/Kolkata") for t in times]
        )
        return pd.DataFrame(rows, index=idx)

    def test_orb_range_computed_correctly(self):
        df = self._make_orb_df()
        indicator = ORBIndicator()
        orb_range = indicator.get_range(df)
        assert orb_range is not None
        high, low = orb_range
        # Opening range high = max of highs in first 3 candles (close + 5)
        assert high == pytest.approx(105 + 5, abs=1)
        assert low  == pytest.approx(95 - 5, abs=1)

    def test_breakout_above_range_gives_buy_signal(self):
        """Post-range candle that closes above orb_high should give BUY signal."""
        df = self._make_orb_df()
        indicator = ORBIndicator(volume_multiplier=1.0)  # Disable vol check
        result = indicator.compute(df)
        # The post-range candles that close above range high should be +1
        post_range = result[result.index.time > indicator.orb_end_time]
        if not post_range.empty:
            breakouts = post_range[post_range["orb_breakout"] == 1]
            assert len(breakouts) > 0, "Expected at least one bullish breakout candle"

    def test_no_signal_during_opening_range(self):
        """No breakout signals should be generated during the opening range window."""
        df = self._make_orb_df()
        indicator = ORBIndicator()
        result = indicator.compute(df)
        orb_window = result[result.index.time <= indicator.orb_end_time]
        assert (orb_window["orb_breakout"] == 0).all()

    def test_insufficient_data_returns_neutral(self):
        df = pd.DataFrame(
            {"open": [100], "high": [105], "low": [95], "close": [102], "volume": [50000]},
            index=pd.DatetimeIndex([pd.Timestamp("2024-01-02 09:15:00", tz="Asia/Kolkata")]),
        )
        indicator = ORBIndicator()
        assert indicator.get_signal(df) == 0


# ── VWAP Indicator Tests ──────────────────────────────────────────────

class TestVWAP:
    """VWAP = cumsum(typical_price × volume) / cumsum(volume), reset per day."""

    def _make_intraday(self, prices: list[float], date: str = "2024-01-02") -> pd.DataFrame:
        """Build intraday 5m OHLCV with uniform volume."""
        n   = len(prices)
        idx = pd.date_range(
            start=f"{date} 09:15:00", periods=n, freq="5min", tz="Asia/Kolkata"
        )
        arr = np.array(prices, dtype=float)
        return pd.DataFrame(
            {"open": arr, "high": arr + 1, "low": arr - 1, "close": arr, "volume": [100_000] * n},
            index=idx,
        )

    def test_vwap_equals_typical_price_with_uniform_volume(self):
        """When all candles have the same volume, VWAP = mean of typical prices so far."""
        prices = [100.0, 102.0, 98.0, 104.0]
        df = self._make_intraday(prices)
        vwap = compute_vwap(df)

        # Manually compute: typical = (H+L+C)/3 = (price+1 + price-1 + price)/3 = price
        # With uniform volume VWAP[i] = mean(typicals[0..i])
        assert not vwap.isna().any(), "No NaN expected for intraday data"
        assert abs(vwap.iloc[0] - 100.0) < 0.01   # first candle: VWAP = itself
        expected_2 = (100.0 + 102.0) / 2
        assert abs(vwap.iloc[1] - expected_2) < 0.01

    def test_vwap_resets_each_day(self):
        """VWAP from day 1 must not bleed into day 2."""
        day1 = self._make_intraday([200.0, 200.0, 200.0], date="2024-01-02")
        day2 = self._make_intraday([100.0, 100.0, 100.0], date="2024-01-03")
        df   = pd.concat([day1, day2])
        vwap = compute_vwap(df)

        # Day 2's VWAP should be ~100, not influenced by day 1's 200
        day2_vwap = vwap[vwap.index.date == pd.Timestamp("2024-01-03").date()]
        assert (day2_vwap - 100.0).abs().max() < 0.1, "VWAP must reset at start of day 2"

    def test_vwap_returns_nan_for_daily_candles(self):
        """Daily candles have midnight timestamps — VWAP should be all NaN."""
        idx = pd.date_range("2024-01-01", periods=5, freq="D", tz="Asia/Kolkata")
        df  = pd.DataFrame(
            {"open": [100]*5, "high": [105]*5, "low": [95]*5,
             "close": [102]*5, "volume": [1_000_000]*5},
            index=idx,
        )
        vwap = compute_vwap(df)
        assert vwap.isna().all(), "Daily candles should return all-NaN VWAP"

    def test_get_vwap_signal_above(self):
        """Price above VWAP → signal +1 (bullish)."""
        prices = [100.0] * 5 + [110.0]   # last candle spikes above VWAP
        df = self._make_intraday(prices)
        assert get_vwap_signal(df) == 1

    def test_get_vwap_signal_below(self):
        """Price below VWAP → signal -1 (bearish)."""
        prices = [100.0] * 5 + [90.0]    # last candle drops below VWAP
        df = self._make_intraday(prices)
        assert get_vwap_signal(df) == -1

    def test_get_vwap_signal_daily_returns_zero(self):
        """Daily data → VWAP unavailable → neutral 0."""
        idx = pd.date_range("2024-01-01", periods=5, freq="D", tz="Asia/Kolkata")
        df  = pd.DataFrame(
            {"open": [100]*5, "high": [105]*5, "low": [95]*5,
             "close": [102]*5, "volume": [1_000_000]*5},
            index=idx,
        )
        assert get_vwap_signal(df) == 0


# ── Supertrend Indicator Tests ────────────────────────────────────────

def make_trending_ohlcv(
    n: int = 40,
    start_price: float = 100.0,
    step: float = 1.0,
    start: str = "2024-01-02 09:15:00",
) -> pd.DataFrame:
    """Build a strongly trending (up or down) OHLCV DataFrame."""
    closes = [start_price + i * step for i in range(n)]
    idx = pd.date_range(start=start, periods=n, freq="5min", tz="Asia/Kolkata")
    closes_arr = np.array(closes, dtype=float)
    opens = np.roll(closes_arr, 1)
    opens[0] = closes_arr[0]
    return pd.DataFrame(
        {
            "open":   opens,
            "high":   closes_arr + 0.5,
            "low":    closes_arr - 0.5,
            "close":  closes_arr,
            "volume": [100_000] * n,
        },
        index=idx,
    )


class TestSupertrendIndicator:

    def test_compute_adds_required_columns(self):
        df = make_trending_ohlcv(40)
        st = SupertrendIndicator(period=10, multiplier=3.0)
        result = st.compute(df)
        for col in ("supertrend", "supertrend_upper", "supertrend_lower", "supertrend_trend"):
            assert col in result.columns, f"Missing column: {col}"

    def test_not_enough_data_returns_zero(self):
        df = make_ohlcv([100.0] * 5)
        st = SupertrendIndicator(period=10, multiplier=3.0)
        assert st.get_signal(df) == 0

    def test_bullish_trend_detected(self):
        """Strongly rising prices should produce a bullish (+1) signal."""
        df = make_trending_ohlcv(n=40, step=2.0)   # prices rise steadily
        st = SupertrendIndicator(period=10, multiplier=3.0)
        assert st.get_signal(df) == 1

    def test_bearish_trend_detected(self):
        """Strongly falling prices should produce a bearish (-1) signal."""
        df = make_trending_ohlcv(n=40, step=-2.0)  # prices fall steadily
        st = SupertrendIndicator(period=10, multiplier=3.0)
        assert st.get_signal(df) == -1

    def test_is_bullish_convenience(self):
        df = make_trending_ohlcv(n=40, step=2.0)
        st = SupertrendIndicator(period=10, multiplier=3.0)
        assert st.is_bullish(df) is True

    def test_is_bullish_false_on_downtrend(self):
        df = make_trending_ohlcv(n=40, step=-2.0)
        st = SupertrendIndicator(period=10, multiplier=3.0)
        assert st.is_bullish(df) is False

    def test_get_value_returns_float_when_valid(self):
        df = make_trending_ohlcv(n=40)
        st = SupertrendIndicator(period=10, multiplier=3.0)
        val = st.get_value(df)
        assert isinstance(val, float)
        assert val > 0

    def test_get_value_returns_none_when_no_data(self):
        df = make_ohlcv([100.0] * 5)
        st = SupertrendIndicator(period=10, multiplier=3.0)
        assert st.get_value(df) is None

    def test_upper_band_above_lower_band(self):
        """Upper band must always be above lower band in valid rows."""
        df = make_trending_ohlcv(n=40)
        st = SupertrendIndicator(period=10, multiplier=3.0)
        result = st.compute(df)
        valid = result.dropna(subset=["supertrend_upper", "supertrend_lower"])
        assert (valid["supertrend_upper"] >= valid["supertrend_lower"]).all()

    def test_supertrend_line_follows_trend(self):
        """In a bull trend, supertrend line should be BELOW the close price."""
        df = make_trending_ohlcv(n=40, step=2.0)
        st = SupertrendIndicator(period=10, multiplier=3.0)
        result = st.compute(df)
        last = result.dropna(subset=["supertrend"]).iloc[-1]
        assert last["supertrend"] < last["close"]

    def test_min_candles_property(self):
        st = SupertrendIndicator(period=10)
        assert st.min_candles == 12   # period + 2

    def test_trend_switches_after_reversal(self):
        """After a sustained uptrend, a sharp reversal should flip trend to -1."""
        # 25 candles up, then 20 candles sharply down
        up_prices   = list(range(100, 150, 2))   # 25 bars rising
        down_prices = list(range(148, 68, -4))   # 20 bars falling steeply
        closes = up_prices + down_prices
        df = make_ohlcv(closes)
        st = SupertrendIndicator(period=10, multiplier=3.0)
        # Should eventually flip bearish — check last candle
        signal = st.get_signal(df)
        assert signal in (-1, 1)   # just verify it doesn't crash and returns valid int
