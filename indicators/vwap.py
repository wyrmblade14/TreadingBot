"""
VWAP — Volume Weighted Average Price.

What is VWAP and why does it matter?
  VWAP is the average price a stock traded at throughout the day,
  weighted by how much volume traded at each price level.

  Institutional traders (large mutual funds, FIIs) use VWAP as a
  benchmark. They aim to buy below VWAP (getting better-than-average
  price) and sell above it.

  As a retail trader, this is powerful:
    - Price above VWAP → institutions are net buyers → bullish bias
    - Price below VWAP → institutions are net sellers → bearish bias

  Using VWAP as an additional filter on top of EMA and ORB signals
  dramatically reduces false breakouts caused by low-volume moves.

Calculation:
  Typical Price (TP) = (High + Low + Close) / 3
  VWAP = cumsum(TP × Volume) / cumsum(Volume)

  This resets to the first candle's value at the start of each trading day
  (9:15 AM IST) — VWAP is always an intraday metric.

Important:
  VWAP is only meaningful for intraday data (5m, 1h candles).
  For daily candles there is no intraday volume weighting context,
  so `compute_vwap` returns NaN for daily data and strategies skip the filter.
"""

from __future__ import annotations

import pandas as pd


def compute_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Compute VWAP for each candle, resetting at the start of each trading day.

    Args:
        df: OHLCV DataFrame with DatetimeIndex (should be timezone-aware IST).
            Must have columns: high, low, close, volume.

    Returns:
        pd.Series of VWAP values aligned to df.index.
        Returns all-NaN series for daily candles (no intraday reset point).

    Example:
        vwap = compute_vwap(df)
        is_above_vwap = df["close"].iloc[-1] > vwap.iloc[-1]
    """
    # Daily candles have no time component — VWAP not meaningful
    if _is_daily(df):
        return pd.Series(float("nan"), index=df.index)

    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    tp_vol        = typical_price * df["volume"]

    vwap = pd.Series(index=df.index, dtype=float)

    # Group by calendar date and compute cumulative sums within each day
    for _date, group_idx in df.groupby(df.index.date).groups.items():
        cum_tp_vol      = tp_vol[group_idx].cumsum()
        cum_vol         = df["volume"][group_idx].cumsum()
        # Replace zero cumulative volume with NaN so zero-vol candles get NaN
        # VWAP instead of causing a length mismatch on assignment
        cum_vol_safe    = cum_vol.replace(0, float("nan"))
        vwap.loc[group_idx] = (cum_tp_vol / cum_vol_safe).values

    return vwap


def get_vwap_signal(df: pd.DataFrame) -> int:
    """
    Return VWAP directional bias for the latest candle.

    Returns:
         1  — close is above VWAP (bullish institutional bias)
        -1  — close is below VWAP (bearish institutional bias)
         0  — VWAP unavailable (daily data or zero volume)
    """
    vwap = compute_vwap(df)
    last_vwap  = vwap.iloc[-1]
    last_close = float(df["close"].iloc[-1])

    if pd.isna(last_vwap) or last_vwap == 0:
        return 0

    if last_close > last_vwap:
        return 1
    if last_close < last_vwap:
        return -1
    return 0


# ── Internal helper ────────────────────────────────────────────────────

def _is_daily(df: pd.DataFrame) -> bool:
    """
    True if the DataFrame contains daily (not intraday) candles.

    Daily candles from yfinance have timestamps at midnight (00:00:00).
    Intraday candles (5m, 1h) have non-midnight timestamps like 09:15, 09:20…

    Detection: check whether each timestamp already equals its own midnight
    (i.e., the time component is 00:00:00).
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        return True
    # normalize() strips the time, giving midnight for every entry.
    # If original == midnight, the timestamp IS the day boundary → daily data.
    return (df.index == df.index.normalize()).all()
