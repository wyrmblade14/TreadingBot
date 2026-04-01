"""
Portfolio tracker — maintains a view of your virtual account's state.

The portfolio reads from the broker (for positions and cash) and the
trade log (for realised P&L history) to give a unified picture of:
  - Current cash balance
  - Open positions and their unrealised P&L
  - Today's realised P&L
  - Total account value

This is what the Streamlit dashboard reads to display the home page.
"""

from __future__ import annotations

from dataclasses import dataclass

from broker.base_broker import BaseBroker, Position


@dataclass
class PortfolioSnapshot:
    """A point-in-time snapshot of the portfolio state."""
    cash_balance:     float
    positions:        list[Position]
    unrealised_pnl:   float
    day_pnl:          float
    portfolio_value:  float
    open_count:       int
    day_pnl_pct:      float


class Portfolio:
    """
    Wraps a broker instance to provide a higher-level portfolio view.
    Used by the dashboard and risk manager.
    """

    def __init__(self, broker: BaseBroker, initial_capital: float) -> None:
        self._broker          = broker
        self._initial_capital = initial_capital

    def snapshot(self) -> PortfolioSnapshot:
        """Return the current portfolio state."""
        positions       = self._broker.get_positions()
        cash            = self._broker.get_cash_balance()
        unrealised      = sum(p.unrealised_pnl for p in positions)
        positions_value = sum(p.market_value for p in positions)
        portfolio_value = cash + positions_value
        day_pnl         = portfolio_value - self._initial_capital
        day_pnl_pct     = (day_pnl / self._initial_capital * 100) if self._initial_capital else 0

        return PortfolioSnapshot(
            cash_balance=round(cash, 2),
            positions=positions,
            unrealised_pnl=round(unrealised, 2),
            day_pnl=round(day_pnl, 2),
            portfolio_value=round(portfolio_value, 2),
            open_count=len(positions),
            day_pnl_pct=round(day_pnl_pct, 2),
        )

    def get_position(self, symbol: str) -> Position | None:
        """Return the open position for a symbol, or None."""
        return next(
            (p for p in self._broker.get_positions() if p.symbol == symbol),
            None,
        )

    def is_flat(self) -> bool:
        """True if there are no open positions."""
        return len(self._broker.get_positions()) == 0
