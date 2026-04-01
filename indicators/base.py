"""
Base class for all technical indicators.

What is a technical indicator?
  A mathematical calculation applied to a stock's price and/or volume
  history to give signals about likely future price direction.
  Indicators don't predict the future — they help identify patterns
  and probability-weighted setups.

Every indicator must return a standardised signal value:
  +1  = BUY signal (bullish condition detected)
   0  = NEUTRAL / no clear signal
  -1  = SELL signal (bearish condition detected)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class BaseIndicator(ABC):
    """Abstract base class that all indicators inherit from."""

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute the indicator values and append them as new columns.

        Args:
            df: OHLCV DataFrame with columns: open, high, low, close, volume
                The DataFrame must have at least as many rows as the
                indicator's longest lookback period.

        Returns:
            The same DataFrame with indicator columns appended.
            The original df is NOT modified (a copy is returned).
        """
        ...

    @abstractmethod
    def get_signal(self, df: pd.DataFrame) -> int:
        """
        Return the signal for the most recent candle.

        Returns:
            +1  BUY signal
             0  NEUTRAL
            -1  SELL signal
        """
        ...
