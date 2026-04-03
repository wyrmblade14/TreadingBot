"""
India VIX — market fear gauge fetched from yfinance.

What is India VIX?
  India VIX (Volatility Index) is published by NSE and measures how much
  the options market expects NIFTY50 to move over the next 30 days.
  It is the Indian equivalent of the US "Fear Index" (VIX).

  Scale:
    VIX < 13   → Low fear   — market is calm, momentum strategies work well
    VIX 13–22  → Normal     — typical intraday conditions
    VIX 22–30  → Elevated   — some fear; avoid new BUY entries (market may gap down)
    VIX > 30   → Extreme    — crash/event conditions; suppress ALL new entries

  Historical context (India VIX):
    Normal range: 10–15 | High-volatility period: 20–30 | Actual crash: 40+ (COVID = 84)
    Original thresholds (20/25) were too tight — blocked trading for weeks during
    tariff-driven market stress in Mar–Apr 2026. Recalibrated to 22/30.

  In simple terms: when VIX is high, even good setups fail because random
  price spikes trigger stop-losses before the target is reached.

Why not NSE PCR (Put-Call Ratio)?
  PCR from NSE requires web scraping with session cookies that change
  frequently — brittle in a long-running bot. India VIX is available
  free via yfinance (^INDIAVIX) and conveys the same directional signal.

Usage in the bot:
  - Fetched at 9:00 AM pre-market scan and logged.
  - Checked in RiskManager.evaluate() before approving any signal.
  - Cached for 5 minutes to avoid hammering yfinance on every candle.
"""

from __future__ import annotations

import time as _time

import yfinance as yf
from loguru import logger

# ── Thresholds ────────────────────────────────────────────────────────
VIX_LOW     = 13.0   # Below this: low fear — normal trading
VIX_HIGH    = 22.0   # Above this: elevated fear — suppress BUY entries
VIX_EXTREME = 30.0   # Above this: extreme fear — suppress ALL entries

# ── In-memory TTL cache ───────────────────────────────────────────────
_CACHE_TTL = 300   # 5 minutes

_cache: dict = {
    "vix":        None,
    "level":      "normal",
    "skip_buys":  False,
    "skip_sells": False,
    "skip_all":   False,
    "timestamp":  0.0,
}


def get_vix_data() -> dict:
    """
    Return current India VIX with TTL cache.

    Returns a dict with keys:
        vix       (float)  — latest VIX value
        level     (str)    — "low" | "normal" | "high" | "extreme"
        skip_buys (bool)   — True when VIX > VIX_HIGH (20)
        skip_all  (bool)   — True when VIX > VIX_EXTREME (25)

    On fetch failure returns the last cached value, or a safe default
    that allows trading to continue (fail-open behaviour).
    """
    global _cache
    now = _time.monotonic()

    # Return cached result if still fresh
    if now - _cache["timestamp"] < _CACHE_TTL and _cache["vix"] is not None:
        return dict(_cache)

    try:
        ticker = yf.Ticker("^INDIAVIX")
        df = ticker.history(period="5d", interval="1d")

        if df is None or df.empty:
            logger.warning("IndiaVIX: no data from yfinance — using last cached value")
            return _safe_default()

        vix = float(df["Close"].iloc[-1])
        level, skip_buys, skip_sells, skip_all = _classify(vix)

        _cache.update({
            "vix":        round(vix, 2),
            "level":      level,
            "skip_buys":  skip_buys,
            "skip_sells": skip_sells,
            "skip_all":   skip_all,
            "timestamp":  now,
        })
        logger.debug(f"IndiaVIX refreshed: {vix:.1f} ({level.upper()})")
        return dict(_cache)

    except Exception as exc:
        logger.warning(f"IndiaVIX fetch failed ({exc}) — using last cached value")
        return _safe_default()


def _classify(vix: float) -> tuple[str, bool, bool, bool]:
    """
    Return (level_str, skip_buys, skip_sells, skip_all) for a given VIX value.

    VIX alone cannot tell us which direction to suppress — the market can be
    fearful and still rally (e.g. short-squeeze days). We pair VIX with the
    intraday NIFTY direction to target the right side:
      - NIFTY UP day   → fear from sellers being squeezed → skip SELL entries
      - NIFTY DOWN day → fear from buyers panicking out   → skip BUY entries
      - NEUTRAL        → no directional read yet          → skip BUYs (conservative)

    VIX > VIX_EXTREME overrides direction — suppress everything.
    """
    if vix > VIX_EXTREME:
        return "extreme", True, True, True

    if vix > VIX_HIGH:
        # Elevated fear — use intraday direction to decide which side to suppress
        try:
            from analysis.market_direction import get_market_direction, MarketDirection
            direction = get_market_direction()
            if direction == MarketDirection.UP:
                # Market going up despite fear → short-squeeze / relief rally
                # Shorts are deadly; longs are fine
                return "high", False, True, False
            elif direction == MarketDirection.DOWN:
                # Market falling despite/because of fear → panic selling
                # Longs are dangerous; shorts may work
                return "high", True, False, False
        except Exception:
            pass
        # Neutral or unknown → conservative default: skip buys
        return "high", True, False, False

    if vix < VIX_LOW:
        return "low", False, False, False
    return "normal", False, False, False


def _safe_default() -> dict:
    """Return the cached value if available, else a fail-open default."""
    if _cache["vix"] is not None:
        return dict(_cache)
    # No data at all — allow trading (fail-open: don't block on network issues)
    return {"vix": 15.0, "level": "normal", "skip_buys": False, "skip_sells": False, "skip_all": False}
