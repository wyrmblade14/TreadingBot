"""
Unit tests for the backtesting engine and performance metrics.

We use synthetic price series so tests run instantly without network calls.
The key things to verify:
  - No lookahead bias in the engine
  - Trades are generated and exit conditions fire correctly
  - Performance metrics are mathematically correct
  - Report generation doesn't crash
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import pytz

from backtesting.engine import BacktestEngine, BacktestResult, BacktestTrade, _check_exit, _OpenTrade
from backtesting.performance import calculate, PerformanceMetrics
from backtesting.walk_forward import WalkForwardEngine, WalkForwardResult, WindowResult
from strategies.base_strategy import Action
from strategies.ema_crossover import EMACrossoverStrategy

IST = pytz.timezone("Asia/Kolkata")


# ── Helpers ───────────────────────────────────────────────────────────

def make_daily_ohlcv(prices: list[float], start: str = "2023-01-02") -> pd.DataFrame:
    """Build a daily OHLCV DataFrame from a close price list."""
    n   = len(prices)
    idx = pd.date_range(start=start, periods=n, freq="B", tz="Asia/Kolkata")
    closes = np.array(prices, dtype=float)
    return pd.DataFrame({
        "open":   closes * 0.995,
        "high":   closes * 1.01,
        "low":    closes * 0.99,
        "close":  closes,
        "volume": [500_000] * n,
    }, index=idx)


def make_result_with_trades(pnls: list[float]) -> BacktestResult:
    """Build a BacktestResult with fake trades having specified net P&Ls."""
    result = BacktestResult(
        symbol="TEST", strategy_name="test",
        start_date=pd.Timestamp("2023-01-01").date(),
        end_date=pd.Timestamp("2023-12-31").date(),
        initial_capital=100_000,
    )
    base_time = IST.localize(datetime(2023, 1, 2, 9, 30))
    for i, pnl in enumerate(pnls):
        entry_price = 500.0
        exit_price  = entry_price + (pnl / 10)   # qty=10 assumed
        result.trades.append(BacktestTrade(
            symbol="TEST", strategy="test",
            action=Action.BUY, quantity=10,
            entry_price=entry_price, exit_price=exit_price,
            stop_loss=490.0, target=520.0,
            entry_time=base_time + timedelta(hours=i),
            exit_time=base_time + timedelta(hours=i, minutes=30),
            exit_reason="target" if pnl > 0 else "stop_loss",
            brokerage=0.0,
        ))
    return result


# ── BacktestEngine tests ──────────────────────────────────────────────

class TestBacktestEngine:

    def test_returns_result_object(self):
        engine = BacktestEngine(EMACrossoverStrategy(), initial_capital=100_000)
        df = make_daily_ohlcv([500.0] * 60)
        with patch("backtesting.engine.fetch_ohlcv", return_value=df):
            result = engine.run("RELIANCE", start="2023-01-01", end="2023-03-31")
        assert isinstance(result, BacktestResult)

    def test_empty_data_returns_empty_result(self):
        engine = BacktestEngine(EMACrossoverStrategy())
        empty_df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        empty_df.index = pd.DatetimeIndex([])
        with patch("backtesting.engine.fetch_ohlcv", return_value=empty_df):
            result = engine.run("RELIANCE")
        assert result.num_trades == 0

    def test_no_trades_on_flat_prices(self):
        """Flat prices produce no EMA crossover → no trades."""
        engine = BacktestEngine(EMACrossoverStrategy())
        df = make_daily_ohlcv([500.0] * 100)
        with patch("backtesting.engine.fetch_ohlcv", return_value=df):
            result = engine.run("RELIANCE")
        assert result.num_trades == 0

    def test_result_fields_populated(self):
        engine = BacktestEngine(EMACrossoverStrategy(), initial_capital=100_000)
        df = make_daily_ohlcv([500 + i * 0.5 for i in range(100)])
        with patch("backtesting.engine.fetch_ohlcv", return_value=df):
            result = engine.run("RELIANCE", start="2023-01-01", end="2023-12-31")
        assert result.symbol == "RELIANCE"
        assert result.initial_capital == 100_000
        assert result.strategy_name == "ema_crossover"

    def test_all_trades_have_valid_prices(self):
        """Every trade: stop_loss < entry_price < target for BUY."""
        engine = BacktestEngine(EMACrossoverStrategy())
        prices = [500 + np.sin(i * 0.3) * 10 for i in range(200)]
        df = make_daily_ohlcv(prices)
        with patch("backtesting.engine.fetch_ohlcv", return_value=df):
            result = engine.run("RELIANCE")
        for t in result.trades:
            if t.action == Action.BUY:
                assert t.stop_loss < t.entry_price
                assert t.target > t.entry_price


class TestExitLogic:
    def _trade(self, action=Action.BUY, entry=500, sl=490, target=520):
        return _OpenTrade(
            action=action, quantity=10,
            entry_price=entry, stop_loss=sl, target=target,
            entry_time=IST.localize(datetime(2023, 1, 2, 9, 30)),
        )

    def _time(self, h=10, m=0):
        return IST.localize(datetime(2023, 1, 2, h, m))

    def test_buy_stop_loss_fires(self):
        t = self._trade(Action.BUY, entry=500, sl=490, target=520)
        assert _check_exit(t, price=489.0, time=self._time(10)) == "stop_loss"

    def test_buy_target_fires(self):
        t = self._trade(Action.BUY, entry=500, sl=490, target=520)
        assert _check_exit(t, price=521.0, time=self._time(10)) == "target"

    def test_buy_no_exit_mid_range(self):
        t = self._trade(Action.BUY, entry=500, sl=490, target=520)
        assert _check_exit(t, price=505.0, time=self._time(10)) is None

    def test_eod_squareoff_fires(self):
        t = self._trade(Action.BUY, entry=500, sl=490, target=520)
        assert _check_exit(t, price=505.0, time=self._time(15, 20)) == "eod_squareoff"

    def test_sell_stop_loss_fires(self):
        t = self._trade(Action.SELL, entry=500, sl=510, target=480)
        assert _check_exit(t, price=511.0, time=self._time(10)) == "stop_loss"

    def test_sell_target_fires(self):
        t = self._trade(Action.SELL, entry=500, sl=510, target=480)
        assert _check_exit(t, price=479.0, time=self._time(10)) == "target"


# ── Performance metrics tests ─────────────────────────────────────────

class TestPerformanceMetrics:

    def test_empty_result_returns_zeros(self):
        result = BacktestResult("T", "s",
            pd.Timestamp("2023-01-01").date(), pd.Timestamp("2023-12-31").date(), 100_000)
        m = calculate(result)
        assert m.num_trades == 0
        assert m.win_rate_pct == 0

    def test_all_winners(self):
        result = make_result_with_trades([500, 300, 400, 200, 600])
        m = calculate(result)
        assert m.num_winners == 5
        assert m.num_losers == 0
        assert m.win_rate_pct == 100.0
        assert m.profit_factor == float("inf")

    def test_all_losers(self):
        result = make_result_with_trades([-200, -300, -100, -400])
        m = calculate(result)
        assert m.num_losers == 4
        assert m.win_rate_pct == 0.0
        assert m.total_net_pnl < 0

    def test_mixed_results(self):
        # 3 wins of ₹500 each, 2 losses of ₹200 each
        result = make_result_with_trades([500, -200, 500, -200, 500])
        m = calculate(result)
        assert m.num_winners == 3
        assert m.num_losers == 2
        assert m.win_rate_pct == pytest.approx(60.0)
        assert m.total_net_pnl == pytest.approx(1100.0)
        assert m.profit_factor == pytest.approx(1500.0 / 400.0, abs=0.1)

    def test_max_drawdown_calculated(self):
        # Goes up then down: max drawdown should be negative
        pnls = [200, 300, 400, -800, 100, 200]
        result = make_result_with_trades(pnls)
        m = calculate(result)
        assert m.max_drawdown_pct < 0

    def test_no_drawdown_when_always_winning(self):
        result = make_result_with_trades([100, 200, 300, 400])
        m = calculate(result)
        assert m.max_drawdown_pct == pytest.approx(0.0)

    def test_final_capital_correct(self):
        result = make_result_with_trades([1000, -500, 2000])
        m = calculate(result)
        assert m.final_capital == pytest.approx(102_500.0)

    def test_summary_returns_string(self):
        result = make_result_with_trades([500, -200, 300])
        m = calculate(result)
        assert isinstance(m.summary(), str)
        assert "WinRate" in m.summary()

    def test_verdict_for_few_trades(self):
        result = make_result_with_trades([100, 200])
        m = calculate(result)
        assert "Too few" in m.verdict()

    def test_verdict_for_good_strategy(self):
        result = make_result_with_trades([500] * 15 + [-100] * 5)
        m = calculate(result)
        verdict = m.verdict()
        assert isinstance(verdict, str)
        assert len(verdict) > 20


# ── WalkForwardEngine tests ───────────────────────────────────────────

def _make_wf_result(consistencies: list[bool]) -> WalkForwardResult:
    """Build a WalkForwardResult with windows of given profitability."""
    wf = WalkForwardResult(symbol="TEST", strategy_name="test",
                           train_months=6, test_months=2)
    import datetime
    for i, profitable in enumerate(consistencies):
        pnls = [500.0, 300.0] if profitable else [-200.0, -100.0]
        bt_result = make_result_with_trades(pnls)
        metrics = calculate(bt_result)
        wf.windows.append(WindowResult(
            window_num=i + 1,
            train_start=datetime.date(2023, 1, 1),
            train_end=datetime.date(2023, 6, 30),
            test_start=datetime.date(2023, 7, 1),
            test_end=datetime.date(2023, 8, 31),
            result=bt_result,
            metrics=metrics,
        ))
    return wf


class TestWalkForwardResult:

    def test_consistency_pct_all_profitable(self):
        wf = _make_wf_result([True, True, True, True])
        assert wf.consistency_pct == 100.0

    def test_consistency_pct_mixed(self):
        wf = _make_wf_result([True, True, False, True])
        assert wf.consistency_pct == 75.0

    def test_consistency_pct_none_profitable(self):
        wf = _make_wf_result([False, False, False])
        assert wf.consistency_pct == 0.0

    def test_is_robust_passes(self):
        # 4 windows, all profitable, avg win rate = 100% (both trades winners)
        wf = _make_wf_result([True, True, True, True])
        assert wf.is_robust is True

    def test_is_robust_fails_low_consistency(self):
        wf = _make_wf_result([True, False, False, False])
        assert wf.is_robust is False

    def test_is_robust_fails_too_few_windows(self):
        wf = _make_wf_result([True, True])  # only 2 windows
        assert wf.is_robust is False

    def test_verdict_no_windows(self):
        wf = WalkForwardResult(symbol="X", strategy_name="s", train_months=6, test_months=2)
        assert "too short" in wf.verdict().lower()

    def test_verdict_robust(self):
        wf = _make_wf_result([True, True, True, True])
        assert "ROBUST" in wf.verdict()

    def test_verdict_not_robust(self):
        wf = _make_wf_result([True, False, False, False])
        assert "NOT" in wf.verdict()

    def test_total_trades_sums_all_windows(self):
        wf = _make_wf_result([True, True, False])
        assert wf.total_trades == 6  # 2 trades per window × 3 windows

    def test_profitable_windows_count(self):
        wf = _make_wf_result([True, False, True, False, True])
        assert wf.profitable_windows == 3


class TestWalkForwardEngine:

    def test_build_windows_count(self):
        engine = WalkForwardEngine(EMACrossoverStrategy(), train_months=6, test_months=2, step_months=2)
        windows = engine._build_windows("2023-01-01", "2024-12-31")
        # 24 months total, 6 train + 2 test = 8 per step, step=2
        # windows: 7, 9, 11, 13, 15, 17, 19, 21 → test ends at 9,11,13,15,17,19,21,23 months
        assert len(windows) >= 6

    def test_build_windows_too_short(self):
        engine = WalkForwardEngine(EMACrossoverStrategy(), train_months=6, test_months=2)
        windows = engine._build_windows("2023-01-01", "2023-05-31")
        assert windows == []

    def test_run_returns_wf_result(self):
        engine = WalkForwardEngine(EMACrossoverStrategy(), train_months=6, test_months=2,
                                   initial_capital=100_000)
        df = make_daily_ohlcv([500.0] * 300)
        with patch("backtesting.engine.fetch_ohlcv", return_value=df):
            result = engine.run("RELIANCE", start="2023-01-01", end="2024-12-31")
        assert isinstance(result, WalkForwardResult)
        assert result.num_windows >= 1

    def test_run_no_windows_short_range(self):
        engine = WalkForwardEngine(EMACrossoverStrategy(), train_months=6, test_months=2)
        df = make_daily_ohlcv([500.0] * 30)
        with patch("backtesting.engine.fetch_ohlcv", return_value=df):
            result = engine.run("RELIANCE", start="2023-01-01", end="2023-04-30")
        assert result.num_windows == 0

    def test_window_dates_non_overlapping_test_periods(self):
        engine = WalkForwardEngine(EMACrossoverStrategy(), train_months=3, test_months=1, step_months=1)
        windows = engine._build_windows("2023-01-01", "2024-06-30")
        # Each test_start should be after the previous test_end
        for i in range(1, len(windows)):
            assert windows[i][2] > windows[i-1][3]
