"""
Unit tests for V-reversal early exit logic in OrderManager.

What we're testing:
  - A SELL trade entered within 30 min exits early when price crosses back above VWAP
  - A BUY trade entered within 30 min exits early when price falls back below VWAP
  - Trades older than 30 min are NOT exited by the reversal check (let SL/target run)
  - A SELL trade where price stays below VWAP is NOT exited
  - NaN/zero VWAP skips the check safely
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from broker.base_broker import OrderStatus, OrderType, TransactionType
from broker.paper_broker import PaperBroker
from config.settings import IST
from execution.order_manager import OpenTrade, OrderManager, _REVERSAL_WINDOW_SECS
from execution.trade_log import TradeLogger
from strategies.base_strategy import Action


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_order_manager() -> tuple[OrderManager, PaperBroker]:
    broker = PaperBroker(initial_capital=1_00_000.0, slippage_pct=0.0)
    logger = MagicMock(spec=TradeLogger)
    logger.record_exit.return_value = -200.0  # simulate a loss exit
    om = OrderManager(broker, logger, trading_mode="paper")
    return om, broker


def _inject_open_sell(
    om: OrderManager,
    broker: PaperBroker,
    symbol: str = "RELIANCE",
    entry_price: float = 1000.0,
    opened_at: datetime | None = None,
) -> OpenTrade:
    """Directly inject an open SELL trade into OrderManager (bypasses execute_signal)."""
    broker.restore_position(symbol, TransactionType.SELL, quantity=10, avg_price=entry_price)
    broker.update_ltp(symbol, entry_price)

    trade = OpenTrade(
        trade_log_id=1,
        symbol=symbol,
        action=Action.SELL,
        quantity=10,
        entry_price=entry_price,
        stop_loss=entry_price * 1.015,   # 1.5% above entry
        target=entry_price * 0.97,       # 3% below entry
        strategy="rsi_macd_combo",
        entry_order_id="test-001",
        opened_at=opened_at or datetime.now(IST),
    )
    om._open_trades[symbol] = trade
    return trade


def _inject_open_buy(
    om: OrderManager,
    broker: PaperBroker,
    symbol: str = "INFY",
    entry_price: float = 1500.0,
    opened_at: datetime | None = None,
) -> OpenTrade:
    """Directly inject an open BUY trade into OrderManager."""
    broker.restore_position(symbol, TransactionType.BUY, quantity=10, avg_price=entry_price)
    broker.update_ltp(symbol, entry_price)

    trade = OpenTrade(
        trade_log_id=2,
        symbol=symbol,
        action=Action.BUY,
        quantity=10,
        entry_price=entry_price,
        stop_loss=entry_price * 0.985,
        target=entry_price * 1.03,
        strategy="ema_crossover",
        entry_order_id="test-002",
        opened_at=opened_at or datetime.now(IST),
    )
    om._open_trades[symbol] = trade
    return trade


# ── Test cases ─────────────────────────────────────────────────────────────────

class TestReversalExitSell:

    def test_sell_reversal_fires_when_price_above_vwap(self):
        """SELL trade within 30 min: price crosses back above VWAP → early exit."""
        om, broker = _make_order_manager()
        _inject_open_sell(om, broker, entry_price=1000.0)

        result = om.check_reversal_exit("RELIANCE", current_price=1010.0, vwap=1005.0)

        assert result is not None, "Expected reversal exit to fire"
        assert "RELIANCE" not in om._open_trades, "Trade should be removed from open trades"

    def test_sell_no_reversal_when_price_still_below_vwap(self):
        """SELL trade: price remains below VWAP → no reversal exit."""
        om, broker = _make_order_manager()
        _inject_open_sell(om, broker, entry_price=1000.0)

        result = om.check_reversal_exit("RELIANCE", current_price=990.0, vwap=1005.0)

        assert result is None, "Should not exit — price is still below VWAP (short working)"

    def test_sell_reversal_skipped_after_window(self):
        """SELL trade older than 30 min: reversal check does nothing."""
        om, broker = _make_order_manager()
        old_entry = datetime.now(IST) - timedelta(seconds=_REVERSAL_WINDOW_SECS + 60)
        _inject_open_sell(om, broker, entry_price=1000.0, opened_at=old_entry)

        result = om.check_reversal_exit("RELIANCE", current_price=1015.0, vwap=1005.0)

        assert result is None, "Window expired — should not trigger reversal exit"
        assert "RELIANCE" in om._open_trades, "Trade should still be open"


class TestReversalExitBuy:

    def test_buy_reversal_fires_when_price_below_vwap(self):
        """BUY trade within 30 min: price falls back below VWAP → early exit."""
        om, broker = _make_order_manager()
        _inject_open_buy(om, broker, entry_price=1500.0)

        result = om.check_reversal_exit("INFY", current_price=1490.0, vwap=1495.0)

        assert result is not None, "Expected reversal exit to fire"
        assert "INFY" not in om._open_trades

    def test_buy_no_reversal_when_price_still_above_vwap(self):
        """BUY trade: price stays above VWAP → no reversal exit."""
        om, broker = _make_order_manager()
        _inject_open_buy(om, broker, entry_price=1500.0)

        result = om.check_reversal_exit("INFY", current_price=1510.0, vwap=1495.0)

        assert result is None


class TestReversalExitEdgeCases:

    def test_nan_vwap_skips_check(self):
        """NaN VWAP (e.g. daily candles) should not cause errors or spurious exits."""
        import math
        om, broker = _make_order_manager()
        _inject_open_sell(om, broker, entry_price=1000.0)

        result = om.check_reversal_exit("RELIANCE", current_price=1010.0, vwap=float("nan"))

        assert result is None

    def test_zero_vwap_skips_check(self):
        """Zero VWAP should be treated as unavailable."""
        om, broker = _make_order_manager()
        _inject_open_sell(om, broker, entry_price=1000.0)

        result = om.check_reversal_exit("RELIANCE", current_price=1010.0, vwap=0.0)

        assert result is None

    def test_no_open_trade_returns_none(self):
        """Symbol with no open trade should return None without error."""
        om, broker = _make_order_manager()

        result = om.check_reversal_exit("HDFCBANK", current_price=1600.0, vwap=1590.0)

        assert result is None

    def test_reversal_at_exactly_window_boundary_skips(self):
        """Trade entered exactly REVERSAL_WINDOW_SECS ago → window expired, no exit."""
        om, broker = _make_order_manager()
        boundary = datetime.now(IST) - timedelta(seconds=_REVERSAL_WINDOW_SECS + 1)
        _inject_open_sell(om, broker, entry_price=1000.0, opened_at=boundary)

        result = om.check_reversal_exit("RELIANCE", current_price=1015.0, vwap=1005.0)

        assert result is None
