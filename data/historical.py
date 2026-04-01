"""
Historical OHLCV data fetcher using yfinance.

OHLCV explained (every candle has 5 values):
  O = Open  : price at the start of the candle period
  H = High  : highest price reached during the period
  L = Low   : lowest price reached during the period
  C = Close : price at the end of the candle period (most important)
  V = Volume: number of shares traded during the period

We use 5-minute candles for intraday strategies and daily candles for
backtesting over longer periods.

Usage:
    from data.historical import fetch_ohlcv, fetch_daily_ohlcv

    # Get last 60 days of 5-minute candles for Reliance
    df = fetch_ohlcv("RELIANCE.NS", period="60d", interval="5m")

    # Get 2 years of daily candles for backtesting
    df = fetch_daily_ohlcv("RELIANCE.NS", start="2022-01-01", end="2024-01-01")
"""

from __future__ import annotations

import threading
import warnings
from datetime import date, datetime

import pandas as pd
import yfinance as yf
from loguru import logger

# yfinance 1.2.x uses chained assignment internally (df["col"] = ...),
# which triggers hundreds of FutureWarnings from pandas 2.x about the
# upcoming Copy-on-Write default in pandas 3.0. These warnings come from
# yfinance's own utils.py and scrapers/history.py — not from our code.
# Suppress them until yfinance releases a pandas 3.0-compatible version.
warnings.filterwarnings("ignore", category=FutureWarning, module=r"yfinance\.")

# yfinance uses an internal SQLite database to cache timezone lookups.
# SQLite does NOT support concurrent writes, so when multiple threads
# call ticker.history() at once, some fail with "unable to open database file".
# This lock serialises the yfinance calls to prevent cache corruption.
_yf_lock = threading.Lock()


def fetch_ohlcv(
    yf_symbol: str,
    period: str = "60d",
    interval: str = "5m",
    start: str | date | None = None,
    end: str | date | None = None,
) -> pd.DataFrame:
    """
    Download intraday OHLCV data from Yahoo Finance.

    Args:
        yf_symbol: NSE symbol with .NS suffix, e.g. "RELIANCE.NS"
        period:    How far back to fetch. E.g. "7d", "60d", "1mo".
                   Ignored if start/end are provided.
                   Note: yfinance only provides 5-min data for ~60 days.
        interval:  Candle size. "5m" = 5-minute, "1m" = 1-minute, "1d" = daily.
        start:     Start date string "YYYY-MM-DD" (optional, overrides period).
        end:       End date string "YYYY-MM-DD" (optional).

    Returns:
        DataFrame with columns: open, high, low, close, volume
        Index: timezone-aware datetime in IST (Asia/Kolkata)

    Raises:
        ValueError: if the download returns empty data (symbol not found, etc.)
    """
    logger.debug(f"Fetching {interval} OHLCV for {yf_symbol} | period={period}")

    kwargs: dict = {"interval": interval, "auto_adjust": True}
    if start:
        kwargs["start"] = start
        kwargs.pop("period", None)
        if end:
            kwargs["end"] = end
    else:
        kwargs["period"] = period

    ticker = yf.Ticker(yf_symbol)
    with _yf_lock:
        df = ticker.history(**kwargs)

    # Retry once if yfinance returned None (can happen on transient rate-limit or network hiccup)
    if df is None or df.empty:
        import time as _time
        _time.sleep(2)
        with _yf_lock:
            df = ticker.history(**kwargs)

    if df is None or df.empty:
        raise ValueError(
            f"No data returned for {yf_symbol!r}. "
            "Check the symbol format (should end in .NS for NSE stocks)."
        )

    # Standardise column names to lowercase
    df.columns = [c.lower() for c in df.columns]

    # Keep only the 5 OHLCV columns; drop dividends/splits if present
    df = df[["open", "high", "low", "close", "volume"]].copy()

    # Convert index to IST timezone
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert("Asia/Kolkata")

    # Drop rows with NaN values (can happen at market open/close edges)
    df.dropna(inplace=True)

    logger.info(
        f"Downloaded {len(df)} {interval} candles for {yf_symbol} "
        f"({df.index[0].date()} → {df.index[-1].date()})"
    )
    return df


def fetch_daily_ohlcv(
    yf_symbol: str,
    start: str = "2022-01-01",
    end: str | None = None,
) -> pd.DataFrame:
    """
    Download daily OHLCV data for backtesting.

    Daily candles are available for many years — ideal for backtesting
    strategies across different market conditions (bull, bear, sideways).

    Args:
        yf_symbol: NSE symbol with .NS suffix, e.g. "RELIANCE.NS"
        start:     Start date "YYYY-MM-DD"
        end:       End date "YYYY-MM-DD". Defaults to today.

    Returns:
        DataFrame with columns: open, high, low, close, volume
        Index: date (daily frequency)
    """
    if end is None:
        end = date.today().isoformat()

    return fetch_ohlcv(yf_symbol, interval="1d", start=start, end=end)


def fetch_multiple(
    yf_symbols: list[str],
    period: str = "60d",
    interval: str = "5m",
) -> dict[str, pd.DataFrame]:
    """
    Download OHLCV data for multiple symbols in one call.

    Returns a dict mapping symbol → DataFrame. Symbols that fail are
    logged as warnings and excluded from the result.

    Args:
        yf_symbols: List of NSE symbols, e.g. ["RELIANCE.NS", "TCS.NS"]
        period:     Data period (see fetch_ohlcv)
        interval:   Candle interval (see fetch_ohlcv)
    """
    results: dict[str, pd.DataFrame] = {}
    for symbol in yf_symbols:
        try:
            results[symbol] = fetch_ohlcv(symbol, period=period, interval=interval)
        except (ValueError, Exception) as exc:
            logger.warning(f"Skipping {symbol}: {exc}")
    return results
