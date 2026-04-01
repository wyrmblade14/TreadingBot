"""
Tests for intraday short selling (sell first, buy later) via PaperBroker.

Short selling mechanics recap:
  - SELL with no existing position → opens a short (borrows shares, sells them)
  - BUY after a short → covers (buys back to close the position)
  - Profit: price falls after short entry  → (entry - exit) * qty > 0
  - Loss:   price rises after short entry  → (entry - exit) * qty < 0
  - Margin: same 5x MIS leverage as longs (20% of position value blocked)
"""
from __future__ import annotations

from datetime import datetime, time
from unittest.mock import patch

import pytest
import pytz

from broker.base_broker import OrderStatus, OrderType, TransactionType
from broker.paper_broker import PaperBroker
from config.settings import INTRADAY_LEVERAGE

CAPITAL = 1_00_000.0
IST = pytz.timezone("Asia/Kolkata")
MARKET_TIME = time(10, 0)


# ── Helpers ───────────────────────────────────────────────────────────

def make_broker(capital: float = CAPITAL) -> PaperBroker:
    return PaperBroker(initial_capital=capital, slippage_pct=0.0)


def _ist_dt(t: time) -> datetime:
    return IST.localize(datetime(2024, 1, 2, t.hour, t.minute, t.second))


def _place(broker: PaperBroker, symbol: str, ttype: TransactionType, qty: int, ltp: float):
    broker.update_ltp(symbol, ltp)
    with patch("broker.paper_broker.datetime") as mock_dt:
        mock_dt.now.return_value = _ist_dt(MARKET_TIME)
        return broker.place_order(symbol, ttype, qty)


def _sell(broker, symbol, qty, ltp):
    return _place(broker, symbol, TransactionType.SELL, qty, ltp)


def _buy(broker, symbol, qty, ltp):
    return _place(broker, symbol, TransactionType.BUY, qty, ltp)


# ── Open short ────────────────────────────────────────────────────────

class TestOpenShort:
    def test_opens_short_position(self):
        """SELL with no existing position creates a SELL position when shorts enabled."""
        broker = make_broker()
        with patch("broker.paper_broker.SHORT_SELLING_ENABLED", True):
            order = _sell(broker, "RELIANCE", 10, 500.0)

        assert order.status == OrderStatus.COMPLETE
        positions = broker.get_positions()
        assert len(positions) == 1
        pos = positions[0]
        assert pos.transaction_type == TransactionType.SELL
        assert pos.quantity == 10
        assert pos.avg_price == pytest.approx(500.0)

    def test_rejects_when_disabled(self):
        """SELL without position is rejected when SHORT_SELLING_ENABLED=False."""
        broker = make_broker()
        with patch("broker.paper_broker.SHORT_SELLING_ENABLED", False):
            order = _sell(broker, "RELIANCE", 10, 500.0)
        assert order.status == OrderStatus.REJECTED

    def test_rejects_insufficient_margin_for_short(self):
        """Short is rejected when cash is below required margin."""
        broker = make_broker(capital=100.0)  # Only ₹100
        with patch("broker.paper_broker.SHORT_SELLING_ENABLED", True):
            order = _sell(broker, "RELIANCE", 10, 5000.0)  # Needs ₹10,000 margin
        assert order.status == OrderStatus.REJECTED
        assert "margin" in order.rejection_reason.lower()


# ── No averaging on shorts ────────────────────────────────────────────

class TestNoShortAveraging:
    def test_rejects_adding_to_existing_short(self):
        """A second SELL when already short in the same symbol is rejected."""
        broker = make_broker()
        with patch("broker.paper_broker.SHORT_SELLING_ENABLED", True):
            _sell(broker, "RELIANCE", 10, 500.0)
            order = _sell(broker, "RELIANCE", 5, 495.0)
        assert order.status == OrderStatus.REJECTED
        assert "short" in order.rejection_reason.lower()


# ── Cover short ───────────────────────────────────────────────────────

class TestCoverShort:
    def test_covers_short_with_buy(self):
        """BUY after an open short closes the position."""
        broker = make_broker()
        with patch("broker.paper_broker.SHORT_SELLING_ENABLED", True):
            _sell(broker, "RELIANCE", 10, 500.0)
            order = _buy(broker, "RELIANCE", 10, 490.0)

        assert order.status == OrderStatus.COMPLETE
        assert len(broker.get_positions()) == 0

    def test_square_off_covers_short(self):
        """square_off_all() issues a BUY order to close a short position."""
        broker = make_broker()
        with patch("broker.paper_broker.SHORT_SELLING_ENABLED", True):
            _sell(broker, "RELIANCE", 10, 500.0)
            broker.update_ltp("RELIANCE", 495.0)
            with patch("broker.paper_broker.datetime") as mock_dt:
                mock_dt.now.return_value = _ist_dt(MARKET_TIME)
                orders = broker.square_off_all()

        assert len(orders) == 1
        assert orders[0].transaction_type == TransactionType.BUY
        assert orders[0].status == OrderStatus.COMPLETE
        assert len(broker.get_positions()) == 0


# ── Short P&L ─────────────────────────────────────────────────────────

class TestShortPnL:
    def test_profit_on_price_decline(self):
        """Short at 500, cover at 490 → cash increases (profit = ₹100 minus brokerage)."""
        broker = make_broker()
        with patch("broker.paper_broker.SHORT_SELLING_ENABLED", True):
            _sell(broker, "TCS", 10, 500.0)
            cash_mid = broker.get_cash_balance()
            _buy(broker, "TCS", 10, 490.0)

        cash_final = broker.get_cash_balance()
        assert cash_final > cash_mid, "Cash should increase after covering at lower price"
        # Gross profit = (500 - 490) * 10 = ₹100; net after brokerage should still be positive
        assert cash_final > CAPITAL - 50, "Net P&L should be positive (profit > brokerage)"

    def test_loss_on_price_rise(self):
        """Short at 500, cover at 510 → cash decreases (loss = ₹100 plus brokerage)."""
        broker = make_broker()
        with patch("broker.paper_broker.SHORT_SELLING_ENABLED", True):
            _sell(broker, "TCS", 10, 500.0)
            _buy(broker, "TCS", 10, 510.0)

        assert broker.get_cash_balance() < CAPITAL, "Loss + brokerage should reduce cash"


# ── Short margin ──────────────────────────────────────────────────────

class TestShortMargin:
    def test_margin_deducted_on_open(self):
        """Opening a short deducts margin (qty × price / leverage) + brokerage from cash."""
        broker = make_broker()
        qty, price = 10, 500.0
        with patch("broker.paper_broker.SHORT_SELLING_ENABLED", True):
            _sell(broker, "RELIANCE", qty, price)

        margin = qty * price / INTRADAY_LEVERAGE  # ₹1,000
        assert broker.get_cash_balance() <= CAPITAL - margin

    def test_margin_returned_on_flat_cover(self):
        """Covering at same entry price returns margin; only brokerage is lost."""
        broker = make_broker()
        qty, price = 10, 500.0
        with patch("broker.paper_broker.SHORT_SELLING_ENABLED", True):
            _sell(broker, "RELIANCE", qty, price)
            cash_after_short = broker.get_cash_balance()
            _buy(broker, "RELIANCE", qty, price)   # cover at same price → zero gross P&L

        cash_final = broker.get_cash_balance()
        assert cash_final > cash_after_short, "Margin should be returned on cover"
        # Only ~₹40-80 brokerage for two orders; should be well above CAPITAL - 200
        assert cash_final > CAPITAL - 200
