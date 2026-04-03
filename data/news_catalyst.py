"""
News & Corporate Announcement Catalyst — per-symbol event classification.

What is a "catalyst"?
  A catalyst is a corporate event or news story that can move a stock's
  price significantly on a given day. Examples:
    - Dividend declared  → usually BULLISH  (investors get paid)
    - NCLT/insolvency    → usually BEARISH  (company in legal trouble)
    - Buyback announced  → usually BULLISH  (company buying its own shares)
    - Quarterly results  → depends on whether profit grew or fell

Why use this for intraday trading?
  Even a strong technical setup can fail if the stock is weighed down by
  bad news from the previous evening. Checking last-day announcements at
  9:00 AM pre-market lets the bot:
    1. Avoid entering SELLS on stocks with BULLISH catalysts (going against
       potential gap-up momentum)
    2. Avoid entering BUYS on stocks with BEARISH catalysts (fighting
       downward institutional selling)

Data sources (in priority order):
  1. NSE Corporate Announcements API — official, authoritative, covers
     dividends, board meetings, buybacks, pledges, NCLT orders, etc.
  2. yfinance ticker.news — fallback; recent headlines from Yahoo Finance,
     useful when NSE API is slow or returns nothing for a symbol.

Caching: 1-hour TTL per symbol (same pattern as india_vix.py).
Fail-open: any network error returns NEUTRAL — never block trading on
bad data availability.

Usage:
    from data.news_catalyst import news_catalyst_cache

    result = news_catalyst_cache.get_catalyst("RELIANCE")
    print(result.direction, result.confidence, result.reason)
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal

import requests
import yfinance as yf
from loguru import logger

from data.instruments import KITE_TO_YF

# ── Cache TTL ─────────────────────────────────────────────────────────
_CACHE_TTL = 3600   # 1 hour — re-fetch once per session

# ── Module-level TTL cache: symbol → (CatalystResult, monotonic_ts) ──
_catalyst_cache: dict[str, tuple["CatalystResult", float]] = {}

# ── NSE API constants ─────────────────────────────────────────────────
_NSE_ANNOUNCE_URL = (
    "https://www.nseindia.com/api/corp-info"
    "?symbol={symbol}&corpType=announcement&market=equities"
)
_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com",
}
_NSE_TIMEOUT = 6   # seconds

# ── Classification rule table ─────────────────────────────────────────
# Each entry: (keywords_to_match, direction, confidence, human_reason)
# Matched against lowercase(subject + " " + category).
# Order matters — first match wins.
_RULES: list[tuple[list[str], str, float, str]] = [
    # ── Hard bad news ─────────────────────────────────────────────────
    (["nclt", "insolvency", "winding up", "default on payment"],
     "BEARISH_CATALYST", 0.9, "Insolvency / NCLT proceedings"),
    (["sebi order", "sebi penalty", "ban on", "suspension"],
     "BEARISH_CATALYST", 0.85, "Regulatory action (SEBI)"),
    (["fraud", "forensic audit", "whistleblower"],
     "BEARISH_CATALYST", 0.9, "Fraud / forensic investigation"),
    # ── Shareholder-friendly actions ──────────────────────────────────
    (["buyback", "buy-back", "share repurchase"],
     "BULLISH_CATALYST", 0.85, "Buyback / share repurchase"),
    (["interim dividend", "final dividend", "special dividend", "dividend declared"],
     "BULLISH_CATALYST", 0.80, "Dividend declared"),
    (["bonus shares", "bonus issue", "stock split"],
     "BULLISH_CATALYST", 0.75, "Bonus / split announcement"),
    # ── M&A / strategic ───────────────────────────────────────────────
    (["acquisition", "acquires", "merger", "strategic investment"],
     "BULLISH_CATALYST", 0.65, "Acquisition / merger"),
    (["block deal", "bulk deal", "promoter selling", "promoter sell"],
     "BEARISH_CATALYST", 0.70, "Large block/bulk deal sale"),
    (["promoter pledge", "pledge of shares", "pledging"],
     "BEARISH_CATALYST", 0.75, "Promoter share pledge increase"),
    # ── Results ───────────────────────────────────────────────────────
    (["profit after tax", "pat increased", "revenue grew", "strong results",
      "record profit", "earnings beat"],
     "BULLISH_CATALYST", 0.70, "Strong quarterly results"),
    (["loss", "net loss", "revenue declined", "profit fell", "missed estimates",
      "earnings miss", "poor results"],
     "BEARISH_CATALYST", 0.75, "Weak quarterly results"),
    # ── Neutral board events ──────────────────────────────────────────
    (["board meeting", "results on", "financial results"],
     "NEUTRAL", 0.50, "Board meeting / upcoming results"),
    (["agm", "egm", "annual general meeting", "extraordinary general meeting"],
     "NEUTRAL", 0.30, "AGM / EGM notice"),
]


@dataclass
class CatalystResult:
    """Classification of a stock's event-driven catalyst for today."""
    symbol:    str
    direction: Literal["BULLISH_CATALYST", "BEARISH_CATALYST", "NEUTRAL"]
    confidence: float       # 0.0–1.0
    reason:    str          # e.g. "Dividend declared"
    source:    str          # "nse_announcement" | "news_headline" | "none"
    fetched_at: datetime = field(default_factory=datetime.now)


class NewsCatalystFetcher:
    """
    Fetches and classifies corporate events + news for NIFTY50 stocks.

    All methods accept Kite-format symbols (e.g. "RELIANCE") and translate
    internally to the correct NSE/yfinance format.

    Caching is module-level (shared across all instances) with a 1-hour TTL.
    """

    # ── Public API ────────────────────────────────────────────────────

    def get_catalyst(self, symbol: str) -> CatalystResult:
        """
        Return a CatalystResult for *symbol*.

        Checks the cache first. On cache miss:
          1. Tries NSE Corporate Announcements API for yesterday's events.
          2. Falls back to yfinance news headlines.
          3. Returns NEUTRAL on any error (fail-open).
        """
        now = _time.monotonic()

        # Cache hit
        if symbol in _catalyst_cache:
            result, ts = _catalyst_cache[symbol]
            if now - ts < _CACHE_TTL:
                logger.debug(f"Catalyst cache hit: {symbol} → {result.direction}")
                return result

        # Cache miss — try NSE first, then yfinance, then neutral
        result = None

        # 1. NSE announcements
        try:
            result = self._fetch_nse_announcement(symbol)
        except Exception as exc:
            logger.debug(f"NSE announcement fetch error for {symbol}: {exc}")

        # 2. yfinance fallback
        if result is None or result.direction == "NEUTRAL":
            try:
                yf_result = self._fetch_yf_news(symbol)
                # Prefer a non-NEUTRAL result; otherwise keep existing
                if yf_result is not None and yf_result.direction != "NEUTRAL":
                    result = yf_result
                elif result is None:
                    result = yf_result
            except Exception as exc:
                logger.debug(f"yfinance news fetch error for {symbol}: {exc}")

        # 3. Fallback to NEUTRAL
        if result is None:
            result = CatalystResult(
                symbol=symbol,
                direction="NEUTRAL",
                confidence=0.0,
                reason="No announcements found",
                source="none",
            )

        _catalyst_cache[symbol] = (result, now)
        if result.direction != "NEUTRAL":
            logger.info(
                f"Catalyst [{symbol}]: {result.direction} "
                f"(conf={result.confidence:.2f}, source={result.source}) — {result.reason}"
            )
        else:
            logger.debug(f"Catalyst [{symbol}]: NEUTRAL (no event found)")

        return result

    # ── Private helpers ───────────────────────────────────────────────

    def _fetch_nse_announcement(self, symbol: str) -> CatalystResult | None:
        """
        Query NSE Corporate Info API for yesterday's and today's announcements.

        NSE returns a list of announcement dicts with keys:
          - "desc"     : subject / description of the announcement
          - "attchmnt" : attachment filename (sometimes has keyword hints)
          - "exchdisstime" : timestamp e.g. "02-Apr-2026 18:30:00"

        We look at announcements from yesterday onward.
        Returns None if no NSE data or no match — caller will try yfinance.
        """
        url = _NSE_ANNOUNCE_URL.format(symbol=symbol)
        try:
            resp = requests.get(url, headers=_NSE_HEADERS, timeout=_NSE_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.debug(f"NSE API request failed for {symbol}: {exc}")
            return None

        # NSE returns a dict with key "corpInfo" containing a list
        announcements = []
        if isinstance(data, dict):
            announcements = data.get("corpInfo", []) or []
        elif isinstance(data, list):
            announcements = data

        if not announcements:
            return None

        yesterday = date.today() - timedelta(days=1)

        for ann in announcements:
            subject = str(ann.get("desc", "") or "").strip()
            category = str(ann.get("attchmnt", "") or "").strip()
            dt_str = str(ann.get("exchdisstime", "") or "")

            # Parse date from "DD-Mon-YYYY HH:MM:SS"
            ann_date = _parse_nse_date(dt_str)
            if ann_date is not None and ann_date < yesterday:
                continue  # too old

            if not subject:
                continue

            direction, confidence, reason = self._classify_text(subject + " " + category)
            if direction != "NEUTRAL" or confidence > 0.0:
                return CatalystResult(
                    symbol=symbol,
                    direction=direction,  # type: ignore[arg-type]
                    confidence=confidence,
                    reason=reason,
                    source="nse_announcement",
                )

        return None

    def _fetch_yf_news(self, symbol: str) -> CatalystResult | None:
        """
        Fetch recent news headlines from yfinance and classify them.

        yfinance returns a list of dicts with at minimum:
          {"title": "...", "providerPublishTime": <unix_ts>}

        We filter to headlines from the last 24 hours.
        Returns None if no news found or no match.
        """
        yf_sym = KITE_TO_YF.get(symbol, symbol + ".NS")
        try:
            ticker = yf.Ticker(yf_sym)
            news = ticker.news or []
        except Exception as exc:
            logger.debug(f"yfinance Ticker() failed for {symbol}: {exc}")
            return None

        cutoff = _time.time() - 86400  # last 24 hours

        best: CatalystResult | None = None
        best_conf = 0.0

        for item in news:
            pub_time = item.get("providerPublishTime", 0) or 0
            if pub_time < cutoff:
                continue
            title = str(item.get("title", "") or "")
            if not title:
                continue

            direction, confidence, reason = self._classify_text(title)
            if confidence > best_conf:
                best_conf = confidence
                best = CatalystResult(
                    symbol=symbol,
                    direction=direction,  # type: ignore[arg-type]
                    confidence=confidence,
                    reason=reason,
                    source="news_headline",
                )

        return best

    def _classify_text(self, text: str) -> tuple[str, float, str]:
        """
        Classify a text string using the keyword rule table.

        Returns (direction, confidence, reason).
        Falls back to ("NEUTRAL", 0.0, "No matching keywords") if no rule matches.
        """
        lower = text.lower()
        for keywords, direction, confidence, reason in _RULES:
            if any(kw in lower for kw in keywords):
                return direction, confidence, reason
        return "NEUTRAL", 0.0, "No matching keywords"


# ── Module-level singleton ────────────────────────────────────────────
news_catalyst_cache = NewsCatalystFetcher()
"""
Module-level singleton. Import and use directly:

    from data.news_catalyst import news_catalyst_cache

    result = news_catalyst_cache.get_catalyst("RELIANCE")
    print(result.direction, result.confidence, result.reason)
"""


# ── Private date parser ───────────────────────────────────────────────

def _parse_nse_date(dt_str: str) -> date | None:
    """
    Parse an NSE timestamp string to a Python date.

    NSE format examples:
      "02-Apr-2026 18:30:00"
      "01-Apr-2026"
    """
    dt_str = dt_str.strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y"):
        try:
            return datetime.strptime(dt_str, fmt).date()
        except ValueError:
            pass
    # Try ISO format fallback
    try:
        return date.fromisoformat(dt_str[:10])
    except Exception:
        return None
