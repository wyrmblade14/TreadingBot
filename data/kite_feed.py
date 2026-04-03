"""
Kite Connect data feed — precise NSE market data.

Replaces yfinance during market hours with Zerodha's own NSE data feed.
yfinance is used as automatic fallback when Kite is unavailable (no token yet,
token expired, network issue, etc.).

Why Kite instead of yfinance?
  yfinance pulls data from Yahoo Finance servers which:
    - May be delayed 10–15 minutes during market hours
    - Occasionally miss candles or return stale data
    - Have no SLA — can be down without notice

  Kite Connect uses NSE's official data feed:
    - Real-time (no delay) via KiteTicker WebSocket
    - Historical OHLCV accurate to the tick via REST API
    - The same data your broker uses for actual execution

Data sources used here:
  1. kite.historical_data()  — OHLCV bars (1min, 5min, etc.) via REST
  2. kite.ltp()              — Last Traded Price (real-time) via REST
  3. KiteTicker (WebSocket)  — Sub-second tick stream (used in build candles)

Instrument tokens:
  Kite uses numeric tokens (e.g. HDFCBANK = 341249) not symbol strings.
  This module caches the NSE token→symbol mapping in memory so lookups
  are instant after the first call.

Usage:
    from data.kite_feed import fetch_kite_ohlcv, get_kite_ltp

    # Get last 5 days of 5-min candles (same format as fetch_ohlcv)
    df = fetch_kite_ohlcv("HDFCBANK", days=5, interval="5minute")

    # Get live last traded price
    ltp = get_kite_ltp(["HDFCBANK", "INFY", "TCS"])
    # → {"HDFCBANK": 1723.45, "INFY": 1456.80, "TCS": 3812.20}
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from loguru import logger

from config.settings import IST
from data.kite_auth import get_kite_client

# ── Instrument token cache ────────────────────────────────────────────
# Maps Kite symbol (e.g. "HDFCBANK") → instrument_token (e.g. 341249)
# Populated lazily on first use; lives for the process lifetime.
_token_cache: dict[str, int] = {}
_token_lock  = threading.Lock()


def _load_instrument_tokens(kite, symbols: list[str]) -> dict[str, int]:
    """
    Fetch NSE instrument list from Kite and extract tokens for requested symbols.
    This hits the Kite API once and caches results — subsequent calls are instant.
    """
    global _token_cache

    # Return from cache if all symbols already known
    missing = [s for s in symbols if s not in _token_cache]
    if not missing:
        return {s: _token_cache[s] for s in symbols if s in _token_cache}

    logger.debug(f"Kite: fetching instrument tokens for {len(missing)} symbols...")
    try:
        instruments = kite.instruments("NSE")
        # instruments is a list of dicts:
        # {"instrument_token": 341249, "tradingsymbol": "HDFCBANK", ...}
        with _token_lock:
            for inst in instruments:
                sym = inst["tradingsymbol"]
                if sym in missing:
                    _token_cache[sym] = inst["instrument_token"]

        found   = [s for s in missing if s in _token_cache]
        not_found = [s for s in missing if s not in _token_cache]
        if found:
            logger.debug(f"Kite: cached tokens for {found}")
        if not_found:
            logger.warning(f"Kite: no token found for {not_found}")

    except Exception as exc:
        logger.warning(f"Kite: instrument fetch failed — {exc}")

    return {s: _token_cache[s] for s in symbols if s in _token_cache}


def fetch_kite_ohlcv(
    kite_symbol: str,
    days: int = 5,
    interval: str = "5minute",
) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV data from Kite Connect REST API.

    Returns a DataFrame in the same format as data.historical.fetch_ohlcv:
        columns: open, high, low, close, volume
        index:   DatetimeIndex in IST

    Args:
        kite_symbol: NSE symbol without exchange prefix, e.g. "HDFCBANK"
        days:        Number of calendar days of history to fetch (default 5)
        interval:    Kite interval string: "minute", "5minute", "15minute",
                     "30minute", "60minute", "day"

    Returns None on any failure (caller should fall back to yfinance).
    """
    kite = get_kite_client()
    if kite is None:
        return None

    tokens = _load_instrument_tokens(kite, [kite_symbol])
    token  = tokens.get(kite_symbol)
    if token is None:
        logger.debug(f"Kite: no instrument token for {kite_symbol}")
        return None

    to_date   = datetime.now(IST).replace(tzinfo=None)
    from_date = to_date - timedelta(days=days)

    try:
        records = kite.historical_data(
            instrument_token=token,
            from_date=from_date,
            to_date=to_date,
            interval=interval,
            continuous=False,
            oi=False,
        )
    except Exception as exc:
        logger.warning(f"Kite historical_data failed for {kite_symbol}: {exc}")
        return None

    if not records:
        logger.debug(f"Kite: no data returned for {kite_symbol}")
        return None

    df = pd.DataFrame(records)
    # Kite returns columns: date, open, high, low, close, volume
    df = df.rename(columns={"date": "datetime"})
    df = df.set_index("datetime")

    # Ensure IST timezone
    if df.index.tzinfo is None:
        df.index = df.index.tz_localize(IST)
    else:
        df.index = df.index.tz_convert(IST)

    df = df[["open", "high", "low", "close", "volume"]].copy()
    df = df.sort_index()

    logger.info(
        f"Kite: {len(df)} {interval} candles for {kite_symbol} "
        f"({df.index[0].date()} → {df.index[-1].date()})"
    )
    return df


def get_kite_ltp(kite_symbols: list[str]) -> dict[str, float]:
    """
    Fetch Last Traded Price for multiple symbols via Kite REST API.

    Args:
        kite_symbols: list of NSE symbols, e.g. ["HDFCBANK", "INFY"]

    Returns:
        dict mapping symbol → LTP float
        Missing symbols are simply absent from the result.
    """
    kite = get_kite_client()
    if kite is None:
        return {}

    # Kite ltp() expects "NSE:HDFCBANK" format
    instrument_ids = [f"NSE:{sym}" for sym in kite_symbols]

    try:
        raw = kite.ltp(instrument_ids)
        # raw = {"NSE:HDFCBANK": {"instrument_token": 341249, "last_price": 1723.45}, ...}
        result = {}
        for sym in kite_symbols:
            key = f"NSE:{sym}"
            if key in raw and raw[key]:
                result[sym] = float(raw[key]["last_price"])
        return result
    except Exception as exc:
        logger.warning(f"Kite LTP fetch failed: {exc}")
        return {}
