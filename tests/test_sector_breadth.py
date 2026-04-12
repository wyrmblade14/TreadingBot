"""
Unit tests for the Sector Breadth rule in Risk Manager.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from risk.risk_manager import RiskManager
from strategies.base_strategy import Action, Signal
from analysis.market_overview import MarketOverview

CAPITAL = 100_000.0
MARKET_OPEN_TIME = "2024-01-02 10:00:00+05:30"

def make_signal(action: Action = Action.BUY) -> Signal:
    if action == Action.BUY:
        return Signal(
            symbol="RELIANCE",
            action=action,
            entry_price=500.0,
            stop_loss=490.0,
            target=525.0,
            strategy="test",
        )
    else:
        return Signal(
            symbol="RELIANCE",
            action=action,
            entry_price=500.0,
            stop_loss=510.0,
            target=475.0,
            strategy="test",
        )

def make_overview(advances: int, declines: int, total: int = 50) -> MarketOverview:
    return MarketOverview(
        nifty_price=22000.0,
        nifty_change=100.0,
        nifty_change_pct=0.5,
        advances=advances,
        declines=declines,
        unchanged=total - advances - declines,
        top_gainers=[],
        top_losers=[],
        total_symbols=total
    )

class TestSectorBreadth:

    @patch("risk.risk_manager.get_nifty_overview")
    @patch("risk.risk_manager.datetime")
    def test_buy_suppressed_on_low_advances(self, mock_dt, mock_overview):
        """Rule: If advances / total < 0.2, suppress BUY entries."""
        mock_dt.now.return_value = datetime.fromisoformat(MARKET_OPEN_TIME)
        # 9 advances out of 50 = 18% < 20%
        mock_overview.return_value = make_overview(advances=9, declines=35)
        
        rm = RiskManager(CAPITAL)
        sig = make_signal(Action.BUY)
        decision = rm.evaluate(sig)
        
        assert not decision.approved
        assert "Market Breadth: broad weakness" in decision.reason
        assert "18.0% up" in decision.reason

    @patch("risk.risk_manager.get_nifty_overview")
    @patch("risk.risk_manager.datetime")
    def test_sell_suppressed_on_low_declines(self, mock_dt, mock_overview):
        """Rule: If declines / total < 0.2, suppress SELL entries."""
        mock_dt.now.return_value = datetime.fromisoformat(MARKET_OPEN_TIME)
        # 5 declines out of 50 = 10% < 20%
        mock_overview.return_value = make_overview(advances=40, declines=5)
        
        rm = RiskManager(CAPITAL)
        sig = make_signal(Action.SELL)
        decision = rm.evaluate(sig)
        
        assert not decision.approved
        assert "Market Breadth: broad strength" in decision.reason
        assert "10.0% down" in decision.reason

    @patch("risk.risk_manager.get_nifty_overview")
    @patch("risk.risk_manager.datetime")
    def test_buy_approved_on_healthy_breadth(self, mock_dt, mock_overview):
        """If advances >= 20%, BUY should be allowed (all else equal)."""
        mock_dt.now.return_value = datetime.fromisoformat(MARKET_OPEN_TIME)
        # 15 advances out of 50 = 30% >= 20%
        mock_overview.return_value = make_overview(advances=15, declines=30)
        
        rm = RiskManager(CAPITAL)
        sig = make_signal(Action.BUY)
        decision = rm.evaluate(sig)
        
        assert decision.approved

    @patch("risk.risk_manager.get_nifty_overview")
    @patch("risk.risk_manager.datetime")
    def test_sell_approved_on_healthy_breadth(self, mock_dt, mock_overview):
        """If declines >= 20%, SELL should be allowed."""
        mock_dt.now.return_value = datetime.fromisoformat(MARKET_OPEN_TIME)
        # 15 declines out of 50 = 30% >= 20%
        mock_overview.return_value = make_overview(advances=30, declines=15)
        
        rm = RiskManager(CAPITAL)
        sig = make_signal(Action.SELL)
        decision = rm.evaluate(sig)
        
        assert decision.approved

    @patch("risk.risk_manager.get_nifty_overview")
    @patch("risk.risk_manager.datetime")
    def test_fail_open_on_fetch_error(self, mock_dt, mock_overview):
        """If breadth data fetch fails, don't block trading."""
        mock_dt.now.return_value = datetime.fromisoformat(MARKET_OPEN_TIME)
        mock_overview.side_effect = Exception("API Down")
        
        rm = RiskManager(CAPITAL)
        sig = make_signal(Action.BUY)
        decision = rm.evaluate(sig)
        
        assert decision.approved

    @patch("risk.risk_manager.get_nifty_overview")
    @patch("risk.risk_manager.datetime")
    def test_ignored_on_low_symbol_count(self, mock_dt, mock_overview):
        """If we only have data for a few symbols, don't trust the breadth check."""
        mock_dt.now.return_value = datetime.fromisoformat(MARKET_OPEN_TIME)
        # 2 advances out of 10 = 20% (ratio is okay, but count is low)
        mock_overview.return_value = make_overview(advances=2, declines=5, total=10)
        
        rm = RiskManager(CAPITAL)
        sig = make_signal(Action.BUY)
        decision = rm.evaluate(sig)
        
        assert decision.approved
