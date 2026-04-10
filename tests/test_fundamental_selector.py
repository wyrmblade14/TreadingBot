"""
Tests for analysis/fundamental_selector.py.

These tests keep all fundamentals data mocked so no network calls are made.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from analysis.fundamental_filter import FundamentalScore
from analysis.fundamental_selector import (
    DEFAULT_MAX_PER_SECTOR,
    FundamentalPick,
    rank_fundamental_universe,
    select_fundamental_watchlist,
)
from data.instruments import SYMBOL_TO_SECTOR


def _score(symbol: str, value: int) -> FundamentalScore:
    return FundamentalScore(
        score=value,
        checks={},
        sector=SYMBOL_TO_SECTOR.get(symbol, "Unknown"),
        symbol=symbol,
    )


def _patch_selector(score_map: dict[str, int], blackout: set[str] | None = None):
    blackout = blackout or set()
    mock_fc = MagicMock()
    mock_fc.is_earnings_blackout.side_effect = lambda symbol: symbol in blackout

    def _score_side_effect(symbol: str):
        return _score(symbol, score_map.get(symbol, 2))

    return patch("analysis.fundamental_selector.score_fundamentals", side_effect=_score_side_effect), patch(
        "analysis.fundamental_selector.fundamentals_cache",
        mock_fc,
    )


class TestRankFundamentalUniverse:

    def test_ranks_high_scores_before_static_order_ties(self):
        symbols = ["HDFCBANK", "INFY", "RELIANCE"]
        scores = {"HDFCBANK": 3, "INFY": 5, "RELIANCE": 4}

        p_score, p_cache = _patch_selector(scores)
        with p_score, p_cache:
            ranked = rank_fundamental_universe(symbols)

        assert [p.symbol for p in ranked] == ["INFY", "RELIANCE", "HDFCBANK"]
        assert all(isinstance(p, FundamentalPick) for p in ranked)

    def test_blackout_symbols_rank_after_non_blackout_symbols(self):
        symbols = ["HDFCBANK", "INFY", "RELIANCE"]
        scores = {"HDFCBANK": 5, "INFY": 3, "RELIANCE": 4}

        p_score, p_cache = _patch_selector(scores, blackout={"HDFCBANK"})
        with p_score, p_cache:
            ranked = rank_fundamental_universe(symbols)

        assert [p.symbol for p in ranked] == ["RELIANCE", "INFY", "HDFCBANK"]
        assert ranked[-1].earnings_blackout is True


class TestSelectFundamentalWatchlist:

    def test_selects_top_fundamental_scores(self):
        symbols = ["HDFCBANK", "INFY", "RELIANCE", "TCS"]
        scores = {"HDFCBANK": 2, "INFY": 5, "RELIANCE": 4, "TCS": 3}

        p_score, p_cache = _patch_selector(scores)
        with p_score, p_cache:
            selected, _ranked = select_fundamental_watchlist(2, symbols=symbols)

        assert selected == ["INFY", "RELIANCE"]

    def test_excludes_blackout_when_enough_alternatives_exist(self):
        symbols = ["HDFCBANK", "INFY", "RELIANCE", "TCS"]
        scores = {"HDFCBANK": 5, "INFY": 4, "RELIANCE": 4, "TCS": 3}

        p_score, p_cache = _patch_selector(scores, blackout={"HDFCBANK"})
        with p_score, p_cache:
            selected, _ranked = select_fundamental_watchlist(2, symbols=symbols)

        assert selected == ["INFY", "RELIANCE"]
        assert "HDFCBANK" not in selected

    def test_relaxes_min_score_to_fill_watchlist(self):
        symbols = ["HDFCBANK", "INFY", "RELIANCE"]
        scores = {"HDFCBANK": 2, "INFY": 2, "RELIANCE": 1}

        p_score, p_cache = _patch_selector(scores)
        with p_score, p_cache:
            selected, _ranked = select_fundamental_watchlist(3, symbols=symbols, min_score=4)

        assert selected == ["HDFCBANK", "INFY", "RELIANCE"]

    def test_sector_cap_prevents_overconcentration_then_relaxes_if_needed(self):
        symbols = ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "INFY", "RELIANCE"]
        scores = {
            "HDFCBANK": 5,
            "ICICIBANK": 5,
            "KOTAKBANK": 5,
            "INFY": 4,
            "RELIANCE": 3,
        }

        p_score, p_cache = _patch_selector(scores)
        with p_score, p_cache:
            selected, _ranked = select_fundamental_watchlist(
                4,
                symbols=symbols,
                max_per_sector=2,
            )

        assert selected[:3] == ["HDFCBANK", "ICICIBANK", "INFY"]
        assert selected[3] == "RELIANCE"

    def test_returns_ranked_picks_even_when_count_is_zero(self):
        symbols = ["HDFCBANK", "INFY"]
        scores = {"HDFCBANK": 3, "INFY": 5}

        p_score, p_cache = _patch_selector(scores)
        with p_score, p_cache:
            selected, ranked = select_fundamental_watchlist(0, symbols=symbols)

        assert selected == []
        assert [p.symbol for p in ranked] == ["INFY", "HDFCBANK"]


def test_default_sector_cap_is_reasonable():
    assert DEFAULT_MAX_PER_SECTOR >= 2
