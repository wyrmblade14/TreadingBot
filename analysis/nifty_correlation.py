"""
NIFTY Divergence Filter — detects when a stock is diverging from the index.

Why this matters:
  The bot evaluates signals in isolation, without checking whether a stock
  is actually participating in the market's move. A human trader immediately
  notices "NIFTY is up 1.5% but RELIANCE is flat — skip the BUY." Conversely,
  a stock that refuses to rally is a relative-weakness short candidate.

What it does:
  After 10:00 AM, compare the stock's intraday % change vs NIFTY's:

    NIFTY ≥ +1.0% AND stock < +0.3%  →  LAGGING  (suppress BUY, flag for SELL)
    NIFTY ≤ −1.0% AND stock > −0.3%  →  LEADING  (suppress SELL)
    anything else                     →  IN_LINE  (no change)

Fail-open design: any data error returns IN_LINE — a signal is never
blocked because of a failed network request.

Cache: 5-minute TTL (same as VIX, regime detector, market direction).
Data source: yfinance fallback (same priority as the rest of the bot).
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass
from datetime import datetime, time

import pandas as pd
from loguru import logger

from config.settings import IST

# ── Thresholds ────────────────────────────────────────────────────────
_NIFTY_MOVE_PCT  = 1.0   # NIFTY must move at least this much (absolute %)
_STOCK_LAG_PCT   = 0.3   # stock must lag by more than this % to count as diverging
_CACHE_TTL       = 300   # 5-minute cache TTL (seconds)

# ── Cache ─────────────────────────────────────────────────────────────
_cache: dict = {
    "nifty_chg": 0.0,
    "timestamp": 0.0,
}


@dataclass
class DivergenceResult:
    """
    Result of comparing a stock's intraday move vs NIFTY's.

    Fields:
        nifty_chg_pct  — NIFTY's % change vs 9:15 open today
        stock_chg_pct  — Stock's % change vs its own 9:15 open today
        label          — "LAGGING" | "IN_LINE" | "LEADING"
        suppress_buy   — True when stock lags a rising NIFTY → skip BUY signals
        suppress_sell  — True when stock holds up in a falling NIFTY → skip SELL signals
        amplify_sell   — True when LAGGING → relative weakness short confirmed (SELL passes through)
    """
    nifty_chg_pct: float
    stock_chg_pct: float
    label:         str    # "LAGGING" | "IN_LINE" | "LEADING"
    suppress_buy:  bool
    suppress_sell: bool
    amplify_sell:  bool


# Sentinel for any error path — re-used to avoid allocation on every fail
_IN_LINE = DivergenceResult(
    nifty_chg_pct=0.0,
    stock_chg_pct=0.0,
    label="IN_LINE",
    suppress_buy=False,
    suppress_sell=False,
    amplify_sell=False,
)


def get_nifty_change() -> float:
    """
    Return NIFTY50's intraday % change vs today's 9:15 open. Cached 5 min.

    Returns 0.0 before 10:00 AM (opening noise) and on any data error.
    A return of 0.0 means the divergence filter will classify all stocks
    as IN_LINE — safe fail-open behaviour.
    """
    global _cache
    now_ts = _time.monotonic()

    if now_ts - _cache["timestamp"] < _CACHE_TTL:
        return _cache["nifty_chg"]

    _cache["timestamp"] = now_ts

    try:
        now_ist = datetime.now(IST)
        if now_ist.time() < time(10, 0):
            # Before 10 AM: opening auction noise not settled
            _cache["nifty_chg"] = 0.0
            return 0.0

        df = _fetch_nifty_5m()
        if df is None or df.empty or len(df) < 2:
            return 0.0

        today = df.index[-1].date()
        today_df = df[df.index.date == today]
        if len(today_df) < 2:
            return 0.0

        open_px    = float(today_df["open"].iloc[0])
        current_px = float(today_df["close"].iloc[-1])
        if open_px <= 0:
            return 0.0

        chg = (current_px - open_px) / open_px * 100
        _cache["nifty_chg"] = round(chg, 3)

        logger.debug(
            f"NiftyCorrelation: NIFTY {chg:+.2f}% "
            f"(open={open_px:.0f} current={current_px:.0f})"
        )
        return _cache["nifty_chg"]

    except Exception as exc:
        logger.debug(f"NiftyCorrelation: fetch error ({exc}) — returning 0.0")
        return 0.0


def get_divergence(
    symbol: str,
    symbol_df: pd.DataFrame,
    nifty_chg: float,
) -> DivergenceResult:
    """
    Compare symbol's intraday % change vs NIFTY's pre-fetched change.

    Args:
        symbol:     Kite symbol name (for logging only)
        symbol_df:  5m OHLCV DataFrame already fetched for this symbol
        nifty_chg:  NIFTY's intraday % change from get_nifty_change()

    Returns IN_LINE on any error — never blocks a signal on a data failure.
    """
    try:
        if symbol_df is None or symbol_df.empty:
            return _IN_LINE

        today = symbol_df.index[-1].date()
        today_df = symbol_df[symbol_df.index.date == today]

        if len(today_df) < 2:
            return _IN_LINE

        open_px    = float(today_df["open"].iloc[0])
        current_px = float(today_df["close"].iloc[-1])
        if open_px <= 0:
            return _IN_LINE

        stock_chg = (current_px - open_px) / open_px * 100

        if nifty_chg >= _NIFTY_MOVE_PCT and stock_chg < _STOCK_LAG_PCT:
            logger.debug(
                f"NiftyCorrelation: {symbol} LAGGING "
                f"(NIFTY {nifty_chg:+.2f}% / stock {stock_chg:+.2f}%)"
            )
            return DivergenceResult(
                nifty_chg_pct=round(nifty_chg, 2),
                stock_chg_pct=round(stock_chg, 2),
                label="LAGGING",
                suppress_buy=True,
                suppress_sell=False,
                amplify_sell=True,
            )

        if nifty_chg <= -_NIFTY_MOVE_PCT and stock_chg > -_STOCK_LAG_PCT:
            logger.debug(
                f"NiftyCorrelation: {symbol} LEADING "
                f"(NIFTY {nifty_chg:+.2f}% / stock {stock_chg:+.2f}%)"
            )
            return DivergenceResult(
                nifty_chg_pct=round(nifty_chg, 2),
                stock_chg_pct=round(stock_chg, 2),
                label="LEADING",
                suppress_buy=False,
                suppress_sell=True,
                amplify_sell=False,
            )

        return DivergenceResult(
            nifty_chg_pct=round(nifty_chg, 2),
            stock_chg_pct=round(stock_chg, 2),
            label="IN_LINE",
            suppress_buy=False,
            suppress_sell=False,
            amplify_sell=False,
        )

    except Exception as exc:
        logger.debug(f"NiftyCorrelation.get_divergence({symbol}): error ({exc}) — IN_LINE")
        return _IN_LINE


def _fetch_nifty_5m() -> pd.DataFrame | None:
    """Fetch NIFTY50 5-minute candles. Kite first, yfinance fallback."""
    try:
        from data.kite_auth import is_kite_available
        if is_kite_available():
            from data.kite_feed import fetch_kite_ohlcv
            df = fetch_kite_ohlcv("NIFTY 50", days=2, interval="5minute")
            if df is not None and len(df) >= 10:
                return df
    except Exception:
        pass

    try:
        import yfinance as yf
        df = yf.Ticker("^NSEI").history(period="2d", interval="5m")
        if df is not None and not df.empty:
            df.columns = [c.lower() for c in df.columns]
            return df
    except Exception:
        pass

    return None
