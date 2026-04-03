"""
Catalyst Scanner — parallel pre-market scan of all NIFTY50 stocks.

What this does:
  At 9:00 AM, scans every stock in the watchlist for corporate events and
  news from the previous day. Classifies each as BULLISH_CATALYST,
  BEARISH_CATALYST, or NEUTRAL. Stores the result in a module-level cache
  that the signal_check() loop queries throughout the trading day.

Why scan in parallel?
  With 50 stocks, sequential fetching takes 50+ seconds (1s per request).
  ThreadPoolExecutor(max_workers=10) cuts that to ~6–8 seconds.

Usage:
    from analysis.catalyst_scanner import scan_all_catalysts, get_todays_catalysts

    # At 9:00 AM (called from pre_market_scan):
    summary = scan_all_catalysts(watchlist)

    # During signal_check (returns cached result — fast):
    summary = get_todays_catalysts()
    catalyst_map = {r.symbol: r for r in summary.bullish + summary.bearish + summary.neutral}
"""

from __future__ import annotations

import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime

from loguru import logger

from data.instruments import NIFTY50_INSTRUMENTS
from data.news_catalyst import CatalystResult, news_catalyst_cache


@dataclass
class CatalystSummary:
    """Result of a full watchlist catalyst scan."""
    bullish:    list[CatalystResult] = field(default_factory=list)  # sorted by confidence desc
    bearish:    list[CatalystResult] = field(default_factory=list)
    neutral:    list[CatalystResult] = field(default_factory=list)
    scanned_at: datetime = field(default_factory=datetime.now)

    @property
    def total(self) -> int:
        return len(self.bullish) + len(self.bearish) + len(self.neutral)


# ── Module-level day cache ────────────────────────────────────────────
_last_summary:   CatalystSummary | None = None
_last_scan_date: date | None            = None


def scan_all_catalysts(symbols: list[str] | None = None) -> CatalystSummary:
    """
    Scan the given symbol list (or full NIFTY50 if None) for catalysts.

    Fetches in parallel with up to 10 workers. A 1-second gap is NOT added
    between workers here — the per-symbol fetch already has NSE's rate-limit
    response handled by the requests timeout, and yfinance is lenient.
    Results are stored in the module-level cache and returned.

    This function always does a fresh fetch (use get_todays_catalysts() for
    the cached intra-day version).
    """
    global _last_summary, _last_scan_date

    if symbols is None:
        symbols = list(NIFTY50_INSTRUMENTS.keys())

    if not symbols:
        summary = CatalystSummary()
        _last_summary = summary
        _last_scan_date = date.today()
        return summary

    logger.info(f"Catalyst scan started: {len(symbols)} symbols")
    start = _time.monotonic()

    results: list[CatalystResult] = []

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {
            pool.submit(_safe_get_catalyst, sym): sym
            for sym in symbols
        }
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                results.append(result)

    bullish = sorted(
        [r for r in results if r.direction == "BULLISH_CATALYST"],
        key=lambda r: r.confidence, reverse=True,
    )
    bearish = sorted(
        [r for r in results if r.direction == "BEARISH_CATALYST"],
        key=lambda r: r.confidence, reverse=True,
    )
    neutral = [r for r in results if r.direction == "NEUTRAL"]

    summary = CatalystSummary(
        bullish=bullish,
        bearish=bearish,
        neutral=neutral,
        scanned_at=datetime.now(),
    )

    elapsed = _time.monotonic() - start
    logger.info(
        f"Catalyst scan complete in {elapsed:.1f}s: "
        f"{len(bullish)} BULLISH | {len(bearish)} BEARISH | {len(neutral)} NEUTRAL"
    )

    _last_summary = summary
    _last_scan_date = date.today()
    return summary


def get_todays_catalysts() -> CatalystSummary:
    """
    Return the day's catalyst summary.

    Returns the cached result if scan_all_catalysts() was already called
    today. Otherwise runs a fresh scan (blocks until complete).

    Called frequently from signal_check() — the cached path is fast.
    """
    if _last_summary is not None and _last_scan_date == date.today():
        return _last_summary

    # First call of the day (or no pre-market scan ran) — run now
    logger.info("get_todays_catalysts: no cached scan for today, running now")
    return scan_all_catalysts()


def _safe_get_catalyst(symbol: str) -> CatalystResult | None:
    """Wrapper that catches all exceptions so pool workers never crash."""
    try:
        return news_catalyst_cache.get_catalyst(symbol)
    except Exception as exc:
        logger.debug(f"Catalyst fetch failed for {symbol}: {exc}")
        return None
