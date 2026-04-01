"""
Risk Manager — the bot's safety guard.

Every signal from a strategy must pass through the Risk Manager before
an order is placed. Think of it as a compliance officer who checks:
  "Is this trade safe given our current state?"

The Risk Manager enforces 10 hardcoded rules. These are not optional.
They exist because most beginners lose money by:
  1. Risking too much on a single trade (FOMO — fear of missing out)
  2. Not cutting losses quickly (hope that it will recover)
  3. Overtrading after a bad day (revenge trading)
  4. Trading at market open when prices are most irrational

These rules are based on professional risk management principles adapted
for the Indian retail intraday market.

The 10 Rules:
──────────────────────────────────────────────────────────────────────
Rule 1: Max 1% capital risk per trade
   → Position size is calculated so max loss = 1% of capital

Rule 2: Stop-loss required on every trade
   → No trade without a defined exit for losses

Rule 3: Min 2:1 reward:risk ratio
   → Target profit must be at least 2× the stop-loss distance

Rule 4: Max daily loss = 3% of capital → halt trading for the day
   → If today's P&L drops below -3%, stop all trading. Come back tomorrow.

Rule 5: After 3 consecutive losses → pause 1 hour
   → Prevents revenge trading after a losing streak

Rule 6: No entries before 9:20 AM
   → Opening 5 minutes are chaotic; institutional orders cause wild swings

Rule 7: No new entries after 2:30 PM
   → End-of-day reversals and squaring-off by other traders cause whipsaws

Rule 8: Max 3 open positions simultaneously
   → Concentration helps a beginner focus and manage risk

Rule 9: No duplicate: only one position per symbol at a time
   → No averaging down (buying more of a losing position)

Rule 10: Signal must be validated (prices must make mathematical sense)
   → Stop-loss must be below entry for BUY, above for SELL
──────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger

from config.settings import (
    FIRST_CANDLE_BLACKOUT,
    IST,
    MAX_CONSECUTIVE_LOSSES,
    MAX_DAILY_LOSS_PCT,
    MAX_OPEN_POSITIONS,
    MIN_REWARD_RISK_RATIO,
    NO_NEW_ENTRIES_TIME,
)
from risk.position_sizer import calculate_quantity
from strategies.base_strategy import Action, Signal


@dataclass
class RiskState:
    """
    Tracks the current risk state across the trading session.

    This is updated by the Risk Manager as trades happen throughout the day.
    It gets reset at the start of each trading day.
    """
    capital:             float       # Current total capital (cash + open positions)
    starting_capital:    float       # Capital at start of day (for daily loss calc)
    daily_pnl:           float = 0.0            # Realised P&L for today
    unrealised_pnl:      float = 0.0            # Current open position P&L
    open_positions:      set   = field(default_factory=set)   # Set of open symbols
    consecutive_losses:  int   = 0              # Streak of losing trades
    trading_halted:      bool  = False           # True if daily loss limit hit
    halt_until:          Optional[datetime] = None  # Time when 1-hr pause ends

    @property
    def total_pnl(self) -> float:
        return self.daily_pnl + self.unrealised_pnl

    @property
    def daily_loss_pct(self) -> float:
        if self.starting_capital == 0:
            return 0.0
        return self.total_pnl / self.starting_capital  # Negative when losing

    def new_day(self, capital: float) -> None:
        """Reset daily counters at market open."""
        self.capital          = capital
        self.starting_capital = capital
        self.daily_pnl        = 0.0
        self.unrealised_pnl   = 0.0
        self.open_positions   = set()
        self.consecutive_losses = 0
        self.trading_halted   = False
        self.halt_until       = None


@dataclass
class RiskDecision:
    """Result of the Risk Manager's evaluation of a signal."""
    approved:  bool
    reason:    str
    signal:    Optional[Signal] = None  # Signal with quantity filled in if approved


class RiskManager:
    """
    Evaluates signals against all 10 risk rules and returns a decision.

    Usage:
        rm = RiskManager(capital=100_000)
        decision = rm.evaluate(signal)
        if decision.approved:
            order_manager.place(decision.signal)
    """

    def __init__(self, capital: float) -> None:
        self.state = RiskState(capital=capital, starting_capital=capital)

    def evaluate(self, signal: Signal, now: Optional[datetime] = None) -> RiskDecision:
        """
        Run all risk checks on a signal.

        Args:
            signal: The trading signal to evaluate.
            now:    Override "current time" for time-gate rules (Rules 5–7).
                    Pass the candle timestamp during replay/backtesting so
                    rules use candle time instead of wall-clock time.
                    Defaults to datetime.now(IST) for live operation.

        Returns RiskDecision with approved=True only if ALL rules pass.
        """
        # HOLD signals always pass through (no action needed)
        if signal.action == Action.HOLD:
            return RiskDecision(approved=True, reason="HOLD — no action", signal=signal)

        if now is None:
            now = datetime.now(IST)

        # ── Rule 4: Daily loss halt ──────────────────────────────────
        if self.state.trading_halted:
            return RiskDecision(
                approved=False,
                reason=f"Trading halted: daily loss limit hit "
                       f"({self.state.daily_loss_pct:.2%} today)",
            )

        # ── Rule 5: Consecutive loss pause ──────────────────────────
        if self.state.halt_until and now < self.state.halt_until:
            remaining = int((self.state.halt_until - now).total_seconds() / 60)
            return RiskDecision(
                approved=False,
                reason=f"1-hour pause after {MAX_CONSECUTIVE_LOSSES} consecutive losses. "
                       f"Resume in {remaining} min.",
            )

        # ── Rule 6: No entries before 9:20 AM ───────────────────────
        if now.time() < FIRST_CANDLE_BLACKOUT:
            return RiskDecision(
                approved=False,
                reason=f"No entries before {FIRST_CANDLE_BLACKOUT} IST (opening blackout).",
            )

        # ── Rule 7: No new entries after 2:30 PM ────────────────────
        if now.time() >= NO_NEW_ENTRIES_TIME:
            return RiskDecision(
                approved=False,
                reason=f"No new entries after {NO_NEW_ENTRIES_TIME} IST.",
            )

        # ── Rule 8: Max open positions ───────────────────────────────
        if len(self.state.open_positions) >= MAX_OPEN_POSITIONS:
            return RiskDecision(
                approved=False,
                reason=f"Max {MAX_OPEN_POSITIONS} open positions reached "
                       f"({self.state.open_positions}).",
            )

        # ── Rule 9: No duplicate positions ──────────────────────────
        if signal.symbol in self.state.open_positions:
            return RiskDecision(
                approved=False,
                reason=f"Already have an open position in {signal.symbol}. "
                       f"No averaging down allowed.",
            )

        # ── Rule 10: Signal sanity check ────────────────────────────
        if not signal.is_valid():
            return RiskDecision(
                approved=False,
                reason=f"Signal failed sanity check: entry={signal.entry_price} "
                       f"sl={signal.stop_loss} target={signal.target}",
            )

        # ── Rule 1: Calculate quantity (1% capital risk) ─────────────
        quantity = calculate_quantity(
            capital=self.state.capital,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
        )
        if quantity <= 0:
            return RiskDecision(
                approved=False,
                reason=f"Calculated quantity is 0 — position too small for capital "
                       f"or stop-loss too tight.",
            )

        # ── Rule 3: Reward:risk ratio ────────────────────────────────
        signal.quantity = quantity
        if round(signal.reward_risk_ratio, 2) < MIN_REWARD_RISK_RATIO:
            return RiskDecision(
                approved=False,
                reason=f"Reward:risk ratio {signal.reward_risk_ratio:.2f}x is below "
                       f"minimum {MIN_REWARD_RISK_RATIO}x. "
                       f"Move target further or tighten stop-loss.",
            )

        # ── All checks passed ────────────────────────────────────────
        logger.info(
            f"Risk APPROVED | {signal} | "
            f"daily_pnl={self.state.daily_pnl:.0f} "
            f"open_positions={len(self.state.open_positions)}"
        )
        return RiskDecision(approved=True, reason="All risk checks passed", signal=signal)

    # ── State update methods (called by Order Manager / Portfolio) ───

    def on_position_opened(self, symbol: str) -> None:
        """Call when a trade is successfully placed."""
        self.state.open_positions.add(symbol)

    def on_position_closed(self, symbol: str, pnl: float) -> None:
        """Call when a position is closed (via target, stop-loss, or manual exit)."""
        self.state.open_positions.discard(symbol)
        self.state.daily_pnl += pnl

        # Track consecutive losses (Rule 5)
        if pnl < 0:
            self.state.consecutive_losses += 1
            if self.state.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
                self.state.halt_until = datetime.now(IST) + timedelta(hours=1)
                logger.warning(
                    f"RiskManager: {MAX_CONSECUTIVE_LOSSES} consecutive losses. "
                    f"Trading paused for 1 hour until {self.state.halt_until.strftime('%H:%M')}."
                )
        else:
            self.state.consecutive_losses = 0  # Reset streak on any win

        # Check daily loss limit (Rule 4)
        if self.state.daily_loss_pct <= -MAX_DAILY_LOSS_PCT:
            self.state.trading_halted = True
            logger.critical(
                f"RiskManager: Daily loss limit hit! "
                f"P&L today = {self.state.daily_pnl:.0f} "
                f"({self.state.daily_loss_pct:.2%}). "
                f"All trading halted for the day."
            )

    def on_unrealised_pnl_update(self, total_unrealised: float) -> None:
        """Call periodically to update open position P&L."""
        self.state.unrealised_pnl = total_unrealised
        # Re-check daily loss limit including unrealised losses
        if not self.state.trading_halted and self.state.daily_loss_pct <= -MAX_DAILY_LOSS_PCT:
            self.state.trading_halted = True
            logger.critical(
                f"RiskManager: Daily loss limit hit (including unrealised). "
                f"Halting trading."
            )

    def new_day(self, capital: float) -> None:
        """Reset for a new trading day. Call at 9:00 AM each morning."""
        self.state.new_day(capital)
        logger.info(f"RiskManager reset for new day. Capital: ₹{capital:,.0f}")

    @property
    def is_trading_allowed(self) -> bool:
        """Quick check: can we place new trades right now?"""
        now = datetime.now(IST)
        if self.state.trading_halted:
            return False
        if self.state.halt_until and now < self.state.halt_until:
            return False
        if now.time() < FIRST_CANDLE_BLACKOUT:
            return False
        if now.time() >= NO_NEW_ENTRIES_TIME:
            return False
        return True
