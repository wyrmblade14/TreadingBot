"""
Fundamentals data layer — cached yfinance fundamental metrics for NIFTY50 stocks.

What are "fundamentals"?
  Fundamentals are financial metrics that describe a company's health and value,
  as opposed to technicals (price patterns). Examples:
    - P/E ratio (Price-to-Earnings): how much investors pay per rupee of profit.
      A high P/E means expensive / high growth expectation.
    - Debt-to-Equity: how much of the company is funded by debt vs. shareholders.
      High D/E = higher risk if earnings fall.
    - EPS (Earnings Per Share): profit attributable to each share. Growing EPS
      means the company is becoming more profitable over time.

Why use fundamentals in a short-term trading bot?
  Even intraday traders benefit from knowing:
    1. Earnings blackout windows — volatility spikes near results; risk management
       demands we stand aside for 3 days before and 1 day after.
    2. Earnings trend — a structurally deteriorating stock amplifies downside;
       avoid new BUY entries if EPS has been shrinking for 4 quarters.
    3. Valuation context — extremely high P/E stocks are fragile to bad news;
       useful signal for the dashboard's analysis views.

Data source:
  yfinance (Yahoo Finance) — free, no API key, covers all NSE stocks via .NS suffix.
  Cached for 24 hours per symbol; fundamentals don't change intraday.

Cache design mirrors data/india_vix.py: module-level dicts keyed by symbol,
each value is a (data, monotonic_timestamp) tuple.

Usage:
    from data.fundamentals import fundamentals_cache

    info = fundamentals_cache.get_fundamentals("RELIANCE")
    trend = fundamentals_cache.get_quarterly_earnings_trend("INFY")
    blackout = fundamentals_cache.is_earnings_blackout("TCS")
"""

from __future__ import annotations

import time as _time
from datetime import date, datetime
from typing import Literal

import yfinance as yf
from loguru import logger

from data.instruments import KITE_TO_YF

# ── Cache TTL ─────────────────────────────────────────────────────────
_CACHE_TTL = 86400  # 24 hours — fundamentals don't change intraday

# ── Fundamental keys we care about ───────────────────────────────────
_FUNDAMENTAL_KEYS = (
    "trailingPE",
    "forwardPE",
    "priceToBook",
    "profitMargins",
    "earningsQuarterlyGrowth",
    "debtToEquity",
    "trailingEps",
    "forwardEps",
    "revenuePerShare",
    "grossProfits",
    "totalRevenue",
    "totalDebt",
    "dividendYield",
    "bookValue",
    "heldPercentInsiders",
    "heldPercentInstitutions",
)

# ── Per-symbol TTL caches ─────────────────────────────────────────────
# Each entry: symbol → (data, monotonic_timestamp)
_fundamentals_cache: dict[str, tuple[dict, float]] = {}
_trend_cache: dict[str, tuple[str, float]] = {}
_calendar_cache: dict[str, tuple[date | None, float]] = {}


# ── Helper: Kite → yfinance symbol translation ────────────────────────

def _to_yf(symbol: str) -> str:
    """Convert a Kite symbol (e.g. "RELIANCE") to yfinance format ("RELIANCE.NS")."""
    return KITE_TO_YF.get(symbol, symbol + ".NS")


class FundamentalsCache:
    """
    Provides cached access to fundamental data for NIFTY50 stocks.

    All methods accept Kite-format symbols (e.g. "RELIANCE", "INFY") and
    translate internally to yfinance's .NS suffix format.

    Caching is module-level (shared across all instances) with a 24-hour TTL
    so that multiple callers — strategies, risk manager, dashboard — all share
    the same fetched data without redundant network calls.
    """

    # ── Public API ────────────────────────────────────────────────────

    def get_fundamentals(self, symbol: str) -> dict:
        """
        Return a dict of fundamental metrics for *symbol*.

        Keys (all values are float or None if unavailable):
            trailingPE, forwardPE, priceToBook, profitMargins,
            earningsQuarterlyGrowth, debtToEquity, trailingEps, forwardEps,
            revenuePerShare, grossProfits, totalRevenue, totalDebt,
            dividendYield, bookValue, heldPercentInsiders,
            heldPercentInstitutions

        Returns {} on any fetch or parse error (fail-open: never block trading
        because yfinance had a bad day).
        """
        now = _time.monotonic()

        # Cache hit
        if symbol in _fundamentals_cache:
            data, ts = _fundamentals_cache[symbol]
            if now - ts < _CACHE_TTL:
                logger.debug(f"Fundamentals cache hit: {symbol}")
                return dict(data)

        # Cache miss — fetch from yfinance
        try:
            yf_sym = _to_yf(symbol)
            ticker = yf.Ticker(yf_sym)
            info = ticker.info  # large dict; we cherry-pick below

            result: dict = {}
            for key in _FUNDAMENTAL_KEYS:
                raw = info.get(key)
                try:
                    result[key] = float(raw) if raw is not None else None
                except (TypeError, ValueError):
                    result[key] = None

            _fundamentals_cache[symbol] = (result, now)
            logger.debug(f"Fundamentals fetched: {symbol} ({yf_sym})")
            return dict(result)

        except Exception as exc:
            logger.warning(f"Fundamentals fetch failed for {symbol}: {exc}")
            return {}

    def get_quarterly_earnings_trend(
        self, symbol: str
    ) -> Literal["IMPROVING", "STABLE", "DETERIORATING"]:
        """
        Classify the company's recent EPS trajectory using last 4 quarters.

        Method:
          1. Pull quarterly income statement from yfinance.
          2. Find "Basic EPS" or "Diluted EPS" row (whichever exists first).
          3. Take the 4 most recent quarters and compute 3 sequential diffs
             (quarter-over-quarter changes).
          4. ≥2 positive diffs  → "IMPROVING"
             ≥2 negative diffs  → "DETERIORATING"
             otherwise          → "STABLE"

        Beginner note: EPS (Earnings Per Share) is net profit divided by the
        number of shares. Rising EPS quarter-over-quarter means the company is
        becoming more profitable — a positive sign for long positions.

        Returns "STABLE" on any error or missing data (fail-open).
        """
        now = _time.monotonic()

        # Cache hit
        if symbol in _trend_cache:
            trend, ts = _trend_cache[symbol]
            if now - ts < _CACHE_TTL:
                logger.debug(f"EPS trend cache hit: {symbol}")
                return trend  # type: ignore[return-value]

        # Cache miss — fetch and classify
        try:
            yf_sym = _to_yf(symbol)
            ticker = yf.Ticker(yf_sym)

            # Try newer attribute first, fall back to legacy name
            try:
                df = ticker.quarterly_income_stmt
            except Exception:
                df = ticker.quarterly_financials

            if df is None or df.empty:
                logger.warning(f"EPS trend: no quarterly data for {symbol}")
                _trend_cache[symbol] = ("STABLE", now)
                return "STABLE"

            # Find the EPS row — try "Basic EPS" then "Diluted EPS"
            eps_row = None
            for label in ("Basic EPS", "Diluted EPS"):
                # df.index may contain multi-level or plain string index
                matches = [idx for idx in df.index if str(idx).strip() == label]
                if matches:
                    eps_row = df.loc[matches[0]]
                    break

            if eps_row is None:
                logger.warning(
                    f"EPS trend: neither 'Basic EPS' nor 'Diluted EPS' found "
                    f"for {symbol}. Available rows: {list(df.index)[:10]}"
                )
                _trend_cache[symbol] = ("STABLE", now)
                return "STABLE"

            # Take the 4 most recent quarters (columns are sorted newest-first)
            recent = eps_row.iloc[:4].dropna()

            if len(recent) < 2:
                logger.warning(f"EPS trend: fewer than 2 quarters of data for {symbol}")
                _trend_cache[symbol] = ("STABLE", now)
                return "STABLE"

            # Compute sequential diffs: diff[0] = recent[0] - recent[1], etc.
            # (recent is newest-first, so diff > 0 means latest quarter > prior quarter)
            values = [float(v) for v in recent]
            diffs = [values[i] - values[i + 1] for i in range(len(values) - 1)]

            positive = sum(1 for d in diffs if d > 0)
            negative = sum(1 for d in diffs if d < 0)

            if positive >= 2:
                trend: Literal["IMPROVING", "STABLE", "DETERIORATING"] = "IMPROVING"
            elif negative >= 2:
                trend = "DETERIORATING"
            else:
                trend = "STABLE"

            _trend_cache[symbol] = (trend, now)
            logger.debug(
                f"EPS trend computed: {symbol} → {trend} "
                f"(diffs={[round(d, 2) for d in diffs]})"
            )
            return trend

        except Exception as exc:
            logger.warning(f"EPS trend fetch failed for {symbol}: {exc}")
            _trend_cache[symbol] = ("STABLE", now)
            return "STABLE"

    def get_earnings_calendar(self, symbol: str) -> date | None:
        """
        Return the next upcoming earnings date for *symbol*, or None.

        Only returns future dates (today + 1 day or later). Past earnings dates
        are ignored — we care about upcoming volatility events, not history.

        Source: yfinance ticker.calendar["Earnings Date"]. This field can be a
        list of datetime objects or a single datetime; we normalise to a list,
        filter to future dates, and return the earliest.

        Returns None on any error or if no upcoming date is found (fail-open).
        """
        now = _time.monotonic()
        today = date.today()

        # Cache hit
        if symbol in _calendar_cache:
            earnings_date, ts = _calendar_cache[symbol]
            if now - ts < _CACHE_TTL:
                logger.debug(f"Earnings calendar cache hit: {symbol}")
                return earnings_date

        # Cache miss — fetch from yfinance
        try:
            yf_sym = _to_yf(symbol)
            ticker = yf.Ticker(yf_sym)
            cal = ticker.calendar  # dict or None

            if not cal or "Earnings Date" not in cal:
                _calendar_cache[symbol] = (None, now)
                return None

            raw = cal["Earnings Date"]

            # Normalise to a flat list of date objects
            if not isinstance(raw, (list, tuple)):
                raw = [raw]

            future_dates: list[date] = []
            for item in raw:
                try:
                    if isinstance(item, datetime):
                        d = item.date()
                    elif isinstance(item, date):
                        d = item
                    else:
                        # May be a pandas Timestamp or string
                        d = _parse_date(item)

                    if d is not None and d > today:
                        future_dates.append(d)
                except Exception:
                    continue

            result = min(future_dates) if future_dates else None
            _calendar_cache[symbol] = (result, now)
            logger.debug(f"Earnings calendar fetched: {symbol} → {result}")
            return result

        except Exception as exc:
            logger.warning(f"Earnings calendar fetch failed for {symbol}: {exc}")
            _calendar_cache[symbol] = (None, now)
            return None

    def is_earnings_blackout(
        self,
        symbol: str,
        days_before: int = 3,
        days_after: int = 1,
    ) -> bool:
        """
        Return True if today falls within the earnings volatility window.

        The window is [earnings_date − days_before, earnings_date + days_after]
        (inclusive on both ends).

        Why a blackout window?
          Earnings announcements cause large, unpredictable gaps. Even a good
          technical setup can be wiped out by a single EPS surprise. The standard
          approach is to step aside for 3 days before results (whisper numbers and
          analyst commentary start moving the price) and 1 day after (post-result
          volatility continues into the next session).

        Returns False on any error — never block trading due to data issues.
        """
        try:
            earnings_date = self.get_earnings_calendar(symbol)
            if earnings_date is None:
                return False

            today = date.today()
            from datetime import timedelta

            window_start = earnings_date - timedelta(days=days_before)
            window_end = earnings_date + timedelta(days=days_after)

            in_blackout = window_start <= today <= window_end
            if in_blackout:
                logger.debug(
                    f"Earnings blackout active: {symbol} "
                    f"(earnings={earnings_date}, window={window_start}–{window_end})"
                )
            return in_blackout

        except Exception as exc:
            logger.warning(f"is_earnings_blackout error for {symbol}: {exc}")
            return False  # fail-open


# ── Module-level singleton ────────────────────────────────────────────
fundamentals_cache = FundamentalsCache()
"""
Module-level singleton. Import and use directly:

    from data.fundamentals import fundamentals_cache

    pe = fundamentals_cache.get_fundamentals("RELIANCE").get("trailingPE")
    trend = fundamentals_cache.get_quarterly_earnings_trend("TCS")
    blackout = fundamentals_cache.is_earnings_blackout("INFY")
"""


# ── Private helpers ───────────────────────────────────────────────────

def _parse_date(value: object) -> date | None:
    """
    Best-effort conversion of an unknown date-like object to a Python date.
    Handles pandas Timestamp, ISO strings, and anything with a .date() method.
    """
    # pandas Timestamp and datetime both have .date()
    if hasattr(value, "date"):
        try:
            return value.date()  # type: ignore[union-attr]
        except Exception:
            pass

    # ISO string e.g. "2026-05-12"
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except Exception:
            pass

    return None
