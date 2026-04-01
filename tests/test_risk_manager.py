"""
Unit tests for the Risk Manager and Position Sizer.

We test all 10 safety rules to ensure the Risk Manager correctly blocks
dangerous trades and approves safe ones.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from risk.position_sizer import calculate_quantity
from risk.risk_manager import RiskManager, RiskState
from strategies.base_strategy import Action, Signal

CAPITAL = 100_000.0  # ₹1,00,000 test capital


def make_signal(
    symbol: str = "RELIANCE",
    action: Action = Action.BUY,
    entry: float = 500.0,
    stop_loss: float = 492.0,
    target: float = 516.0,
    strategy: str = "test",
) -> Signal:
    return Signal(
        symbol=symbol,
        action=action,
        entry_price=entry,
        stop_loss=stop_loss,
        target=target,
        strategy=strategy,
    )


# ── Position Sizer tests ──────────────────────────────────────────────

class TestPositionSizer:
    def test_basic_calculation(self):
        # Capital=1,00,000 | Risk=1% | Entry=500 | SL=492 → risk=8/share
        # qty = floor(1000/8) = 125
        qty = calculate_quantity(100_000, 500, 492)
        assert qty == 125

    def test_zero_risk_returns_zero(self):
        qty = calculate_quantity(100_000, 500, 500)
        assert qty == 0

    def test_tight_stop_gives_more_shares(self):
        """Tighter stop → lower risk per share → more shares (when within capital cap)."""
        # Use entry=₹100 so neither position exceeds capital (500×100=₹50k, 100×100=₹10k)
        qty_tight = calculate_quantity(100_000, 100, 98)    # risk = ₹2 → 500 shares
        qty_wide  = calculate_quantity(100_000, 100, 90)    # risk = ₹10 → 100 shares
        assert qty_tight > qty_wide

    def test_capital_cap_on_oversized_position(self):
        """When margin required exceeds MAX_POSITION_PCT of capital, cap kicks in."""
        from config.settings import INTRADAY_LEVERAGE, MAX_POSITION_PCT
        capital = 100_000
        entry   = 500
        # risk=₹1 → qty=1000, margin=₹1,00,000 >> 30% of capital → fallback kicks in
        qty = calculate_quantity(capital, entry, 499)
        # Margin (position_value / leverage) must not exceed 30% of capital
        assert qty * entry / INTRADAY_LEVERAGE <= capital * MAX_POSITION_PCT

    def test_position_value_never_exceeds_leverage_limit(self):
        """Total margin (position_value / leverage) must not exceed full capital."""
        from config.settings import INTRADAY_LEVERAGE
        qty = calculate_quantity(100_000, 500, 499)  # Very tight stop
        # With 5x leverage, position can be up to 5× capital — but margin ≤ capital
        assert qty * 500 / INTRADAY_LEVERAGE <= 100_000

    def test_negative_capital_returns_zero(self):
        qty = calculate_quantity(-1000, 500, 492)
        assert qty == 0


# ── Risk Manager tests ────────────────────────────────────────────────

MARKET_OPEN_TIME = "2024-01-02 09:25:00+05:30"  # After blackout, before 2:30 PM


class TestRiskManager:

    def _rm_at_time(self, time_str: str, capital: float = CAPITAL) -> RiskManager:
        """Create a RiskManager whose 'now' is fixed to the given IST time."""
        rm = RiskManager(capital=capital)
        return rm

    # ── Rule 10: Signal sanity ───────────────────────────────────────
    def test_invalid_signal_rejected(self):
        rm = RiskManager(CAPITAL)
        bad = make_signal(entry=500, stop_loss=510, target=520)  # SL > entry for BUY
        with patch("risk.risk_manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime.fromisoformat(MARKET_OPEN_TIME)
            decision = rm.evaluate(bad)
        assert not decision.approved
        assert "sanity" in decision.reason.lower()

    # ── Rule 8: Max open positions ───────────────────────────────────
    def test_max_positions_enforced(self):
        rm = RiskManager(CAPITAL)
        # Open 3 positions manually
        rm.state.open_positions = {"RELIANCE", "TCS", "INFY"}
        sig = make_signal("HDFC")
        with patch("risk.risk_manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime.fromisoformat(MARKET_OPEN_TIME)
            decision = rm.evaluate(sig)
        assert not decision.approved
        assert "Max" in decision.reason

    # ── Rule 9: No duplicate symbol ─────────────────────────────────
    def test_duplicate_symbol_rejected(self):
        rm = RiskManager(CAPITAL)
        rm.state.open_positions = {"RELIANCE"}
        sig = make_signal("RELIANCE")
        with patch("risk.risk_manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime.fromisoformat(MARKET_OPEN_TIME)
            decision = rm.evaluate(sig)
        assert not decision.approved
        assert "open position" in decision.reason.lower()

    # ── Rule 4: Daily loss halt ──────────────────────────────────────
    def test_daily_loss_halt(self):
        rm = RiskManager(CAPITAL)
        rm.state.trading_halted = True
        sig = make_signal()
        with patch("risk.risk_manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime.fromisoformat(MARKET_OPEN_TIME)
            decision = rm.evaluate(sig)
        assert not decision.approved
        assert "halted" in decision.reason.lower()

    def test_daily_loss_triggers_halt(self):
        """Closing a losing trade that exceeds 3% should halt trading."""
        rm = RiskManager(CAPITAL)
        rm.state.open_positions.add("RELIANCE")
        rm.on_position_closed("RELIANCE", pnl=-3_500)  # -3.5% of 1,00,000
        assert rm.state.trading_halted

    # ── Rule 5: Consecutive loss pause ──────────────────────────────
    def test_consecutive_losses_pause(self):
        """3 consecutive losses should trigger 1-hour pause."""
        rm = RiskManager(CAPITAL)
        for symbol in ["RELIANCE", "TCS", "INFY"]:
            rm.state.open_positions.add(symbol)
            rm.on_position_closed(symbol, pnl=-100)

        assert rm.state.halt_until is not None
        # Pause should be approx 1 hour from now
        gap = rm.state.halt_until - datetime.now(rm.state.halt_until.tzinfo)
        assert 50 <= gap.total_seconds() / 60 <= 61  # ~1 hour

    def test_winning_trade_resets_loss_streak(self):
        rm = RiskManager(CAPITAL)
        rm.state.open_positions.update(["RELIANCE", "TCS"])
        rm.on_position_closed("RELIANCE", pnl=-100)
        rm.on_position_closed("TCS", pnl=500)  # Win → reset streak
        assert rm.state.consecutive_losses == 0

    # ── Rule 6: Opening blackout ─────────────────────────────────────
    def test_no_entry_before_blackout(self):
        rm = RiskManager(CAPITAL)
        sig = make_signal()
        early_time = "2024-01-02 09:18:00+05:30"
        with patch("risk.risk_manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime.fromisoformat(early_time)
            decision = rm.evaluate(sig)
        assert not decision.approved
        assert "blackout" in decision.reason.lower()

    # ── Rule 7: No entries after 2:30 PM ────────────────────────────
    def test_no_entry_after_cutoff(self):
        rm = RiskManager(CAPITAL)
        sig = make_signal()
        late_time = "2024-01-02 14:35:00+05:30"
        with patch("risk.risk_manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime.fromisoformat(late_time)
            decision = rm.evaluate(sig)
        assert not decision.approved
        assert "2:30" in decision.reason or "14:30" in decision.reason

    # ── Rule 3: Reward:risk ratio ────────────────────────────────────
    def test_poor_rr_ratio_rejected(self):
        """A trade with 1:1 RR should be rejected (minimum is 2:1)."""
        rm = RiskManager(CAPITAL)
        # Entry=500, SL=492 (risk=8), Target=508 (reward=8) → RR=1:1
        bad_rr = make_signal(entry=500, stop_loss=492, target=508)
        with patch("risk.risk_manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime.fromisoformat(MARKET_OPEN_TIME)
            decision = rm.evaluate(bad_rr)
        assert not decision.approved
        assert "reward" in decision.reason.lower() or "ratio" in decision.reason.lower()

    # ── HOLD signals ─────────────────────────────────────────────────
    def test_hold_always_approved(self):
        rm = RiskManager(CAPITAL)
        rm.state.trading_halted = True  # Even when halted, HOLD passes
        hold = Signal("RELIANCE", Action.HOLD, 500, 500, 500, strategy="test")
        with patch("risk.risk_manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime.fromisoformat(MARKET_OPEN_TIME)
            decision = rm.evaluate(hold)
        assert decision.approved

    # ── Happy path ───────────────────────────────────────────────────
    def test_valid_signal_approved(self):
        """A clean, valid signal at a normal trading time should be approved."""
        rm = RiskManager(CAPITAL)
        sig = make_signal(entry=500, stop_loss=492, target=516)
        with patch("risk.risk_manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime.fromisoformat(MARKET_OPEN_TIME)
            decision = rm.evaluate(sig)
        assert decision.approved
        assert decision.signal is not None
        assert decision.signal.quantity > 0

    def test_quantity_filled_after_approval(self):
        """After approval, signal.quantity must be set by position sizer."""
        rm = RiskManager(CAPITAL)
        sig = make_signal(entry=500, stop_loss=492, target=516)
        with patch("risk.risk_manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime.fromisoformat(MARKET_OPEN_TIME)
            decision = rm.evaluate(sig)
        assert decision.signal.quantity == 125  # 1% of 1,00,000 / 8 = 125

    # ── State transitions ────────────────────────────────────────────
    def test_open_positions_tracked(self):
        rm = RiskManager(CAPITAL)
        rm.on_position_opened("RELIANCE")
        assert "RELIANCE" in rm.state.open_positions

    def test_closed_position_removed(self):
        rm = RiskManager(CAPITAL)
        rm.on_position_opened("TCS")
        rm.on_position_closed("TCS", pnl=500)
        assert "TCS" not in rm.state.open_positions

    def test_new_day_resets_state(self):
        rm = RiskManager(CAPITAL)
        rm.state.trading_halted = True
        rm.state.daily_pnl = -5000
        rm.state.consecutive_losses = 5
        rm.new_day(CAPITAL)
        assert not rm.state.trading_halted
        assert rm.state.daily_pnl == 0
        assert rm.state.consecutive_losses == 0
