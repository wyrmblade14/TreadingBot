"""
First Candle Anchor — extracts the high and low of the 9:15–9:20 candle.

What is the "first candle anchor"?
  The very first 5-minute candle of the day (9:15–9:20 AM) is the most
  important candle of the session. It captures the initial price discovery
  after overnight news, global market moves, and pre-market orders all
  get absorbed simultaneously at the open.

  The key levels:
    First candle HIGH → The market failed to break above this in the first
                        5 minutes. If it breaks above later in the day with
                        momentum, institutions are committing bullish.
    First candle LOW  → Same logic bearish. A break below this signals
                        institutions are selling.

How we use it:
  We apply this as a filter on EMA Crossover signals:
    BUY  only when current price is ABOVE the first candle high
         (confirms bullish day — the market has already cleared the open's
         resistance and is building on it)
    SELL only when current price is BELOW the first candle low
         (confirms bearish day)

  A BUY signal that fires below the first candle high is ambiguous — the
  stock may just be oscillating inside the morning range without direction.
  We skip those trades and wait for confirmed direction.

Note: This filter is only relevant for intraday (5m) data.
      On daily candles, the 9:15–9:20 window does not exist in the DataFrame
      and get_first_candle_levels() returns None, so the filter is skipped.
"""

from __future__ import annotations

from datetime import time

import pandas as pd


def get_first_candle_levels(df: pd.DataFrame) -> tuple[float, float] | None:
    """
    Return (high, low) of the 9:15–9:20 candle for today.

    Args:
        df: OHLCV DataFrame with an IST-timezone DatetimeIndex.

    Returns:
        (first_candle_high, first_candle_low) if the candle exists, else None.
        Returns None for daily data (9:15 candles are not present).
    """
    today = df.index[-1].date()
    mask = (
        (df.index.date == today)
        & (df.index.time >= time(9, 15))
        & (df.index.time < time(9, 20))
    )
    candles = df[mask]
    if candles.empty:
        return None
    return float(candles["high"].iloc[0]), float(candles["low"].iloc[0])
