"""
Tests for Walk-Forward Analysis — ensuring rolling windows and trade filtering work.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import pytz

from backtesting.engine import BacktestResult, BacktestTrade
from backtesting.walk_forward import WalkForwardEngine, WalkForwardResult
from strategies.base_strategy import Action, BaseStrategy

IST = pytz.timezone("Asia/Kolkata")


class MockStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(name="mock_strategy")
    def generate_signal(self, symbol, df):
        return self.hold_signal(symbol, 0)


def make_trade(entry_date: date, pnl: float = 100.0) -> BacktestTrade:
    """Helper to create a trade on a specific date."""
    entry_time = IST.localize(datetime.combine(entry_date, datetime.min.time()) + timedelta(hours=10))
    exit_time = entry_time + timedelta(minutes=30)
    return BacktestTrade(
        symbol="TEST",
        strategy="mock",
        action=Action.BUY,
        quantity=10,
        entry_price=500.0,
        exit_price=500.0 + (pnl / 10),
        stop_loss=490.0,
        target=520.0,
        entry_time=entry_time,
        exit_time=exit_time,
        exit_reason="target" if pnl > 0 else "stop_loss",
        brokerage=0.0,
    )


class TestWalkForwardEngineFiltering:

    @patch("backtesting.walk_forward.BacktestEngine")
    @patch("backtesting.walk_forward.calculate")
    def test_run_filters_train_period_trades(self, mock_calculate, mock_engine_cls):
        # Setup mock engine
        mock_engine = mock_engine_cls.return_value
        
        # Define a window: Train Jan-Jun, Test Jul-Aug
        train_start = date(2023, 1, 1)
        test_start = date(2023, 7, 1)
        test_end = date(2023, 8, 31)
        
        # Create trades: one in train, one in test
        trade_train = make_trade(date(2023, 3, 1), pnl=500.0)
        trade_test = make_trade(date(2023, 7, 15), pnl=300.0)
        
        # Mock result from BacktestEngine.run
        mock_bt_result = BacktestResult(
            symbol="TEST",
            strategy_name="mock",
            start_date=train_start,
            end_date=test_end,
            initial_capital=100_000,
            trades=[trade_train, trade_test]
        )
        mock_engine.run.return_value = mock_bt_result
        
        # Mock metrics
        mock_metrics = MagicMock()
        mock_metrics.total_net_pnl = 300.0
        mock_metrics.num_trades = 1
        mock_metrics.win_rate_pct = 100.0
        mock_metrics.summary.return_value = "Mock Summary"
        mock_calculate.return_value = mock_metrics

        # Run Walk-Forward Engine for exactly ONE window
        strategy = MockStrategy()
        # To get one window: 2023-01-01 to 2023-08-31 with 6m train, 2m test
        engine = WalkForwardEngine(strategy, train_months=6, test_months=2)
        
        with patch("backtesting.walk_forward.logger"):
            result = engine.run("TEST", start="2023-01-01", end="2023-08-31")

        # Assertions
        assert result.num_windows == 1
        window = result.windows[0]
        
        # Verify filtering: window.result.trades should only have the test trade
        assert len(window.result.trades) == 1
        assert window.result.trades[0].entry_time.date() == date(2023, 7, 15)
        
        # Verify engine.run was called with train_start
        mock_engine.run.assert_called_with(
            symbol="TEST",
            start=str(train_start),
            end=str(test_end)
        )

    def test_build_windows_logic(self):
        engine = WalkForwardEngine(MockStrategy(), train_months=6, test_months=2, step_months=2)
        windows = engine._build_windows("2023-01-01", "2023-12-31")
        
        # Window 1: Jan-Jun (6m) -> Test Jul-Aug (2m). Ends Aug 31.
        # Window 2: Mar-Aug (6m) -> Test Sep-Oct (2m). Ends Oct 31.
        # Window 3: May-Oct (6m) -> Test Nov-Dec (2m). Ends Dec 31.
        # Next window would end Feb 28, 2024 -> exceeds 2023-12-31.
        
        assert len(windows) == 3
        
        w1 = windows[0]
        assert w1[0] == date(2023, 1, 1) # train_start
        assert w1[1] == date(2023, 6, 30) # train_end
        assert w1[2] == date(2023, 7, 1) # test_start
        assert w1[3] == date(2023, 8, 31) # test_end

        w3 = windows[2]
        assert w3[0] == date(2023, 5, 1)
        assert w3[3] == date(2023, 12, 31)


class TestWalkForwardRobustness:
    def test_is_robust_logic(self):
        wf = WalkForwardResult(symbol="TEST", strategy_name="mock", train_months=6, test_months=2)
        
        # Need at least 3 windows, >60% consistency, >45% avg win rate
        from backtesting.walk_forward import WindowResult
        from unittest.mock import MagicMock
        
        def make_window(profitable, win_rate):
            m = MagicMock()
            m.total_net_pnl = 100.0 if profitable else -100.0
            m.win_rate_pct = win_rate
            m.num_trades = 10
            return WindowResult(
                window_num=1, train_start=date(2023,1,1), train_end=date(2023,6,30),
                test_start=date(2023,7,1), test_end=date(2023,8,31),
                result=MagicMock(), metrics=m
            )

        # 1. Too few windows
        wf.windows = [make_window(True, 50), make_window(True, 50)]
        assert wf.is_robust is False
        
        # 2. Low consistency
        wf.windows = [make_window(True, 50), make_window(False, 50), make_window(False, 50)]
        assert wf.consistency_pct == 33.3 # approx
        assert wf.is_robust is False
        
        # 3. Low win rate
        wf.windows = [make_window(True, 30), make_window(True, 30), make_window(True, 30)]
        assert wf.consistency_pct == 100.0
        assert wf.avg_win_rate == 30.0
        assert wf.is_robust is False
        
        # 4. Robust
        wf.windows = [make_window(True, 50), make_window(True, 50), make_window(False, 50)]
        # consistency = 66.7%, win rate = 50%
        assert wf.is_robust is True

    def test_avg_profit_factor_handles_inf(self):
        wf = WalkForwardResult(symbol="TEST", strategy_name="mock", train_months=6, test_months=2)
        
        from backtesting.walk_forward import WindowResult
        from unittest.mock import MagicMock
        
        def make_window_pf(pf):
            m = MagicMock()
            m.profit_factor = pf
            m.num_trades = 5
            return WindowResult(
                window_num=1, train_start=date(2023,1,1), train_end=date(2023,6,30),
                test_start=date(2023,7,1), test_end=date(2023,8,31),
                result=MagicMock(), metrics=m
            )

        # All inf
        wf.windows = [make_window_pf(float("inf")), make_window_pf(float("inf"))]
        assert wf.avg_profit_factor == float("inf")
        
        # Mixed inf and finite
        wf.windows = [make_window_pf(float("inf")), make_window_pf(2.0)]
        assert wf.avg_profit_factor == 2.0  # Currently filters out inf for average
        
        # All finite
        wf.windows = [make_window_pf(1.5), make_window_pf(2.5)]
        assert wf.avg_profit_factor == 2.0
