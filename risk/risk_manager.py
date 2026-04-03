"""
Risk Manager — the bot's safety guard.

Every signal from a strategy must pass through the Risk Manager before
an order is placed. Think of it as a compliance officer who checks:
  "Is this trade safe given our current state?"

The Risk Manager enforces 11 hardcoded rules. These are not optional.
They exist because most beginners lose money by:
  1. Risking too much on a single trade (FOMO — fear of missing out)
  2. Not cutting losses quickly (hope that it will recover)
  3. Overtrading after a bad day (revenge trading)
  4. Trading at market open when prices are most irrational

These rules are based on professional risk management principles adapted
for the Indian retail intraday market.

The 11 Rules:
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

Rule 11: Earnings blackout — no entries within 3 days of earnings results
   → Binary event risk: price can gap 5–8% in any direction on results
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

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from analysis.fundamental_analyst import FundamentalJudgment

try:
    from data.india_vix import get_vix_data as _get_vix_data
except ImportError:  # pragma: no cover
    _get_vix_data = None  # type: ignore[assignment]


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

    def evaluate(self, signal: Signal, now: Optional[datetime] = None, judgment: "Optional[FundamentalJudgment]" = None) -> RiskDecision:
        """
        Run all risk checks on a signal.

        Args:
            signal:   The trading signal to evaluate.
            now:      Override "current time" for time-gate rules (Rules 5–7).
                      Pass the candle timestamp during replay/backtesting so
                      rules use candle time instead of wall-clock time.
                      Defaults to datetime.now(IST) for live operation.
            judgment: Optional FundamentalJudgment from FundamentalAnalyst.
                      If provided, position size is scaled by fundamental quality.
                      Defaults to None (full 1% position size, no scaling).

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

        # ── VIX safety check ─────────────────────────────────────────
        # India VIX > 22: elevated fear — suppress BUY entries (random spikes hit stops).
        # India VIX > 30: extreme fear (crash/event) — suppress ALL entries.
        # Fail-open: if VIX fetch fails, trading continues normally.
        if _get_vix_data is not None:
            try:
                _vix = _get_vix_data()
                if _vix["skip_all"]:
                    return RiskDecision(
                        approved=False,
                        reason=f"India VIX={_vix['vix']:.1f} > 30 — extreme fear, all entries suppressed.",
                    )
                if _vix.get("skip_buys") and signal.action == Action.BUY:
                    return RiskDecision(
                        approved=False,
                        reason=f"India VIX={_vix['vix']:.1f} > 22 — NIFTY falling, BUY entries suppressed.",
                    )
                if _vix.get("skip_sells") and signal.action == Action.SELL:
                    return RiskDecision(
                        approved=False,
                        reason=f"India VIX={_vix['vix']:.1f} > 22 — NIFTY rising, SELL/short entries suppressed.",
                    )
            except Exception:
                pass  # Non-fatal: allow trading if VIX data unavailable

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

        # ── Rule 1: Calculate quantity (1% capital risk, scaled by fundamentals) ──
        _scale = self.position_scale_factor(signal.symbol, judgment)
        if _scale == 0.0:
            return RiskDecision(
                approved=False,
                reason=f"{signal.symbol}: position scale is 0.0 (earnings blackout or extreme bearish risk).",
            )
        from config.settings import RISK_PER_TRADE_PCT
        quantity = calculate_quantity(
            capital=self.state.capital,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            risk_pct=RISK_PER_TRADE_PCT * _scale,
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

        # ── Rule 11: Earnings blackout ───────────────────────────────
        # If the company is reporting earnings within ±3 days, don't trade it.
        # Earnings announcements cause large unpredictable gaps that no technical
        # indicator can predict. The bot protects itself by standing aside.
        # Fail-open: if fundamentals data is unavailable, trading continues normally.
        try:
            from data.fundamentals import fundamentals_cache as _fc
            if _fc.is_earnings_blackout(signal.symbol):
                return RiskDecision(
                    approved=False,
                    reason=f"{signal.symbol} is in earnings blackout window (±3 days). "
                           f"No new entries near earnings — too much binary risk.",
                )
        except Exception:
            pass  # Fail-open: data issue never blocks trading

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

    def restore_daily_state(self, today_closed_trades: list[dict]) -> None:
        """
        Rebuild daily_pnl and consecutive_losses from today's closed trades.

        Called on bot restart so circuit breakers survive process restarts.
        Without this, restarting the bot after 3 losses resets the consecutive-
        loss counter to 0, allowing the bot to trade right into a 4th, 5th, 6th
        loss — exactly what happened on 2026-04-02 (8 losses, -₹6,348).

        Args:
            today_closed_trades: list of trade dicts from TradeLogger.get_today_trades()
                                  filtered to only closed trades (net_pnl is not None).
        """
        if not today_closed_trades:
            return

        # Restore cumulative daily P&L
        self.state.daily_pnl = sum(t.get("net_pnl") or 0.0 for t in today_closed_trades)

        # Restore consecutive loss streak from the tail of today's trades
        streak = 0
        for t in reversed(today_closed_trades):
            if (t.get("net_pnl") or 0.0) < 0:
                streak += 1
            else:
                break   # streak broken by a win
        self.state.consecutive_losses = streak

        logger.info(
            f"RiskManager restored | daily_pnl=₹{self.state.daily_pnl:.0f} | "
            f"consecutive_losses={streak}"
        )

        # Re-apply halt if streak already hit the limit
        if streak >= MAX_CONSECUTIVE_LOSSES:
            self.state.halt_until = datetime.now(IST) + timedelta(hours=1)
            logger.warning(
                f"RiskManager: {streak} consecutive losses carried over from previous session — "
                f"1-hour halt re-applied until {self.state.halt_until.strftime('%H:%M')} IST"
            )

        # Re-apply daily halt if loss limit already breached
        if self.state.daily_loss_pct <= -MAX_DAILY_LOSS_PCT:
            self.state.trading_halted = True
            logger.critical(
                f"RiskManager: daily loss limit already hit before restart "
                f"(P&L=₹{self.state.daily_pnl:.0f}, {self.state.daily_loss_pct:.2%}). "
                f"Trading halted for the rest of the day."
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

    def position_scale_factor(
        self,
        symbol: str,
        judgment: "FundamentalJudgment | None" = None,
    ) -> float:
        """
        Return a position size scaling factor (0.0–1.0) based on fundamental quality.

        This modulates how much of the standard 1% risk budget to use:
          1.0 → full position (BULLISH fundamentals, high confidence)
          0.6 → reduced position (NEUTRAL or mixed signals)
          0.3 → minimal position (BEARISH fundamentals)
          0.0 → blocked (earnings blackout — should already be caught by Rule 11)

        Why scale rather than block?
          Binary allow/block is too crude. A stock with mixed fundamentals is
          still tradeable — just at lower size. Reducing size on uncertain setups
          is how professional traders manage fundamental risk without missing trades.

        Args:
            symbol:   The Kite symbol being traded.
            judgment: Optional FundamentalJudgment from FundamentalAnalyst.analyze().
                      If None, returns 1.0 (full size — no penalty for missing data).

        Returns:
            Float in [0.0, 1.0].
        """
        # Double-check earnings blackout (Rule 11 should catch this first, but be safe)
        try:
            from data.fundamentals import fundamentals_cache as _fc
            if _fc.is_earnings_blackout(symbol):
                return 0.0
        except Exception:
            pass  # fail-open

        if judgment is None:
            return 1.0  # no data → don't penalise

        if judgment.bias == "BULLISH" and judgment.confidence >= 0.6:
            return 1.0
        if judgment.bias == "NEUTRAL":
            return 0.6
        if judgment.bias == "BEARISH":
            return 0.3
        # Fallback: use the model's own position_scale recommendation
        return max(0.3, min(1.0, judgment.position_scale))
