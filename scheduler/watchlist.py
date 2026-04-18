"""
Daily watchlist selection for scheduler jobs.

This module keeps stock-universe selection out of scheduler/job_runner.py.
The job runner should orchestrate time-based jobs; this file decides which
symbols those jobs should scan.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from analysis.fundamental_selector import FundamentalPick, select_fundamental_watchlist
from data.instruments import NIFTY50_INSTRUMENTS

if TYPE_CHECKING:
    from analysis.fundamental_analyst import FundamentalJudgment

_APPROVED_FILE = Path("config/approved_symbols.json")


@dataclass
class DailyWatchlist:
    """
    Selected symbol universe for one trading session.

    source:
      - "approved_weekly": locked by weekend review (assign_strategies.py --optimize)
      - "fundamental": selected by analysis.fundamental_selector
      - "static_fallback": old first-N order because fundamentals were unavailable
      - "empty": requested size resolved to zero
    """

    symbols: list[str]
    ranked_picks: list[FundamentalPick] = field(default_factory=list)
    source: str = "fundamental"

    def detail_strings(self) -> list[str]:
        """Human-readable symbol(score,sector) strings for logging."""
        ranked_by_symbol = {p.symbol: p for p in self.ranked_picks}
        details: list[str] = []
        for symbol in self.symbols:
            pick = ranked_by_symbol.get(symbol)
            details.append(f"{symbol}({pick.score}/5,{pick.sector})" if pick else symbol)
        return details


def _load_approved_symbols() -> list[str] | None:
    """
    Load this week's approved symbols from config/approved_symbols.json.

    Returns None if the file is missing or expired so the caller can fall
    through to the fundamentals-based selection.
    """
    if not _APPROVED_FILE.exists():
        return None
    try:
        data = json.loads(_APPROVED_FILE.read_text())
        expires = date.fromisoformat(data.get("expires", "2000-01-01"))
        if date.today() > expires:
            logger.warning("approved_symbols.json expired — falling back to fundamentals")
            return None
        symbols = [s["symbol"] for s in data.get("symbols", [])]
        if not symbols:
            return None
        logger.info(
            f"Approved weekly universe loaded ({len(symbols)} symbols, expires {expires}): {symbols}"
        )
        return symbols
    except Exception as exc:
        logger.warning(f"Could not load approved_symbols.json: {exc} — falling back to fundamentals")
        return None


def static_watchlist(watchlist_size: int) -> list[str]:
    """Return the deterministic first-N NIFTY50 watchlist as safe fallback."""
    try:
        size = int(watchlist_size)
    except (TypeError, ValueError):
        size = 10

    size = max(0, min(size, len(NIFTY50_INSTRUMENTS)))
    return [i.kite_symbol for i in NIFTY50_INSTRUMENTS[:size]]


def select_daily_watchlist(watchlist_size: int) -> DailyWatchlist:
    """
    Select today's scan universe.

    Priority:
      1. approved_symbols.json  — locked by weekend review, valid LOCK_DAYS days
      2. Fundamentals selector  — ranks NIFTY50 by sector-relative score
      3. Static fallback        — first-N NIFTY50 order (data unavailable)
    """
    fallback = static_watchlist(watchlist_size)
    if not fallback:
        return DailyWatchlist(symbols=[], source="empty")

    # 1. Weekend-review locked universe
    approved = _load_approved_symbols()
    if approved:
        return DailyWatchlist(symbols=approved[:watchlist_size], source="approved_weekly")

    # 2. Live fundamentals ranking
    try:
        selected, ranked = select_fundamental_watchlist(len(fallback))
        if selected:
            watchlist = DailyWatchlist(
                symbols=selected,
                ranked_picks=ranked,
                source="fundamental",
            )
            logger.info(f"Fundamental watchlist selected: {watchlist.detail_strings()}")
            return watchlist

        logger.warning("Fundamental selector returned no symbols; using static fallback.")
    except Exception as exc:
        logger.warning(f"Fundamental watchlist selection failed: {exc}; using static fallback.")

    return DailyWatchlist(symbols=fallback, source="static_fallback")


def get_fundamental_judgment(symbol: str) -> "FundamentalJudgment | None":
    """
    Return a cached FundamentalJudgment for signal sizing, or None on data errors.

    The RiskManager remains the final gate. This helper only supplies context so
    quantity can be reduced when fundamentals are mixed or weak.
    """
    try:
        from analysis.fundamental_analyst import analyst
        from data.fundamentals import fundamentals_cache

        metrics = fundamentals_cache.get_fundamentals(symbol)
        if not metrics:
            return None
        return analyst.analyze(symbol, metrics)
    except Exception as exc:
        logger.debug(f"Fundamental judgment unavailable for {symbol}: {exc}")
        return None
