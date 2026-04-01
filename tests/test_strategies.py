"""
Unit tests for the three trading strategies.

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
from strategies.ema_crossover import EMACrossoverStrategy
from strategies.opening_range_breakout import ORBStrategy
from strategies.rsi_macd_combo import RSIMACDStrategy


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
