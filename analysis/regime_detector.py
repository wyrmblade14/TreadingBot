"""
Market Regime Detector — classifies each trading day as Trending, Ranging, or Volatile.

Why this matters:
  All 3 of your strategies are momentum-based. Momentum strategies only work when
  the market has clear directional conviction. In a choppy ranging market, EMA
  crossovers and ORB breakouts fire frequently but quickly reverse. In a volatile
  spike day, stop-losses get hit by noise rather than genuine reversals.

  By detecting the regime first, we only fire signals when conditions suit the
  strategy type — reducing bad trades without changing any strategy logic.

How it works:
  Two metrics computed from NIFTY50 index (^NSEI) daily data:

  ADX (Average Directional Index):
    Measures trend *strength* on a scale of 0–100. It answers: "How much
    conviction does the market have right now?" — not direction, just strength.
      < 20 = weak/no trend → Ranging
      20–25 = developing trend (borderline)
      > 25 = strong trend → Trending

  ATR Ratio (Volatility check):
    Compares today's Average True Range (daily price swing size) against its
    own 20-day rolling average. If today's swing is 1.5× the recent norm,
    the market is unusually spiky — stops get triggered randomly.
    ATR ratio > 1.5 → Volatile (overrides any trend reading)

Regime → Strategy behaviour:
  TRENDING  → All 3 strategies fire normally (this is their home turf)
  RANGING   → EMA Crossover + ORB suppressed (crossovers flip too often)
              RSI+MACD still fires (RSI catches range-extreme reversals)
  VOLATILE  → ALL strategies suppressed (price spikes are unpredictable)
  UNKNOWN   → All strategies fire (fail-safe — data fetch failed)

Data source: NIFTY50 index (^NSEI) from yfinance — free, no API key needed.
Cache: result held for 5 minutes so strategies don't hit yfinance every candle.
"""

from __future__ import annotations

import time
from enum import Enum

import pandas as pd
import ta
import yfinance as yf
from loguru import logger


# ── Regime classification ─────────────────────────────────────────────

class MarketRegime(str, Enum):
    TRENDING = "Trending"   # ADX > 25, normal ATR → run all strategies
    RANGING  = "Ranging"    # ADX < 20, normal ATR → suppress EMA + ORB
    VOLATILE = "Volatile"   # ATR spike            → suppress ALL strategies
    UNKNOWN  = "Unknown"    # data fetch failed     → fail-safe, allow all


# ── Thresholds ────────────────────────────────────────────────────────
# Tune these if you want a stricter or more relaxed regime filter.

ADX_TRENDING_THRESHOLD = 25.0   # ADX above this = confirmed strong trend
ADX_RANGING_THRESHOLD  = 20.0   # ADX below this = no trend / sideways
ATR_VOLATILE_RATIO     = 1.5    # ATR today > 1.5× its 20-day avg = spike day

# Strategy names that are ALLOWED in each non-trending regime:
#   RANGING: RSI+MACD only (its RSI component catches range-end reversals)
#   VOLATILE: none allowed
_RANGING_ALLOWED: set[str]  = {"rsi_macd_combo"}
_VOLATILE_ALLOWED: set[str] = set()


# ── Simple TTL cache ──────────────────────────────────────────────────
# Shared across all calls within the same process. Avoids hammering yfinance
# on every 5-minute signal check across 50 NIFTY50 stocks.

_cache: dict = {
    "regime":    MarketRegime.UNKNOWN,
    "details":   {},
    "timestamp": 0.0,
}
_CACHE_TTL_SECONDS = 300   # refresh at most once every 5 minutes


# ── Pure computation (testable without network) ───────────────────────

def get_regime_from_df(df: pd.DataFrame) -> tuple[MarketRegime, dict]:
    """
    Compute the market regime from a NIFTY50 daily OHLCV DataFrame.

    This is a pure function — no network calls. Safe to use in unit tests
    by passing any synthetic DataFrame.

    Args:
        df: Daily OHLCV DataFrame with at least 30 rows.
            Columns (case-insensitive): open, high, low, close, volume.

    Returns:
        (MarketRegime, details_dict)
        details_dict has keys: adx, atr, atr_20avg, atr_ratio, regime
    """
    MIN_ROWS = 30   # ADX(14) needs ~28 rows of lead; 20-day ATR avg needs 20
    if df is None or len(df) < MIN_ROWS:
        return MarketRegime.UNKNOWN, {"reason": f"need ≥{MIN_ROWS} rows, got {len(df) if df is not None else 0}"}

    # Normalise column names — yfinance returns Title Case ("Close", "High" …)
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    high  = df["high"]
    low   = df["low"]
    close = df["close"]

    # ── Step 1: ATR ratio — is today unusually volatile? ─────────────
    # ATR (Average True Range) measures the average daily price swing.
    # Dividing today's ATR by the 20-day rolling average tells us whether
    # today's movement is bigger than normal.
    atr_series   = ta.volatility.AverageTrueRange(
        high=high, low=low, close=close, window=14
    ).average_true_range()

    current_atr  = float(atr_series.iloc[-1])
    avg_atr_20d  = float(atr_series.rolling(20).mean().iloc[-1])

    if pd.isna(current_atr) or pd.isna(avg_atr_20d) or avg_atr_20d == 0:
        return MarketRegime.UNKNOWN, {"reason": "ATR computation returned NaN"}

    atr_ratio = current_atr / avg_atr_20d

    # ── Step 2: ADX — how strong is the current trend? ───────────────
    # ADX ignores direction — it measures the *strength* of whatever
    # trend exists. A high ADX means the market is committed to its
    # current move (up or down). A low ADX means it's aimlessly drifting.
    adx_series  = ta.trend.ADXIndicator(
        high=high, low=low, close=close, window=14
    ).adx()
    current_adx = float(adx_series.iloc[-1])

    if pd.isna(current_adx):
        return MarketRegime.UNKNOWN, {"reason": "ADX computation returned NaN"}

    details = {
        "adx":       round(current_adx, 1),
        "atr":       round(current_atr, 2),
        "atr_20avg": round(avg_atr_20d, 2),
        "atr_ratio": round(atr_ratio, 2),
    }

    # ── Step 3: Classify ──────────────────────────────────────────────
    # Volatile takes priority — even a trending market can have a spike day.
    if atr_ratio >= ATR_VOLATILE_RATIO:
        regime = MarketRegime.VOLATILE
    elif current_adx >= ADX_TRENDING_THRESHOLD:
        regime = MarketRegime.TRENDING
    else:
        regime = MarketRegime.RANGING

    details["regime"] = regime.value
    return regime, details


# ── Live fetch with caching ───────────────────────────────────────────

def get_current_regime() -> MarketRegime:
    """
    Return the current NIFTY50 market regime.

    Fetches 60 days of daily NIFTY50 data on first call, then caches the
    result for 5 minutes. Safe to call from every strategy on every candle.

    If data fetch fails, returns UNKNOWN (fail-safe = allow all strategies).
    """
    global _cache
    now = time.monotonic()

    # Return cached result if still fresh
    if now - _cache["timestamp"] < _CACHE_TTL_SECONDS and _cache["regime"] != MarketRegime.UNKNOWN:
        return _cache["regime"]

    try:
        ticker = yf.Ticker("^NSEI")
        df     = ticker.history(period="60d", interval="1d")

        if df is None or df.empty or len(df) < 30:
            logger.warning("RegimeDetector: not enough NIFTY50 data — defaulting to UNKNOWN")
            _set_cache(MarketRegime.UNKNOWN, {}, now)
            return MarketRegime.UNKNOWN

        regime, details = get_regime_from_df(df)
        _set_cache(regime, details, now)

        logger.info(
            f"RegimeDetector: {regime.value} | "
            f"ADX={details.get('adx', '?')} | "
            f"ATR={details.get('atr', '?')} ({details.get('atr_ratio', '?')}× 20d avg)"
        )
        return regime

    except Exception as exc:
        logger.warning(f"RegimeDetector: fetch error ({exc}) — defaulting to UNKNOWN")
        _set_cache(MarketRegime.UNKNOWN, {}, now)
        return MarketRegime.UNKNOWN


def get_regime_details() -> dict:
    """
    Return the raw metric values from the last regime computation.

    Useful for displaying in the dashboard. Call get_current_regime() first
    to ensure the cache is populated.

    Returns dict with keys: regime, adx, atr, atr_20avg, atr_ratio.
    """
    return dict(_cache.get("details", {}))


def regime_allows_strategy(regime: MarketRegime, strategy_name: str) -> bool:
    """
    Return True if this strategy is allowed to fire in the current regime.

    Args:
        regime:        The current market regime.
        strategy_name: Internal name of the strategy (e.g. "ema_crossover").

    Returns:
        True  → strategy may generate signals as normal.
        False → strategy should return HOLD without computing indicators.

    Rules:
        TRENDING → all strategies allowed (strong directional market)
        RANGING  → only rsi_macd_combo allowed (RSI catches range extremes)
        VOLATILE → no strategy allowed (stops hit by noise, not reversals)
        UNKNOWN  → all allowed (fail-safe: don't suppress when unsure)
    """
    if regime == MarketRegime.TRENDING or regime == MarketRegime.UNKNOWN:
        return True
    if regime == MarketRegime.RANGING:
        return strategy_name in _RANGING_ALLOWED
    if regime == MarketRegime.VOLATILE:
        return strategy_name in _VOLATILE_ALLOWED
    return True   # defensive default


# ── Internal helpers ──────────────────────────────────────────────────

def _set_cache(regime: MarketRegime, details: dict, ts: float) -> None:
    global _cache
    _cache["regime"]    = regime
    _cache["details"]   = details
    _cache["timestamp"] = ts
