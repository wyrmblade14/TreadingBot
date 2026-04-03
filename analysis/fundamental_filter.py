"""
Fundamental Filter — sector-relative fundamental scoring for NIFTY50 stocks.

Why sector-relative scoring (not absolute thresholds)?
  Different sectors operate at very different valuation levels:
    - IT companies (TCS, Infosys) normally trade at P/E 30–40 because investors
      expect high growth.
    - PSU banks (SBI) normally trade at P/E 8–12 because they grow more slowly
      and carry more risk.
  If you set a fixed rule like "P/E < 20", you'd exclude every IT stock
  even when they're actually cheap relative to other IT stocks.

  Sector-relative scoring solves this: instead of asking "is TCS's P/E below 20?",
  we ask "is TCS's P/E below the average P/E of all IT stocks in NIFTY50?".
  That question is always fair.

The 5 checks (each worth 1 point):

  1. P/E vs sector       — Stock P/E is below its sector median P/E.
                           A lower P/E relative to peers means you're paying less
                           per rupee of earnings — fundamentally cheaper.

  2. Debt vs sector      — Stock debt-to-equity is below its sector median.
                           High debt amplifies both gains and losses. Stocks with
                           less debt than peers are more resilient in downturns.

  3. Profit margin vs sector — Stock profit margin is above its sector median.
                           Margin = how many rupees the company keeps per rupee
                           of revenue. Higher than peers → better operating quality.

  4. Price/Book vs sector — Stock Price-to-Book is below its sector median.
                           Price-to-Book compares market price to the book value
                           (assets minus liabilities). Below sector median = cheaper
                           on an asset basis.

  5. Earnings trend       — EPS (Earnings Per Share) has been improving over the
                           last 4 quarters. Even in a short-term trade, buying a
                           stock whose earnings are growing is the safer side of
                           the trade.

Score interpretation:
  5/5 → High — fundamentally well-positioned vs peers; earnings growing.
  4/5 → High — strong relative fundamentals with one gap.
  3/5 → Moderate — about in line with its sector.
  2/5 or below → Low — relatively expensive or deteriorating vs peers.

Fallback behaviour:
  - If data is unavailable for a specific check → score that check as True (neutral).
    We never penalise a stock just because Yahoo Finance had a bad day.
  - If get_fundamentals() returns {} → return neutral score=2 with all checks marked
    False and labelled "No data available".
  - Any unhandled exception → return neutral score=2 (fail-open, never block trading).
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from data.fundamentals import fundamentals_cache
from data.instruments import SYMBOL_TO_SECTOR, get_symbols_by_sector


# ── Check names (used as dict keys and display labels) ────────────────

CHECK_PE     = "P/E vs sector"
CHECK_DEBT   = "Debt vs sector"
CHECK_MARGIN = "Profit margin vs sector"
CHECK_BOOK   = "Price/Book vs sector"
CHECK_TREND  = "Earnings trend"

ALL_CHECKS = [CHECK_PE, CHECK_DEBT, CHECK_MARGIN, CHECK_BOOK, CHECK_TREND]

# ── Metric keys in the fundamentals_cache dict ────────────────────────
# These match the _FUNDAMENTAL_KEYS fetched from yfinance in data/fundamentals.py

_KEY_PE     = "trailingPE"
_KEY_DEBT   = "debtToEquity"
_KEY_MARGIN = "profitMargins"
_KEY_BOOK   = "priceToBook"


# ── Output dataclass ──────────────────────────────────────────────────

@dataclass
class FundamentalScore:
    """
    The result of scoring a stock's fundamentals against its sector peers.

    Fields:
        score:   Total points out of 5.
        checks:  Dict mapping each check name → (passed: bool, label: str).
                 The label is a short human-readable explanation.
        sector:  The sector this stock was compared against (e.g. "Information Technology").
        symbol:  The Kite-format symbol that was scored (e.g. "INFY").
    """
    score:   int
    checks:  dict[str, tuple[bool, str]]
    sector:  str
    symbol:  str

    @property
    def max_score(self) -> int:
        return 5

    @property
    def colour(self) -> str:
        """
        CSS colour for a score badge — matches analysis/signal_scorer.py ScoreResult.colour
        so both scores can be displayed consistently in the dashboard.
        """
        if self.score >= 4:
            return "#4caf50"    # green
        if self.score >= 3:
            return "#ffc107"    # amber
        return "#ef5350"        # red

    @property
    def label(self) -> str:
        """Short text label for the score tier."""
        if self.score >= 4:
            return "High"
        if self.score >= 3:
            return "Moderate"
        return "Low"

    def dot_string(self) -> str:
        """
        Visual dot representation, e.g. '●●●○○' for score 3.
        Filled dots = passed checks. Empty = failed.
        """
        return "●" * self.score + "○" * (self.max_score - self.score)


# ── Neutral fallback builder ──────────────────────────────────────────

def _neutral_score(symbol: str, sector: str, reason: str) -> FundamentalScore:
    """
    Return a neutral FundamentalScore(2) with all checks marked False
    and the given reason as their label. Used when data is completely absent.
    """
    checks = {k: (False, reason) for k in ALL_CHECKS}
    return FundamentalScore(score=2, checks=checks, sector=sector, symbol=symbol)


# ── Sector median helper ──────────────────────────────────────────────

def _sector_median(sector: str, metric_key: str) -> float | None:
    """
    Return the median value of *metric_key* across all stocks in *sector*.

    Collects the raw metric from fundamentals_cache for every peer directly —
    never calls score_fundamentals() on peers to avoid infinite recursion.

    Missing or non-positive values are excluded.
    Returns None if fewer than 2 peers have valid data (insufficient to form
    a meaningful sector benchmark).

    Why use sorted()[len//2] instead of statistics.median()?
      It avoids an extra import and is equivalent for our small lists
      (8 stocks per sector at most). For even-length lists it returns the
      lower-middle value — a minor conservative bias that is acceptable here.
    """
    peers = get_symbols_by_sector(sector)
    values: list[float] = []
    for sym in peers:
        data = fundamentals_cache.get_fundamentals(sym)
        v = data.get(metric_key)
        if v is not None and v > 0:
            values.append(float(v))
    if len(values) < 2:
        return None
    return float(sorted(values)[len(values) // 2])  # simple median (lower-middle)


# ── Individual checks ─────────────────────────────────────────────────

def _check_pe(
    stock_val: float | None,
    sector: str,
) -> tuple[bool, str]:
    """
    Stock's trailing P/E is below the sector median.

    What P/E means:
      If a stock has P/E = 20, you're paying ₹20 for every ₹1 of annual earnings.
      Below sector median → relatively cheap; investors are paying less than usual
      for this sector's earnings stream.
    """
    if stock_val is None:
        return True, "P/E unavailable — skipped (neutral)"

    median = _sector_median(sector, _KEY_PE)
    if median is None:
        return True, "Insufficient sector P/E data — skipped (neutral)"

    passed = stock_val < median
    rel    = "below" if passed else "above"
    return (
        passed,
        f"P/E {stock_val:.1f} is {rel} sector median {median:.1f} "
        f"({'cheaper than peers ✓' if passed else 'pricier than peers ✗'})",
    )


def _check_debt(
    stock_val: float | None,
    sector: str,
) -> tuple[bool, str]:
    """
    Stock's debt-to-equity is below the sector median.

    What D/E means:
      Debt-to-Equity of 0.5 = for every ₹100 of shareholder equity, the company
      owes ₹50. Lower than peers → less leveraged, more conservative balance sheet.
    """
    if stock_val is None:
        return True, "Debt/Equity unavailable — skipped (neutral)"

    median = _sector_median(sector, _KEY_DEBT)
    if median is None:
        return True, "Insufficient sector Debt/Equity data — skipped (neutral)"

    passed = stock_val < median
    rel    = "below" if passed else "above"
    return (
        passed,
        f"D/E {stock_val:.2f} is {rel} sector median {median:.2f} "
        f"({'less debt than peers ✓' if passed else 'more debt than peers ✗'})",
    )


def _check_margin(
    stock_val: float | None,
    sector: str,
) -> tuple[bool, str]:
    """
    Stock's profit margin is above the sector median.

    What profit margin means:
      If margin = 0.15, the company keeps ₹15 of every ₹100 of revenue as profit.
      Above sector median → operationally more efficient than peers.
    """
    if stock_val is None:
        return True, "Profit margin unavailable — skipped (neutral)"

    median = _sector_median(sector, _KEY_MARGIN)
    if median is None:
        return True, "Insufficient sector margin data — skipped (neutral)"

    # yfinance returns profitMargins as a decimal (0.15 = 15%)
    passed    = stock_val > median
    rel       = "above" if passed else "below"
    pct_stock = stock_val * 100
    pct_med   = median * 100
    return (
        passed,
        f"Margin {pct_stock:.1f}% is {rel} sector median {pct_med:.1f}% "
        f"({'better quality than peers ✓' if passed else 'lower margin than peers ✗'})",
    )


def _check_book(
    stock_val: float | None,
    sector: str,
) -> tuple[bool, str]:
    """
    Stock's Price-to-Book is below the sector median.

    What P/B means:
      Price-to-Book of 2.0 means you pay ₹2 for every ₹1 of net asset value.
      Below sector median → buying assets at a relative discount to peers.
    """
    if stock_val is None:
        return True, "Price/Book unavailable — skipped (neutral)"

    median = _sector_median(sector, _KEY_BOOK)
    if median is None:
        return True, "Insufficient sector Price/Book data — skipped (neutral)"

    passed = stock_val < median
    rel    = "below" if passed else "above"
    return (
        passed,
        f"P/B {stock_val:.2f} is {rel} sector median {median:.2f} "
        f"({'cheaper on book value ✓' if passed else 'pricier on book value ✗'})",
    )


def _check_earnings_trend(symbol: str) -> tuple[bool, str]:
    """
    EPS has been IMPROVING over the last 4 quarters.

    EPS = Earnings Per Share = net profit / total shares outstanding.
    Three consecutive positive quarter-over-quarter changes → IMPROVING.
    """
    trend = fundamentals_cache.get_quarterly_earnings_trend(symbol)
    passed = (trend == "IMPROVING")
    label_map = {
        "IMPROVING":    "EPS improving over last 4 quarters ✓",
        "STABLE":       "EPS broadly stable — no clear trend (neutral ✗)",
        "DETERIORATING": "EPS deteriorating over last 4 quarters ✗",
    }
    return passed, label_map.get(trend, f"EPS trend: {trend}")


# ── Main public function ──────────────────────────────────────────────

def score_fundamentals(symbol: str) -> FundamentalScore:
    """
    Score a NIFTY50 stock's fundamentals relative to its sector peers.

    Each of the 5 checks contributes 1 point (0–5 scale):
      1. P/E below sector median
      2. Debt/Equity below sector median
      3. Profit margin above sector median
      4. Price/Book below sector median
      5. EPS trend is IMPROVING

    For checks 1–4, missing data is skipped (scored True, neutral).
    For check 5, STABLE/DETERIORATING → False; IMPROVING → True.

    Args:
        symbol: Kite-format symbol, e.g. "RELIANCE" or "INFY".

    Returns:
        FundamentalScore with:
            .score   — integer 0–5
            .checks  — {check_name: (passed, explanation_string)}
            .sector  — sector name used for comparison
            .symbol  — the input symbol
            .label   — "High" / "Moderate" / "Low"
            .colour  — CSS hex colour matching signal_scorer.py colour scheme
            .dot_string() — e.g. "●●●○○"

    Falls back to score=2 (neutral) on any data error so trading is never
    blocked due to a Yahoo Finance outage.
    """
    # ── Resolve sector ────────────────────────────────────────────────
    sector = SYMBOL_TO_SECTOR.get(symbol, "Unknown")

    try:
        # ── Fetch fundamentals for this stock ─────────────────────────
        fund = fundamentals_cache.get_fundamentals(symbol)

        if not fund:
            # Empty dict means yfinance returned nothing — go neutral
            logger.warning(
                f"FundamentalFilter: no fundamentals data for {symbol}; "
                f"returning neutral score=2"
            )
            return _neutral_score(symbol, sector, "No data available")

        # Extract the four metric values (may be None if yfinance didn't return them)
        pe_val     = fund.get(_KEY_PE)
        debt_val   = fund.get(_KEY_DEBT)
        margin_val = fund.get(_KEY_MARGIN)
        book_val   = fund.get(_KEY_BOOK)

        # ── Run the 5 checks ──────────────────────────────────────────
        checks: dict[str, tuple[bool, str]] = {}

        # Check 1 — P/E vs sector
        passed, detail = _check_pe(pe_val, sector)
        checks[CHECK_PE] = (passed, detail)

        # Check 2 — Debt/Equity vs sector
        passed, detail = _check_debt(debt_val, sector)
        checks[CHECK_DEBT] = (passed, detail)

        # Check 3 — Profit margin vs sector
        passed, detail = _check_margin(margin_val, sector)
        checks[CHECK_MARGIN] = (passed, detail)

        # Check 4 — Price/Book vs sector
        passed, detail = _check_book(book_val, sector)
        checks[CHECK_BOOK] = (passed, detail)

        # Check 5 — Quarterly earnings trend
        passed, detail = _check_earnings_trend(symbol)
        checks[CHECK_TREND] = (passed, detail)

        # ── Total ─────────────────────────────────────────────────────
        total = sum(1 for p, _ in checks.values() if p)
        result = FundamentalScore(score=total, checks=checks, sector=sector, symbol=symbol)

        logger.debug(
            f"FundamentalFilter: {symbol} ({sector}) → {total}/5 "
            f"[PE={pe_val}, D/E={debt_val}, margin={margin_val}, P/B={book_val}, "
            f"trend={fundamentals_cache.get_quarterly_earnings_trend(symbol)}]"
        )
        return result

    except Exception as exc:
        logger.warning(
            f"FundamentalFilter: unexpected error scoring {symbol}: {exc}; "
            f"returning neutral score=2"
        )
        return _neutral_score(symbol, sector, f"Scoring error — {exc}")
