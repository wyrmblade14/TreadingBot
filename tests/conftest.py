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


@pytest.fixture(autouse=True)
def isolated_test_db(tmp_path, monkeypatch):
    """Point every test at a fresh SQLite DB in a temp directory.

    Tests never touch logs/trades.db and never require PostgreSQL to be running.
    Each test gets an empty database so there is no cross-test state pollution.
    """
    test_db = tmp_path / "test_trades.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db}")

    import execution.trade_log as tl
    from sqlalchemy import create_engine as _ce
    from sqlalchemy.orm import sessionmaker as _sm

    test_engine = _ce(f"sqlite:///{test_db}", echo=False)
    tl.engine = test_engine
    tl.SessionLocal = _sm(bind=test_engine)
    tl.Base.metadata.create_all(test_engine)

    yield

    test_engine.dispose()
