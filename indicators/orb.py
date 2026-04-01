"""
ORB (Opening Range Breakout) Indicator.

What is Opening Range Breakout?
  The "opening range" is the high and low price formed during the first
  N minutes of the trading session (we use 15 minutes: 9:15–9:30 AM IST).

  The core idea: institutional traders and large funds establish their
  directional bias in the first few minutes. Once price breaks out of
  this initial range with strong volume, it often continues in that
  direction for the rest of the morning.

  BUY signal:  A 5-min candle CLOSES ABOVE the opening range high
               → Price has broken out upward with conviction
               → We buy, expecting continuation

  SELL signal: A 5-min candle CLOSES BELOW the opening range low
               → Price has broken down with conviction
               → We sell/short (or exit longs)

Why this works in the Indian market:
  Indian markets often gap up or down at open and then reverse OR
  continue strongly. ORB captures the "continuation" move after the
  initial 15-minute price discovery phase. It's particularly effective
  on high-volatility days (earnings, budget announcements, global events).

Limitations:
  - On "choppy" (sideways, low-volatility) days, ORB gives false breakouts.
  - Always check if the overall NIFTY is trending before taking ORB trades.
  - Exit ALL ORB positions by 2:30 PM regardless of P&L.
"""

from __future__ import annotations

from datetime import time

import pandas as pd
from loguru import logger

from indicators.base import BaseIndicator


class ORBIndicator(BaseIndicator):
    """
    Detects Opening Range Breakout signals.

    Args:
        orb_end_time:       End of the opening range window (default 9:30 AM)
        volume_multiplier:  Breakout candle must have this multiple of avg volume
    """

    def __init__(
        self,
        orb_end_time: time = time(9, 30),
        volume_multiplier: float = 1.5,
    ) -> None:
        self.orb_end_time = orb_end_time
        self.volume_multiplier = volume_multiplier

    def _get_opening_range(self, df: pd.DataFrame) -> tuple[float, float] | None:
        """
        Calculate the opening range high and low.

        Returns (range_high, range_low) or None if opening range
        candles are not yet available in the DataFrame.
        """
        # Filter candles within the opening range window for TODAY only.
        # Without the date filter, the visible slice spans all historical days and
        # _get_opening_range() returns the max high / min low of every opening session
        # in history — a wildly wide range that is never breached intraday.
        today = df.index[-1].date()
        orb_mask = (df.index.date == today) & (df.index.time <= self.orb_end_time)
        orb_candles = df[orb_mask]

        if orb_candles.empty:
            return None

        range_high = orb_candles["high"].max()
        range_low  = orb_candles["low"].min()
        return range_high, range_low

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Append opening range levels and breakout flags to the DataFrame.

        New columns added:
          orb_high       — Opening range high price
          orb_low        — Opening range low price
          orb_breakout   — +1 if candle closed above orb_high, -1 below orb_low, else 0
        """
        result = df.copy()
        orb_range = self._get_opening_range(result)

        if orb_range is None:
            extra = pd.DataFrame(
                {"orb_high": float("nan"), "orb_low": float("nan"), "orb_breakout": 0},
                index=result.index,
            )
            return pd.concat([result, extra], axis=1)

        range_high, range_low = orb_range
        vol_avg20 = result["volume"].rolling(20).mean()

        def classify_breakout(row: pd.Series) -> int:
            if row.name.time() <= self.orb_end_time:
                return 0
            avg = vol_avg20.loc[row.name]
            vol_confirmed = pd.isna(avg) or row["volume"] >= self.volume_multiplier * avg
            if row["close"] > range_high and vol_confirmed:
                return 1
            if row["close"] < range_low and vol_confirmed:
                return -1
            return 0

        extra = pd.DataFrame(
            {
                "orb_high":     range_high,
                "orb_low":      range_low,
                "vol_avg20":    vol_avg20,
                "orb_breakout": result.apply(classify_breakout, axis=1),
            },
            index=result.index,
        )
        return pd.concat([result, extra], axis=1)

    def get_signal(self, df: pd.DataFrame) -> int:
        """
        Return the ORB signal for the most recent candle.

        +1  = Bullish breakout above opening range high
         0  = No breakout
        -1  = Bearish breakdown below opening range low
        """
        if len(df) < 3:
            return 0

        # Only generate signal if opening range is complete
        orb_range = self._get_opening_range(df)
        if orb_range is None:
            return 0

        # Current candle must be after the opening range window
        current_time = df.index[-1].time()
        if current_time <= self.orb_end_time:
            return 0

        result = self.compute(df)
        signal = int(result["orb_breakout"].iloc[-1])

        if signal == 1:
            logger.debug(
                f"ORB BUY breakout | close={result['close'].iloc[-1]:.2f} "
                f"above orb_high={orb_range[0]:.2f}"
            )
        elif signal == -1:
            logger.debug(
                f"ORB SELL breakdown | close={result['close'].iloc[-1]:.2f} "
                f"below orb_low={orb_range[1]:.2f}"
            )

        return signal

    def get_range(self, df: pd.DataFrame) -> tuple[float, float] | None:
        """Return (orb_high, orb_low) for display in the dashboard."""
        return self._get_opening_range(df)
