"""
Circuit breaker checker for NSE stocks and indices.

What is a circuit breaker?
  SEBI (India's market regulator) mandates that trading is halted when a
  stock or index moves too far in one direction on a single day. This
  prevents panic-driven crashes and gives the market time to stabilise.

Individual stock circuit limits:
  - 2%, 5%, 10%, or 20% (varies by stock; most NIFTY50 stocks have 20%)
  - Once a stock hits its circuit limit, no more orders can be placed.

NSE market-wide circuit breakers (index-level):
  - 10% drop in NIFTY50 → 45-minute trading halt
  - 15% drop            → 1-hour 45-minute halt (or close for the day)
  - 20% drop            → Market closed for the rest of the day

Why this matters for the bot:
  If a stock has already moved 18% and is approaching its 20% circuit,
  placing a buy order is dangerous — it could trigger the circuit and
  trap us in an illiquid position.

  We check this BEFORE generating signals to avoid circuit-trapped trades.
"""

from __future__ import annotations

from loguru import logger


# NIFTY50 stocks typically have 20% circuit limits.
# A few volatile ones (newly added or PSU stocks) may have lower limits.
# We use conservative 10% as our "danger zone" threshold.
CIRCUIT_WARNING_THRESHOLD = 0.10  # Warn if stock already moved > 10% today
CIRCUIT_BLOCK_THRESHOLD   = 0.18  # Block trade if stock moved > 18% today


def check_circuit_risk(
    symbol: str,
    prev_close: float,
    current_price: float,
    circuit_limit_pct: float = 0.20,
) -> tuple[bool, str]:
    """
    Check if a stock is approaching its circuit limit.

    Args:
        symbol:            Stock symbol (for logging)
        prev_close:        Previous day's closing price
        current_price:     Current market price
        circuit_limit_pct: The stock's circuit limit (default 20%)

    Returns:
        (is_safe, reason)
        is_safe = True  → trade can proceed
        is_safe = False → trade should be blocked
    """
    if prev_close <= 0:
        return True, "OK"

    pct_move = abs(current_price - prev_close) / prev_close

    if pct_move >= circuit_limit_pct * (CIRCUIT_BLOCK_THRESHOLD / 0.20):
        reason = (
            f"{symbol} has moved {pct_move:.1%} today, "
            f"dangerously close to {circuit_limit_pct:.0%} circuit limit. "
            f"Trade blocked."
        )
        logger.warning(reason)
        return False, reason

    if pct_move >= circuit_limit_pct * (CIRCUIT_WARNING_THRESHOLD / 0.20):
        logger.warning(
            f"{symbol} has moved {pct_move:.1%} today — circuit watch active."
        )

    return True, "OK"


def check_market_circuit(nifty_prev_close: float, nifty_current: float) -> tuple[bool, str]:
    """
    Check if the broad NIFTY market has triggered a circuit breaker.

    Args:
        nifty_prev_close: NIFTY50 index previous close
        nifty_current:    NIFTY50 index current value

    Returns:
        (trading_allowed, reason)
    """
    if nifty_prev_close <= 0:
        return True, "OK"

    pct_drop = (nifty_prev_close - nifty_current) / nifty_prev_close

    if pct_drop >= 0.20:
        msg = f"NIFTY market-wide circuit: -{pct_drop:.1%}. Market closed."
        logger.critical(msg)
        return False, msg

    if pct_drop >= 0.15:
        msg = f"NIFTY 15% circuit breaker triggered: -{pct_drop:.1%}. Extended halt."
        logger.critical(msg)
        return False, msg

    if pct_drop >= 0.10:
        msg = f"NIFTY 10% circuit breaker triggered: -{pct_drop:.1%}. 45-min halt."
        logger.warning(msg)
        return False, msg

    return True, "OK"
