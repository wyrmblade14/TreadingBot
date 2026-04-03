"""
Unit tests for data/news_catalyst.py and analysis/catalyst_scanner.py.

Tests:
  - Rule-based classification for BULLISH / BEARISH / NEUTRAL keywords
  - NSE announcement fetch + classification
  - yfinance news fallback
  - Cache behaviour (one fetch per TTL)
  - Exception safety (fail-open → NEUTRAL)
  - CatalystSummary structure from scan_all_catalysts()
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from data.news_catalyst import (
    NewsCatalystFetcher,
    CatalystResult,
    _catalyst_cache,
)
from analysis.catalyst_scanner import (
    CatalystSummary,
    scan_all_catalysts,
    _safe_get_catalyst,
)


# ── Helpers ───────────────────────────────────────────────────────────

def _fresh_fetcher() -> NewsCatalystFetcher:
    """Return a NewsCatalystFetcher with the module-level cache cleared."""
    _catalyst_cache.clear()
    return NewsCatalystFetcher()


# ── Classification tests ──────────────────────────────────────────────

class TestClassifyText:

    def test_dividend_is_bullish(self):
        fc = _fresh_fetcher()
        direction, conf, reason = fc._classify_text("Interim Dividend declared for FY2026")
        assert direction == "BULLISH_CATALYST"
        assert conf >= 0.7
        assert "dividend" in reason.lower()

    def test_buyback_is_bullish(self):
        fc = _fresh_fetcher()
        direction, conf, reason = fc._classify_text("Board approves buyback of shares at ₹2,500")
        assert direction == "BULLISH_CATALYST"
        assert conf >= 0.8

    def test_nclt_is_bearish(self):
        fc = _fresh_fetcher()
        direction, conf, reason = fc._classify_text("NCLT order received against the company")
        assert direction == "BEARISH_CATALYST"
        assert conf >= 0.85

    def test_promoter_pledge_is_bearish(self):
        fc = _fresh_fetcher()
        direction, conf, reason = fc._classify_text("Pledging of shares by promoter group")
        assert direction == "BEARISH_CATALYST"
        assert conf >= 0.7

    def test_agm_is_neutral(self):
        fc = _fresh_fetcher()
        direction, conf, reason = fc._classify_text("Notice of Annual General Meeting (AGM)")
        assert direction == "NEUTRAL"

    def test_unknown_text_is_neutral(self):
        fc = _fresh_fetcher()
        direction, conf, reason = fc._classify_text("Appointment of independent director")
        assert direction == "NEUTRAL"
        assert conf == 0.0

    def test_strong_results_headline_is_bullish(self):
        fc = _fresh_fetcher()
        direction, conf, _ = fc._classify_text("Company reports record profit in Q3 FY26")
        assert direction == "BULLISH_CATALYST"

    def test_loss_headline_is_bearish(self):
        fc = _fresh_fetcher()
        direction, conf, _ = fc._classify_text("Net loss widens as revenue declined sharply")
        assert direction == "BEARISH_CATALYST"


# ── NSE announcement fetch tests ──────────────────────────────────────

class TestFetchNSEAnnouncement:

    def test_dividend_announcement_from_nse(self):
        """NSE returns a dividend announcement from yesterday → BULLISH."""
        fc = _fresh_fetcher()
        yesterday = (date.today() - timedelta(days=1)).strftime("%d-%b-%Y 10:00:00")
        mock_data = {
            "corpInfo": [
                {"desc": "Interim Dividend declared", "attchmnt": "", "exchdisstime": yesterday}
            ]
        }
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = mock_data
            mock_get.return_value = mock_resp

            result = fc._fetch_nse_announcement("RELIANCE")

        assert result is not None
        assert result.direction == "BULLISH_CATALYST"
        assert result.source == "nse_announcement"

    def test_old_announcement_ignored(self):
        """NSE returns an announcement from 5 days ago → filtered out → None."""
        fc = _fresh_fetcher()
        old_date = (date.today() - timedelta(days=5)).strftime("%d-%b-%Y 10:00:00")
        mock_data = {
            "corpInfo": [
                {"desc": "Dividend declared", "attchmnt": "", "exchdisstime": old_date}
            ]
        }
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = mock_data
            mock_get.return_value = mock_resp

            result = fc._fetch_nse_announcement("INFY")

        assert result is None

    def test_nse_request_failure_returns_none(self):
        """Network error on NSE API → returns None (not an exception)."""
        fc = _fresh_fetcher()
        with patch("requests.get", side_effect=ConnectionError("timeout")):
            result = fc._fetch_nse_announcement("TCS")
        assert result is None

    def test_empty_corp_info_returns_none(self):
        """NSE returns empty corpInfo list → None."""
        fc = _fresh_fetcher()
        mock_data = {"corpInfo": []}
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = mock_data
            mock_get.return_value = mock_resp

            result = fc._fetch_nse_announcement("WIPRO")

        assert result is None


# ── yfinance news tests ───────────────────────────────────────────────

class TestFetchYFNews:

    def test_recent_bullish_headline(self):
        """yfinance returns a buyback headline from 6h ago → BULLISH."""
        fc = _fresh_fetcher()
        import time as _t
        recent_ts = int(_t.time()) - 6 * 3600
        mock_news = [{"title": "Company announces buyback at premium", "providerPublishTime": recent_ts}]

        with patch("yfinance.Ticker") as mock_yf:
            mock_ticker = MagicMock()
            mock_ticker.news = mock_news
            mock_yf.return_value = mock_ticker

            result = fc._fetch_yf_news("RELIANCE")

        assert result is not None
        assert result.direction == "BULLISH_CATALYST"
        assert result.source == "news_headline"

    def test_old_headline_ignored(self):
        """yfinance headline older than 24h → no result."""
        fc = _fresh_fetcher()
        import time as _t
        old_ts = int(_t.time()) - 30 * 3600  # 30 hours ago
        mock_news = [{"title": "Company posts record profit", "providerPublishTime": old_ts}]

        with patch("yfinance.Ticker") as mock_yf:
            mock_ticker = MagicMock()
            mock_ticker.news = mock_news
            mock_yf.return_value = mock_ticker

            result = fc._fetch_yf_news("RELIANCE")

        assert result is None

    def test_yf_exception_returns_none(self):
        """yfinance raises → returns None (fail-open)."""
        fc = _fresh_fetcher()
        with patch("yfinance.Ticker", side_effect=RuntimeError("rate limit")):
            result = fc._fetch_yf_news("HDFC")
        assert result is None


# ── Full get_catalyst() tests ─────────────────────────────────────────

class TestGetCatalyst:

    def test_fetch_failure_returns_neutral(self):
        """Both NSE and yfinance fail → NEUTRAL, no exception raised."""
        fc = _fresh_fetcher()
        with patch.object(fc, "_fetch_nse_announcement", return_value=None), \
             patch.object(fc, "_fetch_yf_news", return_value=None):
            result = fc.get_catalyst("WIPRO")

        assert result.direction == "NEUTRAL"
        assert result.source == "none"
        assert result.symbol == "WIPRO"

    def test_cache_hit_avoids_refetch(self):
        """Second call for same symbol hits cache, not NSE or yfinance."""
        fc = _fresh_fetcher()
        with patch.object(fc, "_fetch_nse_announcement") as mock_nse, \
             patch.object(fc, "_fetch_yf_news") as mock_yf:
            mock_nse.return_value = None
            mock_yf.return_value = None

            fc.get_catalyst("TCS")
            fc.get_catalyst("TCS")

        # Each should be called only once (second call uses cache)
        assert mock_nse.call_count == 1
        assert mock_yf.call_count == 1

    def test_nse_result_takes_priority_over_neutral_yf(self):
        """NSE returns NEUTRAL, yfinance returns BULLISH → BULLISH wins."""
        fc = _fresh_fetcher()
        nse_result = CatalystResult("SBIN", "NEUTRAL", 0.3, "Board meeting", "nse_announcement")
        yf_result  = CatalystResult("SBIN", "BULLISH_CATALYST", 0.8, "Dividend declared", "news_headline")

        with patch.object(fc, "_fetch_nse_announcement", return_value=nse_result), \
             patch.object(fc, "_fetch_yf_news", return_value=yf_result):
            result = fc.get_catalyst("SBIN")

        assert result.direction == "BULLISH_CATALYST"


# ── CatalystSummary / scan_all_catalysts tests ────────────────────────

class TestCatalystScanner:

    def test_scan_returns_summary_structure(self):
        """scan_all_catalysts returns a CatalystSummary with bullish/bearish/neutral lists."""
        bull = CatalystResult("RELIANCE", "BULLISH_CATALYST", 0.8, "Dividend", "nse_announcement")
        bear = CatalystResult("TCS",      "BEARISH_CATALYST", 0.9, "NCLT",     "nse_announcement")
        neut = CatalystResult("INFY",     "NEUTRAL",          0.0, "None",     "none")

        def mock_get_catalyst(symbol: str) -> CatalystResult:
            return {"RELIANCE": bull, "TCS": bear, "INFY": neut}.get(
                symbol,
                CatalystResult(symbol, "NEUTRAL", 0.0, "None", "none")
            )

        with patch("analysis.catalyst_scanner.news_catalyst_cache") as mock_cache:
            mock_cache.get_catalyst.side_effect = mock_get_catalyst
            summary = scan_all_catalysts(["RELIANCE", "TCS", "INFY"])

        assert isinstance(summary, CatalystSummary)
        assert len(summary.bullish) == 1
        assert len(summary.bearish) == 1
        assert summary.bullish[0].symbol == "RELIANCE"
        assert summary.bearish[0].symbol == "TCS"
        assert summary.total == 3

    def test_bullish_sorted_by_confidence(self):
        """Bullish results are sorted by confidence descending."""
        results = [
            CatalystResult("A", "BULLISH_CATALYST", 0.65, "Acquisition", "nse_announcement"),
            CatalystResult("B", "BULLISH_CATALYST", 0.85, "Buyback",     "nse_announcement"),
        ]

        def mock_get(symbol):
            return next((r for r in results if r.symbol == symbol), None) or \
                   CatalystResult(symbol, "NEUTRAL", 0.0, "", "none")

        with patch("analysis.catalyst_scanner.news_catalyst_cache") as mock_cache:
            mock_cache.get_catalyst.side_effect = mock_get
            summary = scan_all_catalysts(["A", "B"])

        # Higher confidence should come first
        assert summary.bullish[0].confidence >= summary.bullish[-1].confidence

    def test_safe_get_catalyst_swallows_exception(self):
        """_safe_get_catalyst returns None instead of raising."""
        with patch("analysis.catalyst_scanner.news_catalyst_cache") as mock_cache:
            mock_cache.get_catalyst.side_effect = RuntimeError("network down")
            result = _safe_get_catalyst("HDFCBANK")
        assert result is None
