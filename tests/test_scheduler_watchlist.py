"""
Tests for scheduler/watchlist.py.

These verify the scheduler-facing watchlist wrapper without hitting yfinance.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from analysis.fundamental_analyst import FundamentalJudgment
from analysis.fundamental_selector import FundamentalPick
from data.instruments import KITE_SYMBOLS, SYMBOL_TO_SECTOR
from scheduler.watchlist import (
    DailyWatchlist,
    get_fundamental_judgment,
    select_daily_watchlist,
    static_watchlist,
)


def _pick(symbol: str, score: int = 4) -> FundamentalPick:
    return FundamentalPick(
        symbol=symbol,
        sector=SYMBOL_TO_SECTOR.get(symbol, "Unknown"),
        score=score,
        label="High" if score >= 4 else "Moderate",
        earnings_blackout=False,
        rank_score=float(score),
        reason=f"{score}/5 fundamentals",
        source_order=0,
    )


class TestStaticWatchlist:

    def test_static_watchlist_bounds_size(self):
        assert static_watchlist(2) == KITE_SYMBOLS[:2]
        assert static_watchlist(-5) == []
        assert static_watchlist(999) == KITE_SYMBOLS

    def test_static_watchlist_invalid_size_defaults_to_10(self):
        assert static_watchlist("bad") == KITE_SYMBOLS[:10]


class TestSelectDailyWatchlist:

    def test_returns_fundamental_selection_when_available(self):
        ranked = [_pick("INFY", 5), _pick("RELIANCE", 4)]
        with patch(
            "scheduler.watchlist.select_fundamental_watchlist",
            return_value=(["INFY", "RELIANCE"], ranked),
        ):
            result = select_daily_watchlist(2)

        assert isinstance(result, DailyWatchlist)
        assert result.source == "fundamental"
        assert result.symbols == ["INFY", "RELIANCE"]
        assert result.detail_strings() == [
            "INFY(5/5,Information Technology)",
            "RELIANCE(4/5,Oil & Gas)",
        ]

    def test_falls_back_to_static_watchlist_on_selector_exception(self):
        with patch(
            "scheduler.watchlist.select_fundamental_watchlist",
            side_effect=RuntimeError("network down"),
        ):
            result = select_daily_watchlist(3)

        assert result.source == "static_fallback"
        assert result.symbols == KITE_SYMBOLS[:3]
        assert result.ranked_picks == []

    def test_empty_when_size_resolves_to_zero(self):
        result = select_daily_watchlist(0)

        assert result.source == "empty"
        assert result.symbols == []


class TestFundamentalJudgment:

    def test_returns_none_when_metrics_unavailable(self):
        with patch("data.fundamentals.fundamentals_cache") as mock_fc:
            mock_fc.get_fundamentals.return_value = {}

            result = get_fundamental_judgment("INFY")

        assert result is None

    def test_returns_analyst_judgment_when_metrics_exist(self):
        expected = FundamentalJudgment(
            bias="BULLISH",
            confidence=0.7,
            position_scale=1.0,
            key_strengths=[],
            key_risks=[],
            summary="test",
            source="rule_based",
        )
        mock_analyst = MagicMock()
        mock_analyst.analyze.return_value = expected

        with patch("data.fundamentals.fundamentals_cache") as mock_fc, patch(
            "analysis.fundamental_analyst.analyst",
            mock_analyst,
        ):
            mock_fc.get_fundamentals.return_value = {"trailingPE": 18.0}

            result = get_fundamental_judgment("INFY")

        assert result == expected
        mock_analyst.analyze.assert_called_once_with("INFY", {"trailingPE": 18.0})
