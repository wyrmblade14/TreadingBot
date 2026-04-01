"""
Supertrend Indicator — ATR-based adaptive trend filter.

What is Supertrend?
  Supertrend is a trend-following indicator that draws a line above or below
  price depending on the current trend direction. Unlike a fixed 50-EMA, it
  adapts its bands based on ATR (Average True Range) — how much the stock
  is actually moving day to day.

Why Supertrend is better than a 50-EMA as a trend filter:
  50-EMA reacts to price LEVELS — it says "price is above its 50-day average".
  Supertrend reacts to price VOLATILITY — it asks "has price broken convincingly
  above/below a volatility-adjusted band?"

  In choppy, sideways markets:
    50-EMA: price keeps crossing above and below it → false signals
    Supertrend: wider bands mean it takes a bigger move to change trend → fewer
                false signals

  In strongly trending markets:
    Both work well, but Supertrend's line sits closer to price → tighter stops.

How it works (plain English):
  1. Calculate ATR(10) — the average true range over 10 candles.
  2. Compute an upper band: midpoint + 3 × ATR (resistance ceiling)
     and a lower band:  midpoint − 3 × ATR (support floor)
  3. Apply memory rules:
       - Upper band can only move DOWN or stay flat (it's a ceiling).
         Reset only when price crosses above it (trend just flipped bullish).
       - Lower band can only move UP or stay flat (it's a floor).
         Reset only when price crosses below it (trend just flipped bearish).
  4. If close > previous upper band → BULLISH (trend = +1)
     If close < previous lower band → BEARISH (trend = -1)
     Otherwise → maintain the previous trend

  This memory (bands can't move against the trend) is what makes Supertrend
  "sticky" — it doesn't flip back and forth on every candle.

Columns added by compute():
  supertrend      — the trend line value (lower band in bull, upper in bear)
  supertrend_upper — dynamic resistance ceiling
  supertrend_lower — dynamic support floor
  supertrend_trend — +1 (bullish) or -1 (bearish)

Signal from get_signal():
  +1 = bullish trend (price above supertrend line)
  -1 = bearish trend (price below supertrend line)
   0 = not enough data yet

Common parameters (used in Indian intraday markets):
  period=10, multiplier=3.0  — standard, works well for 5-minute NSE charts
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import ta

from indicators.base import BaseIndicator


class SupertrendIndicator(BaseIndicator):
    """
    Supertrend trend filter using ATR-based dynamic bands.

    Args:
        period:     ATR lookback period (default 10).
        multiplier: Band width multiplier applied to ATR (default 3.0).
    """

    def __init__(self, period: int = 10, multiplier: float = 3.0) -> None:
        self.period     = period
        self.multiplier = multiplier

    @property
    def min_candles(self) -> int:
        """Minimum DataFrame length needed for a valid signal."""
        return self.period + 2

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute Supertrend bands and trend direction.

        Appends four columns to the DataFrame:
          supertrend        — the active trend line (support in bull, resistance in bear)
          supertrend_upper  — upper ATR band
          supertrend_lower  — lower ATR band
          supertrend_trend  — +1 (bullish) or -1 (bearish); NaN until period is reached

        Uses numpy arrays for the iterative band-memory computation to avoid
        pandas CoW (Copy-on-Write) warnings from chained assignment.
        """
        n     = len(df)
        high  = df["high"].values.astype(float)
        low   = df["low"].values.astype(float)
        close = df["close"].values.astype(float)

        # ATR via ta library (same library used by all other indicators in this project)
        atr_vals = ta.volatility.AverageTrueRange(
            df["high"], df["low"], df["close"], window=self.period
        ).average_true_range().values.astype(float)

        hl2         = (high + low) / 2.0
        basic_upper = hl2 + self.multiplier * atr_vals
        basic_lower = hl2 - self.multiplier * atr_vals

        # Pre-allocate output arrays
        final_upper = np.full(n, np.nan)
        final_lower = np.full(n, np.nan)
        supertrend  = np.full(n, np.nan)
        trend       = np.full(n, np.nan)

        # Find first valid ATR index
        start = self.period  # ta ATR needs `period` bars; index `period` is first valid
        if start >= n:
            extra = pd.DataFrame(
                {
                    "supertrend":       supertrend,
                    "supertrend_upper": final_upper,
                    "supertrend_lower": final_lower,
                    "supertrend_trend": trend,
                },
                index=df.index,
            )
            return pd.concat([df, extra], axis=1)

        # Seed the first valid bar
        final_upper[start] = basic_upper[start]
        final_lower[start] = basic_lower[start]
        trend[start]       = 1.0 if close[start] >= hl2[start] else -1.0
        supertrend[start]  = (
            final_lower[start] if trend[start] == 1.0 else final_upper[start]
        )

        # Iterative computation — state machine, cannot be vectorised
        for i in range(start + 1, n):
            # Upper band: allowed to move DOWN only.
            # Reset (use fresh basic_upper) if:
            #   a) new basic_upper is lower than the stored ceiling, OR
            #   b) previous close broke above the stored ceiling (trend just flipped bullish)
            if (
                basic_upper[i] < final_upper[i - 1]
                or close[i - 1] > final_upper[i - 1]
            ):
                final_upper[i] = basic_upper[i]
            else:
                final_upper[i] = final_upper[i - 1]

            # Lower band: allowed to move UP only.
            # Reset (use fresh basic_lower) if:
            #   a) new basic_lower is higher than the stored floor, OR
            #   b) previous close broke below the stored floor (trend just flipped bearish)
            if (
                basic_lower[i] > final_lower[i - 1]
                or close[i - 1] < final_lower[i - 1]
            ):
                final_lower[i] = basic_lower[i]
            else:
                final_lower[i] = final_lower[i - 1]

            # Trend determination
            if close[i] > final_upper[i - 1]:
                trend[i] = 1.0    # price broke through ceiling → bullish
            elif close[i] < final_lower[i - 1]:
                trend[i] = -1.0   # price broke through floor → bearish
            else:
                trend[i] = trend[i - 1]   # maintain previous trend

            supertrend[i] = (
                final_lower[i] if trend[i] == 1.0 else final_upper[i]
            )

        extra = pd.DataFrame(
            {
                "supertrend":       supertrend,
                "supertrend_upper": final_upper,
                "supertrend_lower": final_lower,
                "supertrend_trend": trend,
            },
            index=df.index,
        )
        return pd.concat([df, extra], axis=1)

    def get_signal(self, df: pd.DataFrame) -> int:
        """
        Return the current Supertrend trend direction.

        Returns:
            +1  Bullish — price above Supertrend line, buy conditions met
            -1  Bearish — price below Supertrend line
             0  Not enough data
        """
        if len(df) < self.min_candles:
            return 0

        result = self.compute(df)
        trend  = result["supertrend_trend"].iloc[-1]

        if np.isnan(trend):
            return 0
        return int(trend)

    def is_bullish(self, df: pd.DataFrame) -> bool:
        """Convenience method — returns True when trend is bullish (+1)."""
        return self.get_signal(df) == 1

    def get_value(self, df: pd.DataFrame) -> float | None:
        """Return the current Supertrend line value (for display/logging)."""
        if len(df) < self.min_candles:
            return None
        result = self.compute(df)
        val = result["supertrend"].iloc[-1]
        return float(val) if not np.isnan(val) else None
