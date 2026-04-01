"""
In-memory candle store for the live trading session.

During live/paper trading, tick data arrives via WebSocket and gets
assembled into candles here. Each symbol gets its own DataFrame that
grows candle-by-candle throughout the trading day.

Think of this as the bot's "short-term memory" for today's price data.
At end of day the store is cleared and historical data is persisted to disk.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import pandas as pd
from loguru import logger


class CandleStore:
    """
    Thread-safe in-memory store for intraday OHLCV candles.

    Each symbol has its own DataFrame indexed by candle timestamp.
    New candles are appended as they complete during the trading session.
    """

    def __init__(self) -> None:
        # symbol → DataFrame(open, high, low, close, volume)
        self._data: dict[str, pd.DataFrame] = defaultdict(
            lambda: pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        )

    def append_candle(
        self,
        symbol: str,
        timestamp: datetime,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: int,
    ) -> None:
        """Add a completed candle to the store for a given symbol."""
        new_row = pd.DataFrame(
            [{"open": open_, "high": high, "low": low, "close": close, "volume": volume}],
            index=[timestamp],
        )
        existing = self._data[symbol]
        # Avoid duplicates if the same candle timestamp arrives twice
        if timestamp not in existing.index:
            self._data[symbol] = pd.concat([existing, new_row])
            logger.debug(f"Candle stored: {symbol} @ {timestamp} | C={close:.2f}")

    def get(self, symbol: str) -> pd.DataFrame:
        """Return all candles for a symbol as a DataFrame."""
        return self._data[symbol].copy()

    def get_last_n(self, symbol: str, n: int) -> pd.DataFrame:
        """Return the most recent n candles for a symbol."""
        return self._data[symbol].tail(n).copy()

    def symbols(self) -> list[str]:
        """Return list of all symbols currently in the store."""
        return list(self._data.keys())

    def clear(self) -> None:
        """Clear all candle data (called at start of each trading day)."""
        self._data.clear()
        logger.info("CandleStore cleared for new trading day.")

    def candle_count(self, symbol: str) -> int:
        """Return how many candles are stored for a symbol."""
        return len(self._data[symbol])


# Singleton instance shared across the application
candle_store = CandleStore()
