"""
Paper Trading Broker — simulates real Zerodha trading without real money.

What is paper trading?
  Paper trading means executing trades on paper (or in a simulation) as if
  they were real, but without any actual money changing hands. It lets you:
    - Test your strategy on live market conditions
    - Build confidence before committing real capital
    - Find bugs in your bot that only appear with real order flow

  The name comes from the old practice of writing trades in a notebook
  (on paper) and tracking hypothetical P&L.

Why simulate costs?
  Many beginners paper trade without accounting for brokerage fees and
  taxes. Then when they go live, their "profitable" strategy breaks even
  or loses money because costs eat their gains.

  This simulator deducts REAL Zerodha costs so your paper P&L accurately
  reflects what you'd make with actual money.

Partial fill simulation:
  Large orders (> 50 shares) have a 25% chance of being filled in two lots
  at progressively worse prices — simulating a sweep through the order book.
  This is realistic for NIFTY50 stocks and gives more accurate P&L estimates
  for position sizes above ~₹1 lakh (50 shares × ~₹2000/share).

Costs simulated (all accurate as of 2024):
  ┌─────────────────────────────────────────────────────────────────┐
  │ Cost Type              │ Rate                                   │
  ├─────────────────────────────────────────────────────────────────┤
  │ Brokerage              │ ₹20 flat per order (both buy & sell)  │
  │ STT (Securities Tax)   │ 0.025% on sell-side turnover           │
  │ Exchange charges (NSE) │ 0.00325% on total turnover             │
  │ GST                    │ 18% on (brokerage + exchange charges)  │
  │ SEBI charges           │ ₹10 per ₹1 crore of turnover          │
  │ Stamp duty             │ 0.003% on buy-side turnover            │
  └─────────────────────────────────────────────────────────────────┘

Slippage:
  In real markets, your order never fills at the exact last-traded price.
  For BUY orders: you pay slightly more (sellers demand a premium)
  For SELL orders: you receive slightly less (buyers bid slightly lower)
  We simulate 0.1% slippage, which is conservative for NIFTY50 stocks.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime
from typing import Optional

from loguru import logger

from broker.base_broker import (
    BaseBroker,
    Order,
    OrderStatus,
    OrderType,
    Position,
    TransactionType,
)
from config.settings import (
    BROKERAGE_PER_ORDER,
    EXCHANGE_TRANSACTION_CHARGE,
    GST_RATE,
    INTRADAY_LEVERAGE,
    MARKET_CLOSE,
    MARKET_OPEN,
    PARTIAL_FILL_ENABLED,
    PARTIAL_FILL_PROBABILITY,
    PARTIAL_FILL_THRESHOLD,
    SEBI_CHARGES_PER_CRORE,
    SHORT_SELLING_ENABLED,
    SLIPPAGE_PCT,
    STAMP_DUTY_BUY,
    STT_INTRADAY_SELL,
    IST,
)


def _calculate_brokerage(
    transaction_type: TransactionType,
    quantity: int,
    fill_price: float,
) -> float:
    """
    Calculate total transaction cost for one order.

    Returns the total cost in INR (this amount is deducted from cash).
    """
    turnover = quantity * fill_price

    brokerage    = BROKERAGE_PER_ORDER
    exchange_chg = turnover * EXCHANGE_TRANSACTION_CHARGE
    gst          = (brokerage + exchange_chg) * GST_RATE
    sebi         = (turnover / 1_00_00_000) * SEBI_CHARGES_PER_CRORE  # per crore

    if transaction_type == TransactionType.BUY:
        stamp      = turnover * STAMP_DUTY_BUY
        stt        = 0.0
    else:
        stamp      = 0.0
        stt        = turnover * STT_INTRADAY_SELL

    total = brokerage + exchange_chg + gst + sebi + stamp + stt

    logger.debug(
        f"Brokerage breakdown | {transaction_type.value} {quantity}@{fill_price:.2f} "
        f"turnover={turnover:.0f} | brokerage={brokerage:.2f} "
        f"stt={stt:.4f} exchange={exchange_chg:.4f} gst={gst:.4f} "
        f"sebi={sebi:.4f} stamp={stamp:.4f} | total={total:.2f}"
    )
    return round(total, 2)


def _simulate_fill(
    transaction_type: TransactionType,
    quantity: int,
    ltp: float,
    slippage_pct: float,
) -> float:
    """
    Compute the weighted average fill price for a market order.

    What is a partial fill / market impact?
      When you place a large order (e.g., buy 200 shares), the exchange's
      order book may not have enough sellers at the current price to fill
      your entire order in one go. Instead, it matches your order against
      multiple sellers at progressively higher prices. The result:
        - Lot 1 (majority): fills at LTP + small slippage
        - Lot 2 (remainder): fills at LTP + larger slippage
      Your average fill price is worse than if the whole order filled at once.

    For small orders (≤ PARTIAL_FILL_THRESHOLD): standard single-price fill.
    For large orders: 25% chance of 2-lot sweep with worse average price.

    Args:
        transaction_type: BUY (fills higher) or SELL (fills lower)
        quantity:         Number of shares
        ltp:              Last traded price
        slippage_pct:     Maximum base slippage (0.1% default)

    Returns:
        Weighted average fill price (float).
    """
    is_buy = transaction_type == TransactionType.BUY

    if (
        PARTIAL_FILL_ENABLED
        and quantity > PARTIAL_FILL_THRESHOLD
        and random.random() < PARTIAL_FILL_PROBABILITY
    ):
        # Two-lot sweep: majority fills at base price, remainder at worse price.
        # lot1_pct is the fraction filled in the first lot (60–80%).
        lot1_pct = random.uniform(0.60, 0.80)
        lot1_qty = max(1, int(quantity * lot1_pct))
        lot2_qty = quantity - lot1_qty

        slip1 = random.uniform(0.0, slippage_pct)
        slip2 = random.uniform(slippage_pct, slippage_pct * 2.5)  # worse fill

        if is_buy:
            p1 = ltp * (1 + slip1)
            p2 = ltp * (1 + slip2)
        else:
            p1 = ltp * (1 - slip1)
            p2 = ltp * (1 - slip2)

        avg_price = (p1 * lot1_qty + p2 * lot2_qty) / quantity
        impact_pct = abs(avg_price - ltp) / ltp * 100

        logger.debug(
            f"2-lot fill | {lot1_qty}@{p1:.2f} + {lot2_qty}@{p2:.2f} "
            f"-> avg {avg_price:.2f} (LTP {ltp:.2f}, impact {impact_pct:.3f}%)"
        )
        return round(avg_price, 2)

    # Standard single-price fill
    slippage = random.uniform(0.0, slippage_pct)
    if is_buy:
        return round(ltp * (1 + slippage), 2)
    else:
        return round(ltp * (1 - slippage), 2)


class PaperBroker(BaseBroker):
    """
    Simulates a Zerodha intraday brokerage account.

    Args:
        initial_capital: Starting virtual cash balance (default ₹1,00,000)
        slippage_pct:    Market order slippage (default 0.1%)
    """

    def __init__(
        self,
        initial_capital: float = 1_00_000.0,
        slippage_pct: float = SLIPPAGE_PCT,
        replay_mode: bool = False,
    ) -> None:
        self._cash: float        = initial_capital
        self._slippage           = slippage_pct
        self._replay_mode        = replay_mode   # True → skip market-hours check (for replay/backtest)
        self._positions: dict[str, Position]  = {}   # symbol → Position
        self._orders:    dict[str, Order]     = {}   # order_id → Order
        self._ltp_store: dict[str, float]     = {}   # symbol → last price (set externally)

        # Track all costs for reporting
        self._total_brokerage: float = 0.0
        self._initial_capital        = initial_capital

        logger.info(
            f"PaperBroker initialised | capital=₹{initial_capital:,.0f} "
            f"| leverage={INTRADAY_LEVERAGE}x MIS"
            + (" | replay_mode=ON" if replay_mode else "")
        )

    # ── Price feed ────────────────────────────────────────────────────

    def update_ltp(self, symbol: str, price: float) -> None:
        """
        Update the latest price for a symbol.

        Called by the data feed (market_feed.py) whenever a new candle
        completes. Also used to update unrealised P&L on open positions.
        """
        self._ltp_store[symbol] = price
        if symbol in self._positions:
            self._positions[symbol].current_price = price

    def get_ltp(self, symbol: str) -> float:
        """Return the last known price for a symbol."""
        price = self._ltp_store.get(symbol, 0.0)
        if price == 0.0:
            logger.warning(f"PaperBroker: No LTP available for {symbol}")
        return price

    # ── Order placement ───────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        transaction_type: TransactionType,
        quantity: int,
        order_type: OrderType = OrderType.MARKET,
        price: float = 0.0,
    ) -> Order:
        """
        Simulate placing an order. Applies slippage and deducts costs.

        Market orders fill instantly at LTP ± slippage.
        Limit orders only fill if LTP meets the limit price.
        """
        order_id = str(uuid.uuid4())[:8]
        now = datetime.now(IST)

        # ── Market hours check (skipped in replay mode) ──────────────
        current_time = now.time()
        if not self._replay_mode and not (MARKET_OPEN <= current_time <= MARKET_CLOSE):
            order = Order(
                order_id=order_id,
                symbol=symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                order_type=order_type,
                price=price,
                status=OrderStatus.REJECTED,
                rejection_reason=f"Market is closed at {current_time}. "
                                  f"Hours: {MARKET_OPEN}–{MARKET_CLOSE} IST",
            )
            self._orders[order_id] = order
            logger.warning(f"Order REJECTED (market closed): {symbol} {transaction_type.value} {quantity}")
            return order

        # ── Get fill price ───────────────────────────────────────────
        ltp = self.get_ltp(symbol)
        if ltp == 0.0:
            order = Order(
                order_id=order_id, symbol=symbol,
                transaction_type=transaction_type, quantity=quantity,
                order_type=order_type, price=price,
                status=OrderStatus.REJECTED,
                rejection_reason=f"No LTP available for {symbol}",
            )
            self._orders[order_id] = order
            return order

        if order_type == OrderType.MARKET:
            # Apply slippage and optional partial-fill market impact
            fill_price = _simulate_fill(transaction_type, quantity, ltp, self._slippage)
        else:
            # Limit order: only fill if price condition is met
            if transaction_type == TransactionType.BUY and ltp <= price:
                fill_price = price
            elif transaction_type == TransactionType.SELL and ltp >= price:
                fill_price = price
            else:
                # Limit not yet met — order stays OPEN (pending fill)
                order = Order(
                    order_id=order_id, symbol=symbol,
                    transaction_type=transaction_type, quantity=quantity,
                    order_type=order_type, price=price,
                    status=OrderStatus.OPEN,
                )
                self._orders[order_id] = order
                logger.debug(f"Limit order pending: {symbol} {transaction_type.value} {quantity}@{price}")
                return order

        # ── Detect trade intent before branching ─────────────────────
        # Capture before any _apply_* call mutates self._positions.
        existing_pos     = self._positions.get(symbol)
        is_opening_short = (
            transaction_type == TransactionType.SELL
            and existing_pos is None
            and SHORT_SELLING_ENABLED
        )
        is_covering_short = (
            transaction_type == TransactionType.BUY
            and existing_pos is not None
            and existing_pos.transaction_type == TransactionType.SELL
        )

        # ── Funds check (MIS leverage: only margin required) ─────────
        # Zerodha MIS gives 5x leverage — you only need to put up 20% margin.
        # E.g., to buy ₹50,000 worth of stock you only need ₹10,000 in your account.
        # Covering a short returns margin instead of deducting it — skip the check.
        if transaction_type == TransactionType.BUY and not is_covering_short:
            brokerage_cost = _calculate_brokerage(transaction_type, quantity, fill_price)
            margin_required = quantity * fill_price / INTRADAY_LEVERAGE + brokerage_cost
            if margin_required > self._cash:
                order = Order(
                    order_id=order_id, symbol=symbol,
                    transaction_type=transaction_type, quantity=quantity,
                    order_type=order_type, price=price,
                    status=OrderStatus.REJECTED,
                    rejection_reason=(
                        f"Insufficient margin. Need ₹{margin_required:.0f} "
                        f"(position ₹{quantity*fill_price:.0f} / {INTRADAY_LEVERAGE}x leverage), "
                        f"have ₹{self._cash:.0f}"
                    ),
                )
                self._orders[order_id] = order
                logger.warning(
                    f"Order REJECTED (insufficient margin): {symbol} "
                    f"need ₹{margin_required:.0f} (5x MIS)"
                )
                return order

        # ── Sell / short validation ───────────────────────────────────
        if transaction_type == TransactionType.SELL:
            if is_opening_short:
                # Opening a new short: same margin requirement as going long
                brokerage_cost = _calculate_brokerage(transaction_type, quantity, fill_price)
                margin_required = quantity * fill_price / INTRADAY_LEVERAGE + brokerage_cost
                if margin_required > self._cash:
                    order = Order(
                        order_id=order_id, symbol=symbol,
                        transaction_type=transaction_type, quantity=quantity,
                        order_type=order_type, price=price,
                        status=OrderStatus.REJECTED,
                        rejection_reason=(
                            f"Insufficient margin for short. Need ₹{margin_required:.0f} "
                            f"(position ₹{quantity*fill_price:.0f} / {INTRADAY_LEVERAGE}x leverage), "
                            f"have ₹{self._cash:.0f}"
                        ),
                    )
                    self._orders[order_id] = order
                    logger.warning(
                        f"Order REJECTED (insufficient margin for short): {symbol} "
                        f"need ₹{margin_required:.0f}"
                    )
                    return order
            elif existing_pos is not None and existing_pos.transaction_type == TransactionType.SELL:
                # Already short — no averaging down allowed (Rule #9 catches this first)
                order = Order(
                    order_id=order_id, symbol=symbol,
                    transaction_type=transaction_type, quantity=quantity,
                    order_type=order_type, price=price,
                    status=OrderStatus.REJECTED,
                    rejection_reason=(
                        f"Cannot add to existing short position in {symbol}. "
                        f"Close the existing short first."
                    ),
                )
                self._orders[order_id] = order
                logger.warning(f"Order REJECTED (short averaging): {symbol}")
                return order
            else:
                # Closing an existing long: validate sufficient quantity held
                held = existing_pos.quantity if existing_pos else 0
                if existing_pos is None or existing_pos.quantity < quantity:
                    order = Order(
                        order_id=order_id, symbol=symbol,
                        transaction_type=transaction_type, quantity=quantity,
                        order_type=order_type, price=price,
                        status=OrderStatus.REJECTED,
                        rejection_reason=f"Cannot sell {quantity} shares of {symbol}; holding {held}",
                    )
                    self._orders[order_id] = order
                    logger.warning(f"Order REJECTED (oversell): {symbol} hold={held} sell={quantity}")
                    return order

        # ── Execute the order ────────────────────────────────────────
        brokerage = _calculate_brokerage(transaction_type, quantity, fill_price)
        self._total_brokerage += brokerage

        if is_covering_short:
            # Covering short: return blocked margin + realised P&L (profit if price fell)
            avg_entry = existing_pos.avg_price
            realised_pnl = (avg_entry - fill_price) * quantity
            margin_returned = quantity * avg_entry / INTRADAY_LEVERAGE
            self._cash += margin_returned + realised_pnl - brokerage
            self._apply_buy(symbol, quantity, fill_price)
        elif transaction_type == TransactionType.BUY:
            # Opening or adding to a long: block margin
            margin = quantity * fill_price / INTRADAY_LEVERAGE
            self._cash -= (margin + brokerage)
            self._apply_buy(symbol, quantity, fill_price)
        elif is_opening_short:
            # Opening a new short: block margin (same as going long)
            margin = quantity * fill_price / INTRADAY_LEVERAGE
            self._cash -= (margin + brokerage)
            self._apply_sell(symbol, quantity, fill_price)
        else:
            # Closing an existing long: return margin + realised P&L
            avg_entry = existing_pos.avg_price
            realised_pnl = (fill_price - avg_entry) * quantity
            margin_returned = quantity * avg_entry / INTRADAY_LEVERAGE
            self._cash += margin_returned + realised_pnl - brokerage
            self._apply_sell(symbol, quantity, fill_price)

        order = Order(
            order_id=order_id, symbol=symbol,
            transaction_type=transaction_type, quantity=quantity,
            order_type=order_type, price=fill_price,
            status=OrderStatus.COMPLETE,
            filled_price=fill_price, filled_quantity=quantity,
            timestamp=now,
        )
        self._orders[order_id] = order
        logger.info(
            f"Order FILLED | {transaction_type.value} {quantity} {symbol} "
            f"@ ₹{fill_price:.2f} | brokerage=₹{brokerage:.2f} | cash=₹{self._cash:,.0f}"
        )
        return order

    def _apply_buy(self, symbol: str, quantity: int, fill_price: float) -> None:
        """Update positions after a buy fill."""
        if symbol in self._positions:
            pos = self._positions[symbol]
            if pos.transaction_type == TransactionType.SELL:
                # Covering a short position — reduce its quantity
                pos.quantity -= quantity
                if pos.quantity == 0:
                    del self._positions[symbol]
            else:
                # Adding to an existing long — weighted average price
                total_qty   = pos.quantity + quantity
                avg_price   = (pos.avg_price * pos.quantity + fill_price * quantity) / total_qty
                pos.quantity  = total_qty
                pos.avg_price = round(avg_price, 4)
        else:
            # Opening a new long position
            self._positions[symbol] = Position(
                symbol=symbol,
                quantity=quantity,
                avg_price=fill_price,
                current_price=fill_price,
                transaction_type=TransactionType.BUY,
            )

    def _apply_sell(self, symbol: str, quantity: int, fill_price: float) -> None:
        """Update positions after a sell fill."""
        if symbol not in self._positions:
            # Opening a new short position
            self._positions[symbol] = Position(
                symbol=symbol,
                quantity=quantity,
                avg_price=fill_price,
                current_price=fill_price,
                transaction_type=TransactionType.SELL,
            )
        else:
            # Closing (reducing) an existing long position
            pos = self._positions[symbol]
            pos.quantity -= quantity
            if pos.quantity == 0:
                del self._positions[symbol]

    # ── Other interface methods ───────────────────────────────────────

    def cancel_order(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order and order.status == OrderStatus.OPEN:
            order.status = OrderStatus.CANCELLED
            logger.info(f"Order {order_id} cancelled")
            return True
        return False

    def get_order(self, order_id: str) -> Optional[Order]:
        return self._orders.get(order_id)

    def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    def get_cash_balance(self) -> float:
        return self._cash

    def square_off_all(self) -> list[Order]:
        """
        Close all open positions at current market price.
        Called automatically at 3:15 PM by the scheduler.
        """
        orders = []
        for symbol, pos in list(self._positions.items()):
            # Short positions are closed by buying; long positions by selling
            close_type = (
                TransactionType.BUY
                if pos.transaction_type == TransactionType.SELL
                else TransactionType.SELL
            )
            action_str = "buying to cover" if close_type == TransactionType.BUY else "selling"
            logger.info(f"Square-off: {action_str} {pos.quantity} × {symbol}")
            order = self.place_order(
                symbol=symbol,
                transaction_type=close_type,
                quantity=pos.quantity,
                order_type=OrderType.MARKET,
            )
            orders.append(order)
        return orders

    # ── Portfolio summary helpers ─────────────────────────────────────

    def get_portfolio_value(self) -> float:
        """
        Total value = cash + (margin blocked + unrealised P&L) for each open position.

        With MIS leverage, only margin (position_value / leverage) was deducted from cash
        on entry. Portfolio value reflects that margin plus any unrealised gain/loss.
        """
        positions_value = sum(
            p.quantity * p.avg_price / INTRADAY_LEVERAGE + p.unrealised_pnl
            for p in self._positions.values()
        )
        return self._cash + positions_value

    def get_total_unrealised_pnl(self) -> float:
        """Sum of unrealised P&L across all open positions."""
        return sum(p.unrealised_pnl for p in self._positions.values())

    def get_day_pnl(self) -> float:
        """
        Approximate day P&L = (current portfolio value) − initial_capital.
        Includes both realised (closed trades) and unrealised (open positions).
        """
        return self.get_portfolio_value() - self._initial_capital

    def get_summary(self) -> dict:
        """Return a summary dict for the dashboard."""
        return {
            "cash":              round(self._cash, 2),
            "portfolio_value":   round(self.get_portfolio_value(), 2),
            "day_pnl":           round(self.get_day_pnl(), 2),
            "day_pnl_pct":       round(self.get_day_pnl() / self._initial_capital * 100, 2),
            "unrealised_pnl":    round(self.get_total_unrealised_pnl(), 2),
            "open_positions":    len(self._positions),
            "total_brokerage":   round(self._total_brokerage, 2),
            "total_orders":      len(self._orders),
        }
