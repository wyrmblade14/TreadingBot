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
