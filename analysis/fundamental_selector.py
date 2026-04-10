"""
Fundamental stock selector for the bot watchlist.

The scheduler used to scan the first N symbols in data/instruments.py. That is
simple, but it ignores whether today's candidates have a supportive fundamental
backdrop. This module ranks the NIFTY50 universe with the existing
score_fundamentals() engine and returns the symbols the bot should scan today.

Design goals:
  - Fail open: missing Yahoo data should not stop paper trading.
  - Avoid binary event risk: prefer stocks outside earnings blackout windows.
  - Diversify sectors: do not fill the watchlist with only banks or IT stocks.
  - Preserve the old static order as a tie-breaker so behaviour is deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from loguru import logger

from analysis.fundamental_filter import FundamentalScore, score_fundamentals
from data.fundamentals import fundamentals_cache
from data.instruments import NIFTY50_INSTRUMENTS, SYMBOL_TO_SECTOR


DEFAULT_MIN_SCORE = 3
DEFAULT_MAX_PER_SECTOR = 3


@dataclass(frozen=True)
class FundamentalPick:
    """Ranked fundamental candidate for the trading watchlist."""

    symbol: str
    sector: str
    score: int
    label: str
    earnings_blackout: bool
    rank_score: float
    reason: str
    source_order: int

    @property
    def eligible(self) -> bool:
        """True when the selector can prefer this stock for today's watchlist."""
        return not self.earnings_blackout


def _normalise_symbols(symbols: Sequence[str] | None) -> list[str]:
    """Return unique Kite symbols in input order."""
    raw = list(symbols) if symbols is not None else [i.kite_symbol for i in NIFTY50_INSTRUMENTS]
    seen: set[str] = set()
    result: list[str] = []
    for sym in raw:
        clean = str(sym).strip().upper()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _safe_score(symbol: str) -> FundamentalScore:
    """
    Score one stock, returning a neutral score on any error.

    This keeps the selector fail-open. If yfinance is down, the bot falls back
    toward the old static NIFTY50 order instead of stopping the trading day.
    """
    try:
        return score_fundamentals(symbol)
    except Exception as exc:
        logger.warning(f"FundamentalSelector: scoring failed for {symbol}: {exc}")
        return FundamentalScore(
            score=2,
            checks={},
            sector=SYMBOL_TO_SECTOR.get(symbol, "Unknown"),
            symbol=symbol,
        )


def _safe_blackout(symbol: str) -> bool:
    """Return earnings blackout status; fail open if the data source errors."""
    try:
        return bool(fundamentals_cache.is_earnings_blackout(symbol))
    except Exception as exc:
        logger.debug(f"FundamentalSelector: blackout check failed for {symbol}: {exc}")
        return False


def rank_fundamental_universe(symbols: Sequence[str] | None = None) -> list[FundamentalPick]:
    """
    Rank symbols from strongest to weakest fundamental backdrop.

    Sorting priority:
      1. Non-blackout stocks first.
      2. Higher sector-relative fundamental score first.
      3. Original NIFTY50 order as deterministic tie-breaker.
    """
    picks: list[FundamentalPick] = []
    for idx, symbol in enumerate(_normalise_symbols(symbols)):
        fs = _safe_score(symbol)
        blackout = _safe_blackout(symbol)
        rank_score = float(fs.score)
        if blackout:
            rank_score -= 10.0

        reason = f"{fs.score}/5 {fs.label} fundamentals"
        if blackout:
            reason += "; earnings blackout"

        picks.append(
            FundamentalPick(
                symbol=symbol,
                sector=fs.sector or SYMBOL_TO_SECTOR.get(symbol, "Unknown"),
                score=fs.score,
                label=fs.label,
                earnings_blackout=blackout,
                rank_score=rank_score,
                reason=reason,
                source_order=idx,
            )
        )

    return sorted(picks, key=lambda p: (p.earnings_blackout, -p.rank_score, p.source_order))


def _append_with_sector_cap(
    selected: list[FundamentalPick],
    candidates: list[FundamentalPick],
    target: int,
    sector_counts: dict[str, int],
    max_per_sector: int | None,
) -> None:
    """Append candidates while respecting optional sector concentration cap."""
    selected_symbols = {p.symbol for p in selected}
    for pick in candidates:
        if len(selected) >= target:
            return
        if pick.symbol in selected_symbols:
            continue
        if max_per_sector is not None and sector_counts.get(pick.sector, 0) >= max_per_sector:
            continue
        selected.append(pick)
        selected_symbols.add(pick.symbol)
        sector_counts[pick.sector] = sector_counts.get(pick.sector, 0) + 1


def select_fundamental_watchlist(
    count: int,
    symbols: Sequence[str] | None = None,
    min_score: int = DEFAULT_MIN_SCORE,
    max_per_sector: int | None = DEFAULT_MAX_PER_SECTOR,
) -> tuple[list[str], list[FundamentalPick]]:
    """
    Select the bot's watchlist from fundamental rankings.

    Args:
        count:          Number of symbols to return.
        symbols:        Optional universe. Defaults to all NIFTY50 symbols.
        min_score:      Preferred minimum FundamentalScore out of 5.
        max_per_sector: Preferred sector concentration cap. Set None to disable.

    Returns:
        (selected_symbols, ranked_picks)

    Fallback behaviour:
      - If too few stocks pass min_score, lower-scoring non-blackout stocks fill
        the remainder.
      - If sector caps leave too few names, the cap is relaxed.
      - If every stock is in blackout, the selector returns the top ranked names
        anyway; RiskManager still performs the final blackout gate before entry.
    """
    ranked = rank_fundamental_universe(symbols)
    if count <= 0 or not ranked:
        return [], ranked

    target = min(count, len(ranked))
    eligible = [p for p in ranked if p.eligible]
    pool = eligible if eligible else ranked

    selected: list[FundamentalPick] = []
    sector_counts: dict[str, int] = {}

    preferred = [p for p in pool if p.score >= min_score]
    fallback = [p for p in pool if p.score < min_score]

    _append_with_sector_cap(selected, preferred, target, sector_counts, max_per_sector)
    _append_with_sector_cap(selected, fallback, target, sector_counts, max_per_sector)

    if len(selected) < target:
        _append_with_sector_cap(selected, pool, target, sector_counts, None)

    selected_symbols = [p.symbol for p in selected]
    logger.info(
        "FundamentalSelector selected watchlist | "
        + ", ".join(f"{p.symbol}:{p.score}/5" for p in selected)
    )
    return selected_symbols, ranked
