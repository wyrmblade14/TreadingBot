"""
Market Overview — NIFTY50 breadth and index data.

Provides:
  - NIFTY50 index price and day change
  - Advance/Decline ratio (how many stocks are up vs down today)
  - Top gainers and losers from NIFTY50

What is Advance/Decline ratio?
  If 35 of the 50 NIFTY stocks are up today, the ratio is 35:15.
  A ratio above 30:20 usually means the market is broadly bullish.
  Below 20:30 means broad weakness.

All data is fetched via yfinance (free, no API key needed).
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass

import pandas as pd
import yfinance as yf

from data.instruments import NIFTY50_INSTRUMENTS, KITE_TO_YF


@dataclass
class MarketOverview:
    """Snapshot of NIFTY50 market breadth at a point in time."""
    nifty_price:    float
    nifty_change:   float   # absolute change
    nifty_change_pct: float  # % change
    advances:       int     # number of stocks up
    declines:       int     # number of stocks down
    unchanged:      int
    top_gainers:    list[dict]   # [{"symbol": ..., "change_pct": ...}, ...]
    top_losers:     list[dict]
    total_symbols:  int


_CACHE_TTL = 300  # 5 minutes
_cache: dict = {
    "timestamp": 0.0,
    "overview": None
}


def get_nifty_overview(top_n: int = 5) -> MarketOverview | None:
    """
    Fetch NIFTY50 index level and breadth data with 5-minute TTL cache.

    Args:
        top_n: Number of top gainers/losers to return

    Returns:
        MarketOverview dataclass, or None if data fetch failed.
    """
    global _cache
    now_ts = _time.monotonic()

    if now_ts - _cache["timestamp"] < _CACHE_TTL and _cache["overview"] is not None:
        return _cache["overview"]

    _cache["timestamp"] = now_ts

    try:
        # Fetch NIFTY50 index
        nifty = yf.Ticker("^NSEI")
        nifty_hist = nifty.history(period="2d", interval="1d")
        if len(nifty_hist) < 2:
            return None

        nifty_prev  = float(nifty_hist["Close"].iloc[-2])
        nifty_close = float(nifty_hist["Close"].iloc[-1])
        nifty_chg   = nifty_close - nifty_prev
        nifty_pct   = nifty_chg / nifty_prev * 100

        # Fetch all NIFTY50 stocks
        kite_symbols = [i.kite_symbol for i in NIFTY50_INSTRUMENTS[:50]]
        yf_symbols = [KITE_TO_YF.get(s, s + ".NS") for s in kite_symbols]
        data = yf.download(yf_symbols, period="2d", interval="1d",
                           auto_adjust=True, progress=False)

        if data.empty:
            return None

        closes = data["Close"] if "Close" in data else data

        advances = 0
        declines = 0
        unchanged = 0
        changes: list[dict] = []

        for sym_yf, kite_sym in zip(yf_symbols, kite_symbols):
            try:
                col = closes[sym_yf] if sym_yf in closes.columns else None
                if col is None or len(col.dropna()) < 2:
                    continue
                prev  = float(col.dropna().iloc[-2])
                today = float(col.dropna().iloc[-1])
                pct   = (today - prev) / prev * 100 if prev != 0 else 0.0
                changes.append({"symbol": kite_sym, "change_pct": round(pct, 2), "price": round(today, 2)})
                if pct > 0.1:
                    advances += 1
                elif pct < -0.1:
                    declines += 1
                else:
                    unchanged += 1
            except Exception:
                continue

        sorted_changes = sorted(changes, key=lambda x: x["change_pct"], reverse=True)
        top_gainers = sorted_changes[:top_n]
        top_losers  = sorted_changes[-top_n:][::-1]

        overview = MarketOverview(
            nifty_price=round(nifty_close, 2),
            nifty_change=round(nifty_chg, 2),
            nifty_change_pct=round(nifty_pct, 2),
            advances=advances,
            declines=declines,
            unchanged=unchanged,
            top_gainers=top_gainers,
            top_losers=top_losers,
            total_symbols=len(changes),
        )
        _cache["overview"] = overview
        return overview

    except Exception as e:
        from loguru import logger
        logger.warning(f"Market overview fetch failed: {e}")
        return None
