"""
Position Sizer — calculates how many shares to buy.

This is one of the most important concepts in trading, yet most beginners
ignore it completely and just "buy what feels right." That's how people
blow up their accounts.

The formula (Fixed Fractional Position Sizing):

    quantity = floor( (capital × risk_per_trade_pct) / risk_per_share )

Where:
    capital            = your total trading capital (e.g. ₹1,00,000)
    risk_per_trade_pct = max % of capital you're willing to lose on this trade
                         (we use 1% = 0.01)
    risk_per_share     = |entry_price − stop_loss|

Example:
    Capital = ₹1,00,000
    Entry   = ₹500 per share
    Stop    = ₹492 per share
    Risk per share = ₹8

    quantity = floor((1,00,000 × 0.01) / 8) = floor(1000 / 8) = 125 shares
    Total risk = 125 × ₹8 = ₹1,000 = exactly 1% of capital ✓

Why this matters:
    Without position sizing, two outcomes are common:
      A) You risk too little → gains are meaningless
      B) You risk too much  → one bad trade wipes out weeks of gains

    With 1% risk per trade and 2:1 reward:risk, you need to be right less
    than 40% of the time to be profitable. That's achievable.
"""

from __future__ import annotations

import math

from loguru import logger

from config.settings import INTRADAY_LEVERAGE, RISK_PER_TRADE_PCT, MAX_POSITION_PCT


def calculate_quantity(
    capital: float,
    entry_price: float,
    stop_loss: float,
    risk_pct: float = RISK_PER_TRADE_PCT,
) -> int:
    """
    Calculate the number of shares to trade using fixed fractional sizing.

    Args:
        capital:      Available trading capital in INR
        entry_price:  Price at which we plan to enter the trade
        stop_loss:    Price at which we would exit for a loss
        risk_pct:     Fraction of capital to risk (default: 1% = 0.01)

    Returns:
        Number of shares to buy/sell (minimum 1, 0 if trade is invalid).

    Example:
        calculate_quantity(100000, 500, 492) → 125
    """
    risk_per_share = abs(entry_price - stop_loss)

    if risk_per_share == 0:
        logger.warning(
            "PositionSizer: entry_price == stop_loss, cannot calculate quantity."
        )
        return 0

    if entry_price <= 0 or capital <= 0:
        return 0

    rupees_at_risk = capital * risk_pct
    quantity = math.floor(rupees_at_risk / risk_per_share)

    # Sanity check: margin required can't exceed MAX_POSITION_PCT of capital.
    # With MIS leverage, margin = position_value / leverage.
    # Cap so we never block more than 30% of capital as margin for one trade.
    margin_required = quantity * entry_price / INTRADAY_LEVERAGE
    if margin_required > capital * MAX_POSITION_PCT:
        quantity = math.floor(capital * MAX_POSITION_PCT * INTRADAY_LEVERAGE / entry_price)

    logger.debug(
        f"PositionSizer | capital={capital:.0f} entry={entry_price:.2f} "
        f"sl={stop_loss:.2f} risk_per_share={risk_per_share:.2f} "
        f"rupees_at_risk={rupees_at_risk:.0f} qty={quantity}"
    )

    return max(0, quantity)
