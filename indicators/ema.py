"""
EMA (Exponential Moving Average) Crossover Indicator.

What is EMA?
  An EMA is a type of moving average that gives more weight to recent
  prices than older ones. This makes it react faster to price changes
  compared to a simple moving average (SMA).

How the crossover strategy works:
  We use THREE EMAs simultaneously:
    - Fast EMA  (9 periods)  — reacts quickly to recent price moves
    - Slow EMA  (21 periods) — smoother, filters out short-term noise
    - Trend EMA (50 periods) — tells us the dominant direction of the stock

  BUY signal:  Fast EMA crosses ABOVE Slow EMA  AND  price is above Trend EMA
               Interpretation: short-term momentum is turning bullish, and
               the stock is in an overall uptrend.

  SELL signal: Fast EMA crosses BELOW Slow EMA
               Interpretation: short-term momentum is weakening.

  Volume filter: The crossover candle must have above-average volume,
  confirming that real buying/selling pressure backs the move.

Why this works for intraday trading:
  In India's intraday market, EMA crossovers on 5-minute charts catch
  momentum moves early. The 50 EMA trend filter prevents trading against
  the broader trend (a common beginner mistake).
"""

from __future__ import annotations

import pandas as pd
import ta as _ta
from loguru import logger

from indicators.base import BaseIndicator


class EMAIndicator(BaseIndicator):
    """
    Computes EMA crossover signals using 9/21/50 period EMAs.

    Args:
        short_period:      Fast EMA period (default 9)
        long_period:       Slow EMA period (default 21)
        trend_period:      Trend EMA period (default 50)
        volume_multiplier: Signal candle volume must be >= this × 20-bar avg volume
    """

    def __init__(
        self,
        short_period: int = 9,
        long_period: int = 21,
        trend_period: int = 50,
        volume_multiplier: float = 1.5,
    ) -> None:
        self.short_period = short_period
        self.long_period = long_period
        self.trend_period = trend_period
        self.volume_multiplier = volume_multiplier

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Append EMA columns to the DataFrame.

        New columns added:
          ema_short  — fast EMA (9 by default)
          ema_long   — slow EMA (21 by default)
          ema_trend  — trend EMA (50 by default)
          vol_avg20  — 20-bar simple moving average of volume
        """
        result = df.copy()

        if len(result) < self.trend_period:
            logger.warning(
                f"EMAIndicator: only {len(result)} candles available, "
                f"need at least {self.trend_period}. EMAs may be NaN."
            )

        close = result["close"]
        new_cols = pd.DataFrame(
            {
                f"ema_{self.short_period}":  _ta.trend.EMAIndicator(close, window=self.short_period, fillna=False).ema_indicator(),
                f"ema_{self.long_period}":   _ta.trend.EMAIndicator(close, window=self.long_period,  fillna=False).ema_indicator(),
                f"ema_{self.trend_period}":  _ta.trend.EMAIndicator(close, window=self.trend_period, fillna=False).ema_indicator(),
                "vol_avg20":                 result["volume"].rolling(window=20).mean(),
            },
            index=result.index,
        )
        return pd.concat([result, new_cols], axis=1)

    def get_signal(self, df: pd.DataFrame) -> int:
        """
        Return signal for the most recent (last) candle.

        Crossover is detected by comparing the relationship between
        fast and slow EMAs on the current vs previous candle.
        """
        if len(df) < self.trend_period + 1:
            return 0  # Not enough data yet

        result = self.compute(df)

        fast_col  = f"ema_{self.short_period}"
        slow_col  = f"ema_{self.long_period}"
        trend_col = f"ema_{self.trend_period}"

        # Current and previous candle values
        curr = result.iloc[-1]
        prev = result.iloc[-2]

        # Guard against NaN (not enough historical data yet)
        if any(pd.isna([curr[fast_col], curr[slow_col], curr[trend_col]])):
            return 0

        fast_now, fast_prev = curr[fast_col], prev[fast_col]
        slow_now, slow_prev = curr[slow_col], prev[slow_col]
        close = curr["close"]
        trend_ema = curr[trend_col]

        # --- Volume check ---
        vol_avg = curr.get("vol_avg20", 0)
        volume_confirmed = (vol_avg == 0) or (curr["volume"] >= self.volume_multiplier * vol_avg)

        # --- Bullish crossover ---
        # Previous: fast < slow  →  Current: fast > slow  (crossed up)
        bullish_cross = (fast_prev < slow_prev) and (fast_now > slow_now)
        above_trend   = close > trend_ema

        if bullish_cross and above_trend and volume_confirmed:
            logger.debug(
                f"EMA BUY signal | fast={fast_now:.2f} slow={slow_now:.2f} "
                f"trend={trend_ema:.2f} close={close:.2f}"
            )
            return 1

        # --- Bearish crossover ---
        # Previous: fast > slow  →  Current: fast < slow  (crossed down)
        bearish_cross = (fast_prev > slow_prev) and (fast_now < slow_now)

        if bearish_cross:
            logger.debug(
                f"EMA SELL signal | fast={fast_now:.2f} slow={slow_now:.2f}"
            )
            return -1

        return 0
