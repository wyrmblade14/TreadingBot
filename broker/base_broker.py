"""
Abstract broker interface.

Both the Paper Broker (simulated) and the Live Kite Broker implement
this interface. This means the rest of the system — order manager,
portfolio, strategies — never needs to know whether it's talking to
a real exchange or a simulator.

To switch from paper trading to live trading, the only change needed is:
    broker = PaperBroker(capital=100_000)   # current
    broker = KiteBroker(api_key, token)     # when ready to go live

Everything else stays exactly the same.

Terminology:
  LTP  = Last Traded Price (the most recent price at which a stock traded)
  MIS  = Margin Intraday Square-off (Zerodha's intraday order product code)
  CNC  = Cash and Carry (delivery/positional trades — not used here)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class OrderType(str, Enum):
    MARKET = "MARKET"   # Fill immediately at best available price
    LIMIT  = "LIMIT"    # Fill only at the specified price or better


class OrderStatus(str, Enum):
    PENDING   = "PENDING"    # Placed but not yet acknowledged by exchange
    OPEN      = "OPEN"       # Acknowledged, waiting to fill
    COMPLETE  = "COMPLETE"   # Fully filled
    REJECTED  = "REJECTED"   # Exchange or broker rejected the order
    CANCELLED = "CANCELLED"  # Cancelled before fill


class TransactionType(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"


@dataclass
class Order:
    """Represents a single order submitted to the broker."""
    order_id:         str
    symbol:           str
    transaction_type: TransactionType
    quantity:         int
    order_type:       OrderType
    price:            float          # 0.0 for MARKET orders
    status:           OrderStatus    = OrderStatus.PENDING
    filled_price:     float          = 0.0
    filled_quantity:  int            = 0
    timestamp:        datetime       = field(default_factory=datetime.now)
    rejection_reason: str            = ""


@dataclass
class Position:
    """Represents an open position in the portfolio."""
    symbol:          str
    quantity:        int
    avg_price:       float          # Average purchase price
    current_price:   float          # Latest market price
    transaction_type: TransactionType = TransactionType.BUY

    @property
    def unrealised_pnl(self) -> float:
        """Profit or loss if position were closed right now."""
        if self.transaction_type == TransactionType.BUY:
            return (self.current_price - self.avg_price) * self.quantity
        else:
            return (self.avg_price - self.current_price) * self.quantity

    @property
    def market_value(self) -> float:
        """Current market value of the position."""
        return self.current_price * self.quantity


class BaseBroker(ABC):
    """
    Abstract broker interface. All broker implementations must provide
    these methods so the rest of the system can work with any broker.
    """

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        transaction_type: TransactionType,
        quantity: int,
        order_type: OrderType = OrderType.MARKET,
        price: float = 0.0,
    ) -> Order:
        """
        Place a new order.

        Args:
            symbol:           NSE symbol, e.g. "RELIANCE"
            transaction_type: BUY or SELL
            quantity:         Number of shares
            order_type:       MARKET or LIMIT
            price:            Required for LIMIT orders; ignored for MARKET

        Returns:
            An Order object. Check order.status to see if it was accepted.
        """
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a pending or open order.

        Returns:
            True if successfully cancelled, False otherwise.
        """
        ...

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[Order]:
        """Return the current state of an order by its ID."""
        ...

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Return all currently open positions."""
        ...

    @abstractmethod
    def get_ltp(self, symbol: str) -> float:
        """
        Return the Last Traded Price for a symbol.
        In paper mode this reads from the candle store.
        In live mode this calls the Kite Connect API.
        """
        ...

    @abstractmethod
    def get_cash_balance(self) -> float:
        """Return available cash balance."""
        ...

    @abstractmethod
    def square_off_all(self) -> list[Order]:
        """
        Close all open positions immediately at market price.
        Called at 3:15 PM for intraday square-off.
        Returns list of sell orders placed.
        """
        ...
