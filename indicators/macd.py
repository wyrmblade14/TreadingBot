"""
MACD (Moving Average Convergence Divergence) Indicator.

What is MACD?
  MACD was developed by Gerald Appel in the late 1970s. It measures
  the relationship between two EMAs to identify momentum and trend direction.

  Three components:
    MACD Line    = 12-period EMA  −  26-period EMA
    Signal Line  = 9-period EMA of the MACD Line  (smoother version)
    Histogram    = MACD Line − Signal Line  (how far apart the two lines are)

How to read it:
  When MACD Line crosses ABOVE Signal Line → bullish momentum picking up → BUY
  When MACD Line crosses BELOW Signal Line → bearish momentum → SELL / EXIT

  The histogram makes the crossover easy to see:
    Positive histogram (above zero line) → MACD > Signal → bullish
    Negative histogram (below zero line) → MACD < Signal → bearish
    Histogram shrinking from negative toward zero → potential bullish crossover coming

Why MACD works well for intraday trading:
  MACD captures momentum shifts before they fully show up in price.
  It's particularly useful for confirming trend continuation after
  brief pullbacks — a common intraday setup in Indian markets.
"""

from __future__ import annotations

import pandas as pd
import ta as _ta
from loguru import logger

from indicators.base import BaseIndicator


class MACDIndicator(BaseIndicator):
    """
    Computes MACD and detects crossover signals.

    Args:
        fast:   Fast EMA period (default 12)
        slow:   Slow EMA period (default 26)
        signal: Signal line EMA period (default 9)
    """

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        self.fast = fast
        self.slow = slow
        self.signal = signal
        # Minimum candles needed before MACD has valid values
        self.min_candles = slow + signal

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Append MACD columns to the DataFrame.

        New columns added:
          macd        — MACD line
          macd_signal — Signal line
          macd_hist   — Histogram (MACD − Signal)
        """
        result = df.copy()

        if len(result) < self.min_candles:
            logger.warning(
                f"MACDIndicator: only {len(result)} candles, "
                f"need {self.min_candles} for valid MACD."
            )

        macd_obj = _ta.trend.MACD(
            result["close"],
            window_slow=self.slow,
            window_fast=self.fast,
            window_sign=self.signal,
            fillna=False,
        )
        new_cols = pd.DataFrame(
            {
                "macd":        macd_obj.macd(),
                "macd_signal": macd_obj.macd_signal(),
                "macd_hist":   macd_obj.macd_diff(),
            },
            index=result.index,
        )
        result = pd.concat([result, new_cols], axis=1)

        return result

    def get_signal(self, df: pd.DataFrame) -> int:
        """
        Return signal based on MACD/Signal line crossover.

        +1  = MACD line just crossed above Signal line (bullish crossover)
         0  = No crossover on the current candle
        -1  = MACD line just crossed below Signal line (bearish crossover)
        """
        if len(df) < self.min_candles + 1:
            return 0

        result = self.compute(df)

        curr_macd   = result["macd"].iloc[-1]
        curr_signal = result["macd_signal"].iloc[-1]
        prev_macd   = result["macd"].iloc[-2]
        prev_signal = result["macd_signal"].iloc[-2]

        if any(pd.isna([curr_macd, curr_signal, prev_macd, prev_signal])):
            return 0

        # Bullish crossover: MACD was below signal, now above
        if prev_macd <= prev_signal and curr_macd > curr_signal:
            logger.debug(f"MACD bullish crossover | MACD={curr_macd:.4f} Signal={curr_signal:.4f}")
            return 1

        # Bearish crossover: MACD was above signal, now below
        if prev_macd >= prev_signal and curr_macd < curr_signal:
            logger.debug(f"MACD bearish crossover | MACD={curr_macd:.4f} Signal={curr_signal:.4f}")
            return -1

        return 0

    def get_values(self, df: pd.DataFrame) -> tuple[float | None, float | None, float | None]:
        """
        Return the latest (macd, signal, histogram) values.
        Returns (None, None, None) if insufficient data.
        """
        if len(df) < self.min_candles:
            return None, None, None
        result = self.compute(df)
        row = result.iloc[-1]
        macd = None if pd.isna(row["macd"]) else float(row["macd"])
        sig  = None if pd.isna(row["macd_signal"]) else float(row["macd_signal"])
        hist = None if pd.isna(row["macd_hist"]) else float(row["macd_hist"])
        return macd, sig, hist
