"""
Unit tests for the Paper Broker.

We test:
  - Order fills with correct slippage
  - Brokerage deducted from cash
  - Rejection when insufficient cash
  - Rejection when trying to sell more than held
  - Rejection outside market hours
  - Position tracking (buy increases, sell decreases)
  - Square-off closes all positions
  - Portfolio value calculation
"""

from __future__ import annotations

from datetime import time
from unittest.mock import patch

import pytest

from broker.base_broker import OrderStatus, OrderType, TransactionType
from broker.paper_broker import PaperBroker

CAPITAL = 1_00_000.0


def make_broker(capital: float = CAPITAL) -> PaperBroker:
    broker = PaperBroker(initial_capital=capital, slippage_pct=0.0)  # Zero slippage for deterministic tests
    return broker


MARKET_TIME = time(10, 0)   # Well within market hours
CLOSED_TIME = time(8, 0)    # Before market open


class TestPaperBrokerOrders:

    def _buy(self, broker: PaperBroker, symbol: str = "RELIANCE", qty: int = 10, ltp: float = 500.0):
        broker.update_ltp(symbol, ltp)
        with patch("broker.paper_broker.datetime") as mock_dt:
            mock_dt.now.return_value = _ist_dt(MARKET_TIME)
            return broker.place_order(symbol, TransactionType.BUY, qty)

    def _sell(self, broker: PaperBroker, symbol: str = "RELIANCE", qty: int = 10, ltp: float = 510.0):
        broker.update_ltp(symbol, ltp)
        with patch("broker.paper_broker.datetime") as mock_dt:
            mock_dt.now.return_value = _ist_dt(MARKET_TIME)
            return broker.place_order(symbol, TransactionType.SELL, qty)

    def test_buy_order_completes(self):
        broker = make_broker()
        order = self._buy(broker)
        assert order.status == OrderStatus.COMPLETE
        assert order.filled_quantity == 10
        assert order.filled_price == pytest.approx(500.0, abs=0.01)

    def test_sell_order_completes(self):
        broker = make_broker()
        self._buy(broker)   # Buy first
        order = self._sell(broker)
        assert order.status == OrderStatus.COMPLETE
        assert order.filled_quantity == 10

    def test_cash_decreases_on_buy(self):
        broker = make_broker()
        initial_cash = broker.get_cash_balance()
        self._buy(broker, qty=10, ltp=500.0)
        # With 5x MIS leverage, only margin (10×500/5 = ₹1000) + brokerage is deducted
        from config.settings import INTRADAY_LEVERAGE
        margin = 10 * 500.0 / INTRADAY_LEVERAGE
        assert broker.get_cash_balance() < initial_cash - margin

    def test_cash_increases_on_sell(self):
        broker = make_broker()
        self._buy(broker, qty=10, ltp=500.0)
        cash_after_buy = broker.get_cash_balance()
        self._sell(broker, qty=10, ltp=510.0)
        assert broker.get_cash_balance() > cash_after_buy

    def test_brokerage_deducted_on_buy(self):
        broker = make_broker()
        self._buy(broker, qty=10, ltp=500.0)
        # With 5x leverage, margin = 10×500/5 = ₹1000; at least ₹20 brokerage on top
        from config.settings import INTRADAY_LEVERAGE
        margin = 10 * 500.0 / INTRADAY_LEVERAGE
        assert broker.get_cash_balance() <= CAPITAL - margin - 20

    def test_rejected_when_insufficient_cash(self):
        broker = make_broker(capital=100.0)   # Very small capital
        order = self._buy(broker, qty=100, ltp=500.0)  # Margin alone needs ₹10,000
        assert order.status == OrderStatus.REJECTED
        assert "Insufficient" in order.rejection_reason or "margin" in order.rejection_reason.lower()

    def test_rejected_when_overselling(self):
        broker = make_broker()
        self._buy(broker, qty=5, ltp=500.0)
        order = self._sell(broker, qty=10)   # Try to sell more than held
        assert order.status == OrderStatus.REJECTED
        assert "oversell" in order.rejection_reason.lower() or "Cannot sell" in order.rejection_reason

    def test_rejected_when_selling_without_position(self):
        broker = make_broker()
        with patch("broker.paper_broker.SHORT_SELLING_ENABLED", False):
            order = self._sell(broker, qty=5)
        assert order.status == OrderStatus.REJECTED

    def test_rejected_outside_market_hours(self):
        broker = make_broker()
        broker.update_ltp("RELIANCE", 500.0)
        with patch("broker.paper_broker.datetime") as mock_dt:
            mock_dt.now.return_value = _ist_dt(CLOSED_TIME)
            order = broker.place_order("RELIANCE", TransactionType.BUY, 10)
        assert order.status == OrderStatus.REJECTED
        assert "closed" in order.rejection_reason.lower()

    def test_rejected_when_no_ltp(self):
        broker = make_broker()
        # Don't call update_ltp — no price available
        with patch("broker.paper_broker.datetime") as mock_dt:
            mock_dt.now.return_value = _ist_dt(MARKET_TIME)
            order = broker.place_order("UNKNOWN", TransactionType.BUY, 10)
        assert order.status == OrderStatus.REJECTED


class TestPaperBrokerPositions:

    def _buy(self, broker: PaperBroker, symbol="RELIANCE", qty=10, ltp=500.0):
        broker.update_ltp(symbol, ltp)
        with patch("broker.paper_broker.datetime") as mock_dt:
            mock_dt.now.return_value = _ist_dt(MARKET_TIME)
            return broker.place_order(symbol, TransactionType.BUY, qty)

    def _sell(self, broker: PaperBroker, symbol="RELIANCE", qty=10, ltp=510.0):
        broker.update_ltp(symbol, ltp)
        with patch("broker.paper_broker.datetime") as mock_dt:
            mock_dt.now.return_value = _ist_dt(MARKET_TIME)
            return broker.place_order(symbol, TransactionType.SELL, qty)

    def test_position_created_on_buy(self):
        broker = make_broker()
        self._buy(broker)
        positions = broker.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "RELIANCE"
        assert positions[0].quantity == 10

    def test_position_removed_on_full_sell(self):
        broker = make_broker()
        self._buy(broker, qty=10)
        self._sell(broker, qty=10)
        assert len(broker.get_positions()) == 0

    def test_partial_sell_reduces_quantity(self):
        broker = make_broker()
        self._buy(broker, qty=10)
        self._sell(broker, qty=5)
        positions = broker.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == 5

    def test_multiple_buys_average_price(self):
        """Two buys at different prices → average price is correct."""
        broker = make_broker()
        self._buy(broker, qty=10, ltp=500.0)
        self._buy(broker, qty=10, ltp=510.0)
        pos = broker.get_positions()[0]
        assert pos.quantity == 20
        assert pos.avg_price == pytest.approx(505.0, abs=0.01)

    def test_ltp_update_reflects_in_position(self):
        broker = make_broker()
        self._buy(broker, qty=10, ltp=500.0)
        broker.update_ltp("RELIANCE", 520.0)
        pos = broker.get_positions()[0]
        assert pos.current_price == pytest.approx(520.0)

    def test_unrealised_pnl_positive_when_price_rises(self):
        broker = make_broker()
        self._buy(broker, qty=10, ltp=500.0)
        broker.update_ltp("RELIANCE", 510.0)
        assert broker.get_total_unrealised_pnl() == pytest.approx(100.0, abs=0.5)

    def test_unrealised_pnl_negative_when_price_falls(self):
        broker = make_broker()
        self._buy(broker, qty=10, ltp=500.0)
        broker.update_ltp("RELIANCE", 490.0)
        assert broker.get_total_unrealised_pnl() < 0


class TestPaperBrokerSquareOff:

    def _buy(self, broker: PaperBroker, symbol="RELIANCE", qty=10, ltp=500.0):
        broker.update_ltp(symbol, ltp)
        with patch("broker.paper_broker.datetime") as mock_dt:
            mock_dt.now.return_value = _ist_dt(MARKET_TIME)
            return broker.place_order(symbol, TransactionType.BUY, qty)

    def test_square_off_closes_all_positions(self):
        broker = make_broker()
        for sym, ltp in [("RELIANCE", 500), ("TCS", 3000), ("INFY", 1500)]:
            self._buy(broker, sym, 5, ltp)

        assert len(broker.get_positions()) == 3

        # Square off during market hours
        with patch("broker.paper_broker.datetime") as mock_dt:
            mock_dt.now.return_value = _ist_dt(MARKET_TIME)
            orders = broker.square_off_all()

        assert len(orders) == 3
        assert len(broker.get_positions()) == 0

    def test_square_off_returns_orders(self):
        broker = make_broker()
        self._buy(broker, "RELIANCE", 10, 500)
        with patch("broker.paper_broker.datetime") as mock_dt:
            mock_dt.now.return_value = _ist_dt(MARKET_TIME)
            orders = broker.square_off_all()
        assert len(orders) == 1
        assert orders[0].status == OrderStatus.COMPLETE


class TestPaperBrokerPortfolio:

    def _buy(self, broker: PaperBroker, symbol="RELIANCE", qty=10, ltp=500.0):
        broker.update_ltp(symbol, ltp)
        with patch("broker.paper_broker.datetime") as mock_dt:
            mock_dt.now.return_value = _ist_dt(MARKET_TIME)
            return broker.place_order(symbol, TransactionType.BUY, qty)

    def test_portfolio_value_includes_positions(self):
        broker = make_broker()
        self._buy(broker, qty=10, ltp=500.0)
        broker.update_ltp("RELIANCE", 510.0)
        # Portfolio value = cash + 10 × 510 = cash + 5100
        value = broker.get_portfolio_value()
        assert value > CAPITAL - 5100   # Cash lost ~5000, gained ~5100 in position

    def test_summary_returns_dict(self):
        broker = make_broker()
        summary = broker.get_summary()
        assert "cash" in summary
        assert "portfolio_value" in summary
        assert "day_pnl" in summary
        assert "day_pnl_pct" in summary
        assert "open_positions" in summary
        assert "total_brokerage" in summary

    def test_initial_portfolio_value_equals_capital(self):
        broker = make_broker(CAPITAL)
        assert broker.get_portfolio_value() == pytest.approx(CAPITAL)

    def test_day_pnl_zero_at_start(self):
        broker = make_broker(CAPITAL)
        assert broker.get_day_pnl() == pytest.approx(0.0)


# ── Helper ────────────────────────────────────────────────────────────

def _ist_dt(t: time):
    """Create a timezone-aware IST datetime with the given time."""
    from datetime import datetime
    import pytz
    ist = pytz.timezone("Asia/Kolkata")
    return ist.localize(datetime(2024, 1, 2, t.hour, t.minute, t.second))


# ── Partial Fill Simulation Tests ────────────────────────────────────

from broker.paper_broker import _simulate_fill
from unittest.mock import patch as _patch
import broker.paper_broker as _pb_module


class TestSimulateFill:
    """Tests for the _simulate_fill() helper function."""

    def test_small_order_single_price_buy(self):
        """Orders <= threshold always fill at a single price (standard slippage)."""
        with _patch("broker.paper_broker.PARTIAL_FILL_ENABLED", True), \
             _patch("broker.paper_broker.PARTIAL_FILL_THRESHOLD", 50), \
             _patch("broker.paper_broker.random") as mock_rnd:
            mock_rnd.uniform.return_value = 0.001   # 0.1% slippage
            mock_rnd.random.return_value  = 0.0     # would trigger partial if threshold exceeded

            price = _simulate_fill(TransactionType.BUY, 10, 1000.0, 0.001)
            assert price == pytest.approx(1001.0, rel=1e-4)
            # random.random() should NOT have been called (small order bypasses check)
            mock_rnd.random.assert_not_called()

    def test_small_order_single_price_sell(self):
        with _patch("broker.paper_broker.PARTIAL_FILL_ENABLED", True), \
             _patch("broker.paper_broker.PARTIAL_FILL_THRESHOLD", 50), \
             _patch("broker.paper_broker.random") as mock_rnd:
            mock_rnd.uniform.return_value = 0.001

            price = _simulate_fill(TransactionType.SELL, 10, 1000.0, 0.001)
            assert price == pytest.approx(999.0, rel=1e-4)

    def test_large_order_two_lot_fill_buy(self):
        """Large orders triggering 2-lot fill should produce a worse (higher) buy price."""
        with _patch("broker.paper_broker.PARTIAL_FILL_ENABLED", True), \
             _patch("broker.paper_broker.PARTIAL_FILL_THRESHOLD", 50), \
             _patch("broker.paper_broker.PARTIAL_FILL_PROBABILITY", 1.0):
            # Force 2-lot fill: both lots fill slightly above LTP for a BUY
            price = _simulate_fill(TransactionType.BUY, 100, 1000.0, 0.002)
            assert price > 1000.0   # must be above LTP for a buy

    def test_large_order_two_lot_fill_sell(self):
        """Large orders triggering 2-lot fill should produce a worse (lower) sell price."""
        with _patch("broker.paper_broker.PARTIAL_FILL_ENABLED", True), \
             _patch("broker.paper_broker.PARTIAL_FILL_THRESHOLD", 50), \
             _patch("broker.paper_broker.PARTIAL_FILL_PROBABILITY", 1.0):
            price = _simulate_fill(TransactionType.SELL, 100, 1000.0, 0.002)
            assert price < 1000.0   # must be below LTP for a sell

    def test_disabled_partial_fill_uses_single_price(self):
        """When PARTIAL_FILL_ENABLED=False, large orders get the same single-price fill."""
        with _patch("broker.paper_broker.PARTIAL_FILL_ENABLED", False), \
             _patch("broker.paper_broker.PARTIAL_FILL_THRESHOLD", 50), \
             _patch("broker.paper_broker.random") as mock_rnd:
            mock_rnd.uniform.return_value = 0.001
            price = _simulate_fill(TransactionType.BUY, 200, 1000.0, 0.001)
            assert price == pytest.approx(1001.0, rel=1e-4)
            mock_rnd.random.assert_not_called()

    def test_two_lot_fill_always_above_ltp_for_buy(self):
        """The 2-lot sweep for a BUY must always fill above LTP (market moves against you)."""
        ltp = 1000.0
        # Run 20 times to confirm it holds across random draws
        with _patch("broker.paper_broker.PARTIAL_FILL_ENABLED", True), \
             _patch("broker.paper_broker.PARTIAL_FILL_THRESHOLD", 50), \
             _patch("broker.paper_broker.PARTIAL_FILL_PROBABILITY", 1.0):
            for _ in range(20):
                price = _simulate_fill(TransactionType.BUY, 100, ltp, 0.002)
                assert price > ltp, f"2-lot BUY fill {price} should be above LTP {ltp}"

    def test_two_lot_fill_always_below_ltp_for_sell(self):
        """The 2-lot sweep for a SELL must always fill below LTP."""
        ltp = 1000.0
        with _patch("broker.paper_broker.PARTIAL_FILL_ENABLED", True), \
             _patch("broker.paper_broker.PARTIAL_FILL_THRESHOLD", 50), \
             _patch("broker.paper_broker.PARTIAL_FILL_PROBABILITY", 1.0):
            for _ in range(20):
                price = _simulate_fill(TransactionType.SELL, 100, ltp, 0.002)
                assert price < ltp, f"2-lot SELL fill {price} should be below LTP {ltp}"


class TestPaperBrokerPartialFill:
    """Integration: partial fill affects the order's filled_price."""

    def test_large_order_fill_price_above_ltp_for_buy(self):
        """With 2-lot fill forced, BUY filled_price must be > LTP."""
        broker = PaperBroker(initial_capital=5_00_000.0, slippage_pct=0.001)
        broker.update_ltp("RELIANCE", 2500.0)

        with patch("broker.paper_broker.datetime") as mock_dt, \
             _patch("broker.paper_broker.PARTIAL_FILL_ENABLED", True), \
             _patch("broker.paper_broker.PARTIAL_FILL_THRESHOLD", 50), \
             _patch("broker.paper_broker.PARTIAL_FILL_PROBABILITY", 1.0):
            mock_dt.now.return_value = _ist_dt(time(10, 0))
            order = broker.place_order("RELIANCE", TransactionType.BUY, 100)

        assert order.status == OrderStatus.COMPLETE
        assert order.filled_price > 2500.0

    def test_small_order_still_fills_at_ltp_level(self):
        """Small orders should fill close to LTP (single slippage draw)."""
        broker = PaperBroker(initial_capital=5_00_000.0, slippage_pct=0.001)
        broker.update_ltp("TCS", 3500.0)

        with patch("broker.paper_broker.datetime") as mock_dt:
            mock_dt.now.return_value = _ist_dt(time(10, 0))
            order = broker.place_order("TCS", TransactionType.BUY, 5)

        assert order.status == OrderStatus.COMPLETE
        # With 0.1% max slippage: fill must be within 0.2% of LTP
        assert 3500.0 <= order.filled_price <= 3500.0 * 1.002
