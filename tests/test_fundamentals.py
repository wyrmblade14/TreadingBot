"""
Tests for data/fundamentals.py — FundamentalsCache.

Covers:
  - get_fundamentals(): fetch, cache, error handling
  - get_quarterly_earnings_trend(): trend classification
  - is_earnings_blackout(): blackout window logic
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data.fundamentals import FundamentalsCache, _fundamentals_cache, _trend_cache, _calendar_cache


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fresh_cache() -> FundamentalsCache:
    """Return a FundamentalsCache with all module-level caches cleared."""
    _fundamentals_cache.clear()
    _trend_cache.clear()
    _calendar_cache.clear()
    return FundamentalsCache()


def _make_eps_df(values: list[float], label: str = "Basic EPS") -> pd.DataFrame:
    """
    Build a minimal quarterly_income_stmt DataFrame with one EPS row.

    yfinance returns columns as Timestamps (most recent first).
    We use simple string column labels here — the production code only looks
    at index labels and uses iloc[:4], so column type doesn't matter for tests.
    """
    cols = [f"Q{i}" for i in range(len(values))]
    df = pd.DataFrame({col: [val] for col, val in zip(cols, values)}, index=[label])
    return df


# ── TestGetFundamentals ───────────────────────────────────────────────────────

class TestGetFundamentals:

    def test_returns_dict_with_expected_keys(self):
        """get_fundamentals returns a dict containing the standard fundamental keys."""
        fc = _fresh_cache()
        fake_info = {
            "trailingPE": 22.5,
            "debtToEquity": 35.0,
            "profitMargins": 0.18,
            "priceToBook": 4.1,
            "earningsQuarterlyGrowth": 0.12,
        }
        mock_ticker = MagicMock()
        mock_ticker.info = fake_info

        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = fc.get_fundamentals("RELIANCE")

        assert isinstance(result, dict)
        assert result["trailingPE"] == 22.5
        assert result["debtToEquity"] == 35.0
        assert result["profitMargins"] == 0.18

    def test_returns_empty_dict_on_fetch_failure(self):
        """get_fundamentals returns {} if yfinance raises an exception."""
        fc = _fresh_cache()

        with patch("yfinance.Ticker", side_effect=Exception("network error")):
            result = fc.get_fundamentals("INFY")

        assert result == {}

    def test_caches_result_on_second_call(self):
        """Second call for the same symbol hits the cache, not yfinance."""
        fc = _fresh_cache()
        mock_ticker = MagicMock()
        mock_ticker.info = {"trailingPE": 18.0}

        with patch("yfinance.Ticker", return_value=mock_ticker) as mock_yf:
            fc.get_fundamentals("TCS")
            fc.get_fundamentals("TCS")

        # yfinance.Ticker should be called exactly once (second call is cached)
        assert mock_yf.call_count == 1

    def test_none_values_handled_gracefully(self):
        """Keys present in yfinance info but set to None are returned as None (no error)."""
        fc = _fresh_cache()
        fake_info = {"trailingPE": None, "debtToEquity": None}
        mock_ticker = MagicMock()
        mock_ticker.info = fake_info

        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = fc.get_fundamentals("WIPRO")

        assert result["trailingPE"] is None
        assert result["debtToEquity"] is None


# ── TestGetQuarterlyEarningsTrend ────────────────────────────────────────────

class TestGetQuarterlyEarningsTrend:

    def test_improving_trend(self):
        """EPS values [18, 16, 14, 12] (newest first) → IMPROVING."""
        fc = _fresh_cache()
        df = _make_eps_df([18.0, 16.0, 14.0, 12.0])
        mock_ticker = MagicMock()
        mock_ticker.quarterly_income_stmt = df

        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = fc.get_quarterly_earnings_trend("INFY")

        assert result == "IMPROVING"

    def test_deteriorating_trend(self):
        """EPS values [12, 14, 16, 18] (newest first) → DETERIORATING."""
        fc = _fresh_cache()
        df = _make_eps_df([12.0, 14.0, 16.0, 18.0])
        mock_ticker = MagicMock()
        mock_ticker.quarterly_income_stmt = df

        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = fc.get_quarterly_earnings_trend("INFY")

        assert result == "DETERIORATING"

    def test_stable_trend(self):
        """EPS values with no clear direction (mixed diffs) → STABLE."""
        fc = _fresh_cache()
        # diffs: [18-17=+1, 17-17=0, 17-18=-1] → 1 positive, 1 negative → STABLE
        df = _make_eps_df([18.0, 17.0, 17.0, 18.0])
        mock_ticker = MagicMock()
        mock_ticker.quarterly_income_stmt = df

        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = fc.get_quarterly_earnings_trend("HDFC")

        assert result == "STABLE"

    def test_returns_stable_on_missing_eps_row(self):
        """If no 'Basic EPS' or 'Diluted EPS' row exists, returns STABLE (fail-open)."""
        fc = _fresh_cache()
        # DataFrame with a completely different index — no EPS rows
        df = pd.DataFrame({"Q1": [100.0], "Q2": [110.0]}, index=["Total Revenue"])
        mock_ticker = MagicMock()
        mock_ticker.quarterly_income_stmt = df

        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = fc.get_quarterly_earnings_trend("SBIN")

        assert result == "STABLE"

    def test_returns_stable_on_exception(self):
        """If yfinance raises an exception, returns STABLE (fail-open, never block trading)."""
        fc = _fresh_cache()

        with patch("yfinance.Ticker", side_effect=RuntimeError("connection reset")):
            result = fc.get_quarterly_earnings_trend("HCLTECH")

        assert result == "STABLE"


# ── TestIsEarningsBlackout ───────────────────────────────────────────────────

class TestIsEarningsBlackout:

    def test_blackout_when_earnings_tomorrow(self):
        """Earnings scheduled for tomorrow → blackout is active (within 3-day window)."""
        fc = _fresh_cache()
        tomorrow = date.today() + timedelta(days=1)

        with patch.object(fc, "get_earnings_calendar", return_value=tomorrow):
            result = fc.is_earnings_blackout("RELIANCE")

        assert result is True

    def test_blackout_when_earnings_3_days_away(self):
        """Earnings 3 days away → still within the 3-day pre-blackout window → True."""
        fc = _fresh_cache()
        three_days = date.today() + timedelta(days=3)

        with patch.object(fc, "get_earnings_calendar", return_value=three_days):
            result = fc.is_earnings_blackout("TCS")

        assert result is True

    def test_not_blackout_when_earnings_4_days_away(self):
        """Earnings 4 days away → outside the 3-day window → False."""
        fc = _fresh_cache()
        four_days = date.today() + timedelta(days=4)

        with patch.object(fc, "get_earnings_calendar", return_value=four_days):
            result = fc.is_earnings_blackout("INFY")

        assert result is False

    def test_not_blackout_when_no_earnings_date(self):
        """No upcoming earnings date found → not in blackout → False."""
        fc = _fresh_cache()

        with patch.object(fc, "get_earnings_calendar", return_value=None):
            result = fc.is_earnings_blackout("WIPRO")

        assert result is False

    def test_returns_false_on_exception(self):
        """Exception in get_earnings_calendar → returns False (fail-open, never block trading)."""
        fc = _fresh_cache()

        with patch.object(fc, "get_earnings_calendar", side_effect=Exception("API down")):
            result = fc.is_earnings_blackout("HDFCBANK")

        assert result is False
