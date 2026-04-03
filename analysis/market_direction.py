"""
Intraday Market Direction — detects whether the market is trending UP or DOWN today.

Why this matters:
  India VIX tells us *how much* fear is in the market, but not *which direction*
  the market is moving. On high-VIX days like 2026-04-02 (VIX=25.4), the market
  went UP +1.42%. Blocking BUYs because VIX was elevated was wrong — the correct
  action was to block SHORTS and allow LONGS.

  This module detects intraday direction from NIFTY50 so the VIX suppression
  logic can target the right side (shorts on an up day, longs on a down day).

How it works:
  After 10:00 AM (once the opening noise settles), compare:
    - NIFTY50's current price vs its 9:15 open
    - NIFTY50's 5-min EMA9 vs EMA21 (direction from recent candles)

  Both must agree for a confirmed direction. If they disagree, return NEUTRAL
  (fail-safe — don't change suppression behaviour when unsure).

Cache: 5-minute TTL (same as VIX and regime detector).
Data source: Kite REST API first, yfinance fallback (same priority as the rest of the bot).
"""

from __future__ import annotations

import math
import time as _time
from enum import Enum

import ta
from loguru import logger


class MarketDirection(str, Enum):
    UP      = "UP"       # NIFTY trending up intraday  → suppress SELL entries
    DOWN    = "DOWN"     # NIFTY trending down intraday → suppress BUY entries
    NEUTRAL = "NEUTRAL"  # unclear / pre-10 AM / data missing → no suppression change


_CACHE_TTL = 300   # 5 minutes

_cache: dict = {
    "direction": MarketDirection.NEUTRAL,
    "nifty_open": None,
    "nifty_current": None,
    "change_pct": None,
    "timestamp": 0.0,
}


def get_market_direction() -> MarketDirection:
    """
    Return today's intraday NIFTY50 direction with TTL cache.

    Returns NEUTRAL before 10:00 AM (too early to read direction reliably)
    and on any data fetch failure (fail-open: don't change suppression when unsure).
    """
    global _cache
    now_ts = _time.monotonic()

    if now_ts - _cache["timestamp"] < _CACHE_TTL:
        return _cache["direction"]

    _cache["timestamp"] = now_ts

    try:
        from datetime import datetime, time
        from config.settings import IST
        now_ist = datetime.now(IST)

        # Before 10:00 AM: opening noise not settled — return NEUTRAL
        if now_ist.time() < time(10, 0):
            _cache["direction"] = MarketDirection.NEUTRAL
            return MarketDirection.NEUTRAL

        df = _fetch_nifty_5m()
        if df is None or len(df) < 20:
            _cache["direction"] = MarketDirection.NEUTRAL
            return MarketDirection.NEUTRAL

        today = df.index[-1].date()
        today_df = df[df.index.date == today]
        if len(today_df) < 5:
            _cache["direction"] = MarketDirection.NEUTRAL
            return MarketDirection.NEUTRAL

        # Signal 1: price vs open
        nifty_open    = float(today_df["open"].iloc[0])
        nifty_current = float(today_df["close"].iloc[-1])
        change_pct    = (nifty_current - nifty_open) / nifty_open

        # Signal 2: EMA9 vs EMA21 on 5m candles
        close = df["close"]
        ema9  = float(ta.trend.EMAIndicator(close, window=9).ema_indicator().iloc[-1])
        ema21 = float(ta.trend.EMAIndicator(close, window=21).ema_indicator().iloc[-1])

        if math.isnan(ema9) or math.isnan(ema21):
            _cache["direction"] = MarketDirection.NEUTRAL
            return MarketDirection.NEUTRAL

        price_up  = change_pct > 0.002   # NIFTY > 0.2% above open  → up day
        price_dn  = change_pct < -0.002  # NIFTY > 0.2% below open  → down day
        ema_up    = ema9 > ema21
        ema_dn    = ema9 < ema21

        if price_up and ema_up:
            direction = MarketDirection.UP
        elif price_dn and ema_dn:
            direction = MarketDirection.DOWN
        else:
            direction = MarketDirection.NEUTRAL  # signals disagree → don't act

        _cache.update({
            "direction":     direction,
            "nifty_open":    round(nifty_open, 0),
            "nifty_current": round(nifty_current, 0),
            "change_pct":    round(change_pct * 100, 2),
        })

        logger.debug(
            f"MarketDirection: {direction.value} | "
            f"NIFTY {nifty_current:.0f} ({change_pct:+.2%} vs open) | "
            f"EMA9={ema9:.0f} {'>' if ema_up else '<'} EMA21={ema21:.0f}"
        )
        return direction

    except Exception as exc:
        logger.debug(f"MarketDirection: fetch error ({exc}) — returning NEUTRAL")
        _cache["direction"] = MarketDirection.NEUTRAL
        return MarketDirection.NEUTRAL


def get_direction_details() -> dict:
    """Return the raw values from the last direction computation (for dashboard)."""
    return {k: v for k, v in _cache.items() if k != "timestamp"}


def _fetch_nifty_5m():
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
