"""
Tests for monitoring/degradation.py — strategy health checking.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from monitoring.degradation import StrategyHealth, check_all_strategies, check_strategy


# ── Helpers ───────────────────────────────────────────────────────────

def _make_health(
    strategy: str = "ema_crossover",
    baseline: float = 50.0,
    rolling: float | None = None,
    count: int = 0,
    min_trades: int = 10,
    threshold: float = 15.0,
) -> StrategyHealth:
    return StrategyHealth(
        strategy=strategy,
        baseline_win_rate=baseline,
        rolling_win_rate=rolling,
        trade_count=count,
        min_trades=min_trades,
        threshold_pct=threshold,
    )


# ── StrategyHealth unit tests ─────────────────────────────────────────

class TestStrategyHealth:

    def test_not_degraded_when_too_few_trades(self):
        h = _make_health(rolling=20.0, count=5, min_trades=10)
        assert not h.is_degraded

    def test_not_degraded_when_no_rolling(self):
        h = _make_health(rolling=None, count=0)
        assert not h.is_degraded

    def test_degraded_when_drop_exceeds_threshold(self):
        h = _make_health(baseline=50.0, rolling=30.0, count=20, threshold=15.0)
        # drop = 50 - 30 = 20pp > 15pp threshold
        assert h.is_degraded

    def test_not_degraded_when_drop_at_threshold(self):
        h = _make_health(baseline=50.0, rolling=35.0, count=20, threshold=15.0)
        # drop = 50 - 35 = 15pp, NOT strictly greater than threshold
        assert not h.is_degraded

    def test_not_degraded_when_above_baseline(self):
        h = _make_health(baseline=50.0, rolling=60.0, count=20)
        assert not h.is_degraded

    def test_drop_pct_positive_when_worse(self):
        h = _make_health(baseline=50.0, rolling=35.0, count=20)
        assert h.drop_pct == 15.0

    def test_drop_pct_negative_when_better(self):
        h = _make_health(baseline=50.0, rolling=60.0, count=20)
        assert h.drop_pct == -10.0

    def test_drop_pct_none_when_no_rolling(self):
        h = _make_health(rolling=None, count=0)
        assert h.drop_pct is None

    def test_alert_message_only_when_degraded(self):
        degraded = _make_health(baseline=50.0, rolling=25.0, count=20, threshold=15.0)
        healthy  = _make_health(baseline=50.0, rolling=55.0, count=20, threshold=15.0)
        assert degraded.alert_message is not None
        assert healthy.alert_message is None

    def test_status_label_watching_when_few_trades(self):
        h = _make_health(count=3, min_trades=10)
        assert "WATCHING" in h.status_label
        assert "3/10" in h.status_label

    def test_status_label_degraded(self):
        h = _make_health(baseline=50.0, rolling=25.0, count=20, threshold=15.0)
        assert "DEGRADED" in h.status_label

    def test_status_label_healthy(self):
        h = _make_health(baseline=50.0, rolling=55.0, count=20)
        assert "HEALTHY" in h.status_label

    def test_has_enough_trades(self):
        assert _make_health(count=10, min_trades=10).has_enough_trades
        assert not _make_health(count=9, min_trades=10).has_enough_trades


# ── check_strategy integration ────────────────────────────────────────

class TestCheckStrategy:

    def _mock_logger(self, win_rate: float | None, count: int) -> MagicMock:
        mock = MagicMock()
        mock.get_rolling_win_rate.return_value = (win_rate, count)
        return mock

    def test_returns_strategy_health(self):
        result = check_strategy("ema_crossover", self._mock_logger(45.0, 20))
        assert isinstance(result, StrategyHealth)
        assert result.strategy == "ema_crossover"

    def test_uses_baseline_from_config(self):
        result = check_strategy("ema_crossover", self._mock_logger(45.0, 20))
        assert result.baseline_win_rate == 50.0  # from STRATEGY_BASELINES

    def test_unknown_strategy_defaults_50(self):
        result = check_strategy("unknown_strat", self._mock_logger(40.0, 20))
        assert result.baseline_win_rate == 50.0

    def test_degraded_strategy_detected(self):
        result = check_strategy("ema_crossover", self._mock_logger(30.0, 20))
        # baseline=50, rolling=30, drop=20 > 15 threshold
        assert result.is_degraded

    def test_healthy_strategy(self):
        result = check_strategy("ema_crossover", self._mock_logger(52.0, 20))
        assert not result.is_degraded


# ── check_all_strategies ──────────────────────────────────────────────

class TestCheckAllStrategies:

    def _mock_logger(self, mapping: dict[str, tuple[float | None, int]]) -> MagicMock:
        """mapping: strategy_name -> (win_rate, count)"""
        mock = MagicMock()
        mock.get_rolling_win_rate.side_effect = lambda strategy, n: mapping.get(
            strategy, (None, 0)
        )
        return mock

    def test_returns_all_strategies(self):
        from config.settings import STRATEGY_BASELINES
        mock = self._mock_logger({})
        results = check_all_strategies(logger=mock)
        assert len(results) == len(STRATEGY_BASELINES)

    def test_degraded_strategies_sorted_first(self):
        mock = self._mock_logger({
            "ema_crossover":          (25.0, 20),   # degraded
            "rsi_macd_combo":         (48.0, 20),   # healthy
            "opening_range_breakout": (35.0, 20),   # caution (not degraded: 50-35=15, not > 15)
        })
        results = check_all_strategies(logger=mock)
        assert results[0].is_degraded   # degraded is first

    def test_creates_logger_if_none(self):
        """Should not raise — creates a real TradeLogger if none provided."""
        # Uses real DB but should just return 0 trades since DB is likely empty in CI
        results = check_all_strategies()
        assert all(isinstance(h, StrategyHealth) for h in results)
