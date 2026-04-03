"""
pytest configuration and shared fixtures.

Auto-patches external network calls so tests are deterministic and fast:
  - India VIX: returns a normal (non-restrictive) result so risk manager
    tests don't fail because today's real VIX happens to be above thresholds.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


_VIX_NORMAL = {
    "vix":       15.0,
    "level":     "normal",
    "skip_buys": False,
    "skip_all":  False,
}


@pytest.fixture(autouse=True)
def mock_india_vix():
    """Patch India VIX to return a safe, non-restrictive value for all tests."""
    with patch("risk.risk_manager._get_vix_data", return_value=_VIX_NORMAL):
        yield


@pytest.fixture(autouse=True)
def mock_fundamentals():
    """Patch earnings blackout to return False so Rule 11 doesn't block tests.

    Rule 11 in risk_manager.py calls is_earnings_blackout() inside a lazy import.
    Without this patch, tests running near a real earnings date would fail
    unpredictably because yfinance returns real data.
    """
    with patch("data.fundamentals.fundamentals_cache") as mock_fc:
        mock_fc.is_earnings_blackout.return_value = False
        yield mock_fc
