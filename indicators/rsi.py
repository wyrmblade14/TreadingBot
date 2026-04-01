"""
RSI (Relative Strength Index) Indicator.

What is RSI?
  RSI measures the speed and magnitude of recent price changes on a
  scale of 0 to 100. It was developed by J. Welles Wilder in 1978.

  RSI = 100 - (100 / (1 + RS))
  where RS = Average gain over N periods / Average loss over N periods

Interpretation:
  RSI > 70 → Overbought: the stock has risen too fast and may pull back
  RSI < 30 → Oversold:   the stock has fallen too fast and may bounce
  RSI 40–60 → Neutral zone: no extreme reading

How we use it:
  We do NOT use RSI alone for entry signals (too many false signals).
  Instead, we use it as a FILTER:
    - Combined with MACD for entry timing (RSI + MACD Combo strategy)
    - As an exit signal when RSI reaches extreme overbought levels (> 75)

  This is a key concept: indicators work much better together than alone.
"""

from __future__ import annotations

import pandas as pd
import ta as _ta
from loguru import logger

from indicators.base import BaseIndicator


class RSIIndicator(BaseIndicator):
    """
    Computes RSI values and provides oversold/overbought signals.

    Args:
        period:     RSI lookback period (default 14)
        oversold:   RSI level below which we consider the stock oversold (default 30)
        overbought: RSI level above which we consider the stock overbought (default 70)
    """

    def __init__(
        self,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
    ) -> None:
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Append RSI column to the DataFrame.

        New column added:
          rsi — RSI value (0–100) for each candle
        """
        result = df.copy()

        if len(result) < self.period + 1:
            logger.warning(
                f"RSIIndicator: only {len(result)} candles, need {self.period + 1}."
            )

        rsi_series = _ta.momentum.RSIIndicator(
            result["close"], window=self.period, fillna=False
        ).rsi().rename("rsi")
        return pd.concat([result, rsi_series], axis=1)

    def get_signal(self, df: pd.DataFrame) -> int:
        """
        Return signal based on current RSI value.

        +1  = RSI just crossed UP from below oversold threshold (bounce signal)
         0  = RSI in neutral zone
        -1  = RSI crossed above overbought (exit/short signal)
        """
        if len(df) < self.period + 2:
            return 0

        result = self.compute(df)
        curr_rsi = result["rsi"].iloc[-1]
        prev_rsi = result["rsi"].iloc[-2]

        if pd.isna(curr_rsi) or pd.isna(prev_rsi):
            return 0

        # Oversold bounce: RSI was below threshold and just crossed above it
        if prev_rsi < self.oversold and curr_rsi >= self.oversold:
            logger.debug(f"RSI oversold bounce | RSI={curr_rsi:.1f}")
            return 1

        # Overbought: RSI exceeded the exit threshold
        if curr_rsi >= self.overbought:
            logger.debug(f"RSI overbought | RSI={curr_rsi:.1f}")
            return -1

        return 0

    def get_value(self, df: pd.DataFrame) -> float | None:
        """Return the current RSI value (useful for filtering in strategy code)."""
        if len(df) < self.period + 1:
            return None
        result = self.compute(df)
        val = result["rsi"].iloc[-1]
        return None if pd.isna(val) else float(val)
