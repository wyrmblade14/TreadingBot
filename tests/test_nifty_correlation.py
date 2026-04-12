"""
Tests for analysis/nifty_correlation.py — NIFTY divergence filter.

Each test injects a synthetic DataFrame and checks the DivergenceResult fields.
The module is fail-open: any error returns IN_LINE (no suppression).
"""

from __future__ import annotations

from datetime import date, datetime, time
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from analysis.nifty_correlation import get_divergence, get_nifty_change, DivergenceResult


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_df(open_px: float, close_px: float, today: date | None = None) -> pd.DataFrame:
    """
    Build a minimal 5m DataFrame with two rows for today.
    First row = opening candle (open_px), last row = current candle (close_px).
    """
    if today is None:
        today = date.today()
    idx = pd.DatetimeIndex([
        datetime(today.year, today.month, today.day, 9, 15),
        datetime(today.year, today.month, today.day, 10, 30),
    ])
    return pd.DataFrame(
        {
            "open":  [open_px, open_px],
            "high":  [open_px * 1.01, open_px * 1.01],
            "low":   [open_px * 0.99, open_px * 0.99],
            "close": [open_px, close_px],
            "volume": [1000, 1000],
        },
        index=idx,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_lagging_suppress_buy_amplify_sell():
    """NIFTY +1.2%, stock +0.1% → LAGGING: suppress_buy=True, amplify_sell=True."""
    df = _make_df(1000, 1001)  # +0.1%
    result = get_divergence("RELIANCE", df, nifty_chg=1.2)

    assert result.label == "LAGGING"
    assert result.suppress_buy is True
    assert result.suppress_sell is False
    assert result.amplify_sell is True


def test_inline_stock_participating():
    """NIFTY +1.2%, stock +1.0% → IN_LINE: stock is moving with the market."""
    df = _make_df(1000, 1010)  # +1.0%
    result = get_divergence("TCS", df, nifty_chg=1.2)

    assert result.label == "IN_LINE"
    assert result.suppress_buy is False
    assert result.suppress_sell is False
    assert result.amplify_sell is False


def test_lagging_stock_negative_on_positive_nifty():
    """NIFTY +1.5%, stock −0.5% → LAGGING (stock even worse than flat)."""
    df = _make_df(1000, 995)  # -0.5%
    result = get_divergence("INFY", df, nifty_chg=1.5)

    assert result.label == "LAGGING"
    assert result.suppress_buy is True
    assert result.amplify_sell is True


def test_leading_suppress_sell():
    """NIFTY −1.0%, stock −0.1% → LEADING: stock holding up, suppress SELL."""
    df = _make_df(1000, 999)  # -0.1%
    result = get_divergence("HDFCBANK", df, nifty_chg=-1.0)

    assert result.label == "LEADING"
    assert result.suppress_sell is True
    assert result.suppress_buy is False
    assert result.amplify_sell is False


def test_inline_nifty_below_threshold():
    """NIFTY +0.5%, stock flat → IN_LINE: NIFTY hasn't moved enough to matter."""
    df = _make_df(1000, 1000)  # 0%
    result = get_divergence("WIPRO", df, nifty_chg=0.5)

    assert result.label == "IN_LINE"
    assert result.suppress_buy is False
    assert result.suppress_sell is False


def test_fail_open_empty_dataframe():
    """Empty DataFrame → IN_LINE (data error never blocks a signal)."""
    result = get_divergence("BAJFINANCE", pd.DataFrame(), nifty_chg=1.5)

    assert result.label == "IN_LINE"
    assert result.suppress_buy is False
    assert result.suppress_sell is False
    assert result.amplify_sell is False


def test_fail_open_none_dataframe():
    """None DataFrame → IN_LINE (fail-open)."""
    result = get_divergence("AXISBANK", None, nifty_chg=1.5)

    assert result.label == "IN_LINE"


def test_lagging_sell_passes_through():
    """LAGGING stock + SELL signal: suppress_buy=True but suppress_sell=False → SELL passes."""
    df = _make_df(1000, 1001)  # +0.1% — lagging vs NIFTY +1.5%
    result = get_divergence("KOTAKBANK", df, nifty_chg=1.5)

    assert result.label == "LAGGING"
    assert result.suppress_buy is True
    # SELL is NOT suppressed — relative weakness short is valid
    assert result.suppress_sell is False


def test_get_nifty_change_before_10am_returns_zero():
    """get_nifty_change() returns 0.0 before 10:00 AM IST (opening noise)."""
    from config.settings import IST

    fake_now = datetime(2026, 4, 11, 9, 30, tzinfo=IST)  # 09:30 IST
    with patch("analysis.nifty_correlation.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        # Force cache miss so it runs the early-exit branch
        import analysis.nifty_correlation as _mod
        _mod._cache["timestamp"] = 0.0

        result = get_nifty_change()

    assert result == 0.0
