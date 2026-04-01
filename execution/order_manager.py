"""
Order Manager — the bridge between strategies and the broker.

The Order Manager takes an approved Signal from the Risk Manager and:
  1. Places the entry order with the broker
  2. Monitors the open position for stop-loss and target hits
  3. Handles automatic square-off at 3:15 PM
  4. Logs every entry and exit to the trade log

It's the operational heart of the bot — translating strategic decisions
into actual order actions.

Position monitoring:
  After entering a trade, on every new candle the bot calls
  check_exits() to see if any open positions have hit their
  stop-loss or target. This works like a "software GTT order"
  (Good Till Triggered) for the paper broker.

  In live mode, Zerodha supports real GTT orders — the plan for
  Phase 6 is to place actual GTT orders on Kite Connect so that
  positions exit even if the bot temporarily disconnects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from loguru import logger

from broker.base_broker import BaseBroker, OrderType, TransactionType
from config.settings import (
    IST, SQUAREOFF_TIME,
    FORCE_EXIT_ENABLED, FORCE_EXIT_TIME,
    TRAIL_STOP_ENABLED, TRAIL_BREAKEVEN_ATR, TRAIL_START_ATR, TRAIL_DISTANCE_ATR,
)
from execution.trade_log import TradeLogger
from strategies.base_strategy import Action, Signal


@dataclass
class OpenTrade:
    """
    Tracks a live trade from entry to exit.

    Trailing stop fields:
        atr         — the ATR at entry, back-calculated from (entry_price - stop_loss) / 1.5.
                      Used to measure profit milestones for the trailing stop.
        trail_phase — 0 = initial fixed stop
                      1 = stop moved to breakeven (profit hit 1×ATR)
                      2 = actively trailing (profit hit 2×ATR)
    """
    trade_log_id:   int
    symbol:         str
    action:         Action
    quantity:       int
    entry_price:    float
    stop_loss:      float
    target:         float
    strategy:       str
    entry_order_id: str
    opened_at:      datetime       = field(default_factory=lambda: datetime.now(IST))
    exit_price:     Optional[float] = None
    exit_reason:    str            = ""
    atr:            float          = 0.0   # ATR at entry — drives trailing stop milestones
    trail_phase:    int            = 0     # 0=fixed, 1=breakeven, 2=trailing


class OrderManager:
    """
    Manages the full lifecycle of trades: entry → monitoring → exit.

    Args:
        broker:       The broker to place orders with (paper or live)
        trade_logger: For persisting trades to SQLite
        trading_mode: "paper" or "live" (for trade log labelling)
    """

    def __init__(
        self,
        broker: BaseBroker,
        trade_logger: TradeLogger,
        trading_mode: str = "paper",
    ) -> None:
        self._broker       = broker
        self._log          = trade_logger
        self._mode         = trading_mode
        self._open_trades: dict[str, OpenTrade] = {}  # symbol → OpenTrade

    def execute_signal(self, signal: Signal) -> bool:
        """
        Place an entry order for an approved signal.

        Args:
            signal: A Risk Manager-approved Signal with quantity filled in.

        Returns:
            True if order was placed and filled successfully, False otherwise.
        """
        if signal.action == Action.HOLD:
            return False

        if signal.quantity <= 0:
            logger.warning(f"OrderManager: Signal for {signal.symbol} has qty=0, skipping.")
            return False

        transaction = (
            TransactionType.BUY if signal.action == Action.BUY else TransactionType.SELL
        )

        logger.info(
            f"OrderManager: Placing {signal.action.value} order | "
            f"{signal.quantity}×{signal.symbol} @ ~₹{signal.entry_price:.2f}"
        )

        order = self._broker.place_order(
            symbol=signal.symbol,
            transaction_type=transaction,
            quantity=signal.quantity,
            order_type=OrderType.MARKET,
        )

        if order.status.value != "COMPLETE":
            logger.warning(
                f"OrderManager: Entry order not filled | {signal.symbol} | "
                f"status={order.status} reason={order.rejection_reason}"
            )
            return False

        # Log the entry to the database
        trade_id = self._log.record_entry(
            symbol=signal.symbol,
            action=signal.action.value,
            quantity=signal.quantity,
            entry_price=order.filled_price,
            stop_loss=signal.stop_loss,
            target=signal.target,
            strategy=signal.strategy,
            reason=signal.reason,
            order_id=order.order_id,
            trading_mode=self._mode,
        )

        # Back-calculate ATR from SL distance: all strategies use SL = entry ± 1.5×ATR
        # so ATR = |entry - stop_loss| / 1.5. Fallback to 0.5% of price if somehow zero.
        sl_distance = abs(order.filled_price - signal.stop_loss)
        entry_atr   = sl_distance / 1.5 if sl_distance > 0 else order.filled_price * 0.005

        self._open_trades[signal.symbol] = OpenTrade(
            trade_log_id=trade_id,
            symbol=signal.symbol,
            action=signal.action,
            quantity=signal.quantity,
            entry_price=order.filled_price,
            stop_loss=signal.stop_loss,
            target=signal.target,
            strategy=signal.strategy,
            entry_order_id=order.order_id,
            atr=round(entry_atr, 4),
        )

        logger.info(
            f"Trade opened #{trade_id} | {signal.action.value} {signal.quantity}×"
            f"{signal.symbol} @ ₹{order.filled_price:.2f} | "
            f"sl=₹{signal.stop_loss:.2f} target=₹{signal.target:.2f}"
        )
        return True

    def check_exits(self, symbol: str, current_price: float) -> Optional[float]:
        """
        Check if an open trade has hit its stop-loss or target.

        Call this on every new candle for each symbol that has an open position.

        Args:
            symbol:        The symbol to check
            current_price: The latest candle's close price

        Returns:
            net_pnl if position was closed, None if still open.
        """
        trade = self._open_trades.get(symbol)
        if trade is None:
            return None

        # ── Time-based force exit ─────────────────────────────────────
        # If the current IST time is at or past FORCE_EXIT_TIME (default 2:00 PM),
        # close the trade regardless of whether SL or target has been reached.
        #
        # Why: afternoon liquidity thins significantly after 2 PM. Bid-ask spreads
        # widen, price moves become random, and end-of-day institutional rebalancing
        # creates noise that has nothing to do with the trade's original thesis.
        # Better to exit at a fair price now than risk a random move at 3 PM.
        #
        # This is a soft floor — the hard EOD square-off at SQUAREOFF_TIME (3:15 PM)
        # is always the last resort. FORCE_EXIT_TIME is simply a smarter early exit.
        if FORCE_EXIT_ENABLED:
            now_ist = datetime.now(IST).time()
            if now_ist >= FORCE_EXIT_TIME:
                logger.info(
                    f"Force exit triggered | {symbol} | "
                    f"time={now_ist.strftime('%H:%M')} IST ≥ "
                    f"{FORCE_EXIT_TIME.strftime('%H:%M')} cutoff | "
                    f"price=₹{current_price:.2f}"
                )
                return self._close_trade(
                    trade, current_price,
                    f"Force exit at {FORCE_EXIT_TIME.strftime('%H:%M')} IST "
                    f"(price=₹{current_price:.2f})"
                )

        # ── Trailing stop: update SL before checking exit conditions ──
        # The trail may move the stop_loss upward (BUY) or downward (SELL),
        # so we always apply it first. This way a trade that reaches 2×ATR
        # profit will trail its stop, and may immediately exit if price has
        # pulled back past the new stop on the same candle.
        if TRAIL_STOP_ENABLED and trade.atr > 0:
            self._update_trailing_stop(trade, current_price)

        # ── Check exit conditions ──────────────────────────────────────
        exit_reason = None

        if trade.action == Action.BUY:
            if current_price <= trade.stop_loss:
                phase_str = {0: "SL", 1: "breakeven stop", 2: "trailing stop"}[trade.trail_phase]
                exit_reason = (
                    f"{phase_str} hit @ ₹{current_price:.2f} "
                    f"(sl=₹{trade.stop_loss:.2f})"
                )
            elif current_price >= trade.target:
                exit_reason = f"Target hit @ ₹{current_price:.2f} (target=₹{trade.target:.2f})"
        else:  # SELL
            if current_price >= trade.stop_loss:
                phase_str = {0: "SL", 1: "breakeven stop", 2: "trailing stop"}[trade.trail_phase]
                exit_reason = (
                    f"{phase_str} hit @ ₹{current_price:.2f} "
                    f"(sl=₹{trade.stop_loss:.2f})"
                )
            elif current_price <= trade.target:
                exit_reason = f"Target hit @ ₹{current_price:.2f} (target=₹{trade.target:.2f})"

        if exit_reason:
            return self._close_trade(trade, current_price, exit_reason)

        return None

    def square_off_symbol(self, symbol: str, reason: str = "Manual square-off") -> Optional[float]:
        """Close a specific position immediately at market price."""
        trade = self._open_trades.get(symbol)
        if trade is None:
            return None
        ltp = self._broker.get_ltp(symbol)
        return self._close_trade(trade, ltp, reason)

    def square_off_all(self) -> dict[str, float]:
        """
        Close all open positions. Called at 3:15 PM for intraday square-off.
        Returns a dict of symbol → net_pnl for each closed trade.
        """
        results = {}
        for symbol in list(self._open_trades.keys()):
            ltp = self._broker.get_ltp(symbol)
            pnl = self._close_trade(
                self._open_trades[symbol], ltp,
                f"End-of-day square-off at {SQUAREOFF_TIME} IST"
            )
            results[symbol] = pnl or 0.0
        return results

    def _update_trailing_stop(self, trade: OpenTrade, current_price: float) -> None:
        """
        Advance the trailing stop through its two phases.

        Phase 1 — breakeven: triggered when unrealised profit ≥ TRAIL_BREAKEVEN_ATR × ATR.
          Moves stop to entry price. The trade can now only break even or profit.

        Phase 2 — trailing: triggered when unrealised profit ≥ TRAIL_START_ATR × ATR.
          Trails the stop at TRAIL_DISTANCE_ATR × ATR behind the current price.
          The stop is ratcheted — it only ever moves in the favourable direction.

        ATR is fixed at the value computed at entry so the milestones don't shift
        as market volatility changes during the trade.

        Args:
            trade:         The open trade to update (mutated in place).
            current_price: Latest candle close price.
        """
        atr    = trade.atr
        entry  = trade.entry_price

        if trade.action == Action.BUY:
            profit = current_price - entry

            # Phase 1: move stop to breakeven
            if trade.trail_phase == 0 and profit >= TRAIL_BREAKEVEN_ATR * atr:
                new_sl = entry
                if new_sl > trade.stop_loss:   # only move in favourable direction
                    old_sl = trade.stop_loss
                    trade.stop_loss  = round(new_sl, 2)
                    trade.trail_phase = 1
                    logger.info(
                        f"Trail Phase 1 (breakeven) | {trade.symbol} | "
                        f"profit={profit:.2f} ≥ {TRAIL_BREAKEVEN_ATR}×ATR={TRAIL_BREAKEVEN_ATR*atr:.2f} | "
                        f"SL: ₹{old_sl:.2f} → ₹{new_sl:.2f}"
                    )

            # Phase 2: trail at TRAIL_DISTANCE_ATR × ATR below current price
            if trade.trail_phase >= 1 and profit >= TRAIL_START_ATR * atr:
                new_sl = current_price - TRAIL_DISTANCE_ATR * atr
                if new_sl > trade.stop_loss:   # ratchet — never lower the stop
                    old_sl = trade.stop_loss
                    trade.stop_loss  = round(new_sl, 2)
                    trade.trail_phase = 2
                    logger.info(
                        f"Trail Phase 2 (trailing) | {trade.symbol} | "
                        f"price=₹{current_price:.2f} | "
                        f"SL: ₹{old_sl:.2f} → ₹{new_sl:.2f}"
                    )

        else:  # SELL / short
            profit = entry - current_price

            # Phase 1: move stop to breakeven
            if trade.trail_phase == 0 and profit >= TRAIL_BREAKEVEN_ATR * atr:
                new_sl = entry
                if new_sl < trade.stop_loss:
                    old_sl = trade.stop_loss
                    trade.stop_loss  = round(new_sl, 2)
                    trade.trail_phase = 1
                    logger.info(
                        f"Trail Phase 1 (breakeven) | {trade.symbol} | "
                        f"profit={profit:.2f} ≥ {TRAIL_BREAKEVEN_ATR}×ATR={TRAIL_BREAKEVEN_ATR*atr:.2f} | "
                        f"SL: ₹{old_sl:.2f} → ₹{new_sl:.2f}"
                    )

            # Phase 2: trail at TRAIL_DISTANCE_ATR × ATR above current price
            if trade.trail_phase >= 1 and profit >= TRAIL_START_ATR * atr:
                new_sl = current_price + TRAIL_DISTANCE_ATR * atr
                if new_sl < trade.stop_loss:   # ratchet — never raise the stop
                    old_sl = trade.stop_loss
                    trade.stop_loss  = round(new_sl, 2)
                    trade.trail_phase = 2
                    logger.info(
                        f"Trail Phase 2 (trailing) | {trade.symbol} | "
                        f"price=₹{current_price:.2f} | "
                        f"SL: ₹{old_sl:.2f} → ₹{new_sl:.2f}"
                    )

    def _close_trade(self, trade: OpenTrade, exit_price: float, reason: str) -> float:
        """Execute the exit order and record P&L."""
        exit_transaction = (
            TransactionType.SELL if trade.action == Action.BUY else TransactionType.BUY
        )

        exit_order = self._broker.place_order(
            symbol=trade.symbol,
            transaction_type=exit_transaction,
            quantity=trade.quantity,
            order_type=OrderType.MARKET,
        )

        actual_exit = exit_order.filled_price if exit_order.filled_price else exit_price
        brokerage   = 40.0  # Approximate: ₹20 entry + ₹20 exit

        try:
            net_pnl = self._log.record_exit(
                trade_id=trade.trade_log_id,
                exit_price=actual_exit,
                brokerage=brokerage,
            )
        except Exception as exc:
            logger.error(
                f"Trade log failed for #{trade.trade_log_id} ({trade.symbol}): {exc}. "
                f"Position removed from tracker; P&L not persisted."
            )
            net_pnl = 0.0
        finally:
            # Always remove from open trades — even if DB logging fails, we must
            # not leave a ghost position that triggers repeated spurious orders.
            self._open_trades.pop(trade.symbol, None)

        logger.info(
            f"Trade closed #{trade.trade_log_id} | {trade.symbol} "
            f"exit=₹{actual_exit:.2f} | {reason} | net_pnl=₹{net_pnl:.2f}"
        )
        return net_pnl

    @property
    def open_symbols(self) -> list[str]:
        """Return list of symbols with open trades."""
        return list(self._open_trades.keys())

    def has_open_trade(self, symbol: str) -> bool:
        return symbol in self._open_trades
