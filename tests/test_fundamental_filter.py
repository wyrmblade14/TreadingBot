"""
Tests for analysis/fundamental_filter.py — score_fundamentals().

Covers:
  - Score range (0–5)
  - Neutral fallback when fundamentals data is empty
  - P/E check: passes when below sector median, fails when above
  - Earnings trend check: passes when IMPROVING
  - Neutral/skipped check when no peer data is available
  - Exception safety: returns score=2 on error
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from analysis.fundamental_filter import (
    CHECK_PE,
    CHECK_TREND,
    FundamentalScore,
    score_fundamentals,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_fc_mock(
    stock_symbol: str,
    stock_data: dict,
    peer_data: dict,
    trend: str = "STABLE",
) -> MagicMock:
    """
    Build a mock fundamentals_cache where:
      - stock_symbol returns stock_data
      - all other symbols return peer_data
    The mock also has get_quarterly_earnings_trend pre-set to *trend*.
    """
    mock_fc = MagicMock()

    def _get_fundamentals(symbol):
        if symbol == stock_symbol:
            return stock_data
        return peer_data

    mock_fc.get_fundamentals.side_effect = _get_fundamentals
    mock_fc.get_quarterly_earnings_trend.return_value = trend
    return mock_fc


# ── TestScoreFundamentals ────────────────────────────────────────────────────

class TestScoreFundamentals:

    def test_score_range_is_0_to_5(self):
        """score_fundamentals() always returns a FundamentalScore with score in [0, 5]."""
        stock_data = {
            "trailingPE": 20.0,
            "debtToEquity": 30.0,
            "profitMargins": 0.20,
            "priceToBook": 3.0,
        }
        peer_data = {
            "trailingPE": 35.0,
            "debtToEquity": 50.0,
            "profitMargins": 0.10,
            "priceToBook": 5.0,
        }
        mock_fc = _make_fc_mock("INFY", stock_data, peer_data, trend="IMPROVING")

        with patch("analysis.fundamental_filter.fundamentals_cache", mock_fc):
            result = score_fundamentals("INFY")

        assert isinstance(result, FundamentalScore)
        assert 0 <= result.score <= 5

    def test_returns_neutral_on_empty_fundamentals(self):
        """When get_fundamentals returns {}, score_fundamentals returns score=2 (neutral)."""
        mock_fc = MagicMock()
        mock_fc.get_fundamentals.return_value = {}
        mock_fc.get_quarterly_earnings_trend.return_value = "STABLE"

        with patch("analysis.fundamental_filter.fundamentals_cache", mock_fc):
            result = score_fundamentals("RELIANCE")

        assert result.score == 2

    def test_pe_check_passes_when_below_sector_median(self):
        """Stock P/E (20) below sector median (~35) → P/E check is True."""
        stock_data = {"trailingPE": 20.0, "debtToEquity": 40.0, "profitMargins": 0.15, "priceToBook": 4.0}
        peer_data  = {"trailingPE": 35.0, "debtToEquity": 40.0, "profitMargins": 0.15, "priceToBook": 4.0}
        mock_fc = _make_fc_mock("INFY", stock_data, peer_data, trend="STABLE")

        with patch("analysis.fundamental_filter.fundamentals_cache", mock_fc):
            result = score_fundamentals("INFY")

        passed, _label = result.checks[CHECK_PE]
        assert passed is True

    def test_pe_check_fails_when_above_sector_median(self):
        """Stock P/E (60) above sector median (~20) → P/E check is False."""
        stock_data = {"trailingPE": 60.0, "debtToEquity": 40.0, "profitMargins": 0.15, "priceToBook": 4.0}
        peer_data  = {"trailingPE": 20.0, "debtToEquity": 40.0, "profitMargins": 0.15, "priceToBook": 4.0}
        mock_fc = _make_fc_mock("INFY", stock_data, peer_data, trend="STABLE")

        with patch("analysis.fundamental_filter.fundamentals_cache", mock_fc):
            result = score_fundamentals("INFY")

        passed, _label = result.checks[CHECK_PE]
        assert passed is False

    def test_earnings_trend_check_passes_when_improving(self):
        """IMPROVING trend → earnings trend check is True."""
        stock_data = {"trailingPE": 25.0, "debtToEquity": 30.0, "profitMargins": 0.18, "priceToBook": 4.5}
        peer_data  = {"trailingPE": 30.0, "debtToEquity": 35.0, "profitMargins": 0.12, "priceToBook": 5.0}
        mock_fc = _make_fc_mock("TCS", stock_data, peer_data, trend="IMPROVING")

        with patch("analysis.fundamental_filter.fundamentals_cache", mock_fc):
            result = score_fundamentals("TCS")

        passed, _label = result.checks[CHECK_TREND]
        assert passed is True

    def test_check_skipped_when_no_peer_data(self):
        """When all peers return {} (no data), sector median is None → check is skipped (True, neutral)."""
        stock_data = {"trailingPE": 25.0, "debtToEquity": 30.0, "profitMargins": 0.18, "priceToBook": 4.0}

        mock_fc = MagicMock()

        def _get_fundamentals(symbol):
            if symbol == "INFY":
                return stock_data
            return {}  # all peers return empty data

        mock_fc.get_fundamentals.side_effect = _get_fundamentals
        mock_fc.get_quarterly_earnings_trend.return_value = "STABLE"

        with patch("analysis.fundamental_filter.fundamentals_cache", mock_fc):
            result = score_fundamentals("INFY")

        # When sector median cannot be computed (< 2 valid peers), check is skipped → True
        passed_pe, label_pe = result.checks[CHECK_PE]
        assert passed_pe is True
        assert "skipped" in label_pe.lower() or "insufficient" in label_pe.lower() or "unavailable" in label_pe.lower()

    def test_returns_score_2_on_exception(self):
        """If an unhandled exception occurs inside score_fundamentals, it returns score=2 (neutral)."""
        mock_fc = MagicMock()
        mock_fc.get_fundamentals.side_effect = RuntimeError("unexpected failure")

        with patch("analysis.fundamental_filter.fundamentals_cache", mock_fc):
            result = score_fundamentals("WIPRO")

        assert result.score == 2
