"""
Adaptive Strategy Manager — continuously adjusts strategy parameters based on
real-time market conditions.

Why this exists:
  Fixed strategy parameters work well in specific market conditions but fail
  in others. Rather than waiting for a bad losing streak and manually tweaking
  params, this manager monitors 4 signals every 60 seconds and automatically
  shifts the bot into the appropriate risk mode.

4 signals monitored:
  1. India VIX     — market fear gauge (high VIX → suppress longs)
  2. Market Regime — ADX/ATR trend strength (ranging → fewer signals)
  3. Risk State    — consecutive losses + day P&L (losing streak → pull back)
  4. Time of Day   — post-1:30 PM is choppy (tighten everything)

3 operating modes:
  NORMAL     → Default config parameters
  DEFENSIVE  → Any one risk signal active — tighter filters, fewer entries
  HALTED     → Extreme VIX or VOLATILE regime — no new entries at all

Parameters adjusted in rsi_macd_combo per mode:

  Parameter          NORMAL   DEFENSIVE   Why
  ─────────────────────────────────────────────────────────────────────
  rsi_buy_min          35        45        Narrower neutral zone → fewer buys
  rsi_buy_max          65        60        Only enter if not already running
  rsi_sell_min         40        50        Don't short near oversold
  rsi_exit             80        72        Lock profits earlier
  min_sl_pct         0.75%     1.00%       Wider SL absorbs more noise

HALTED mode does NOT modify config — it relies on VIX/regime checks in
RiskManager.evaluate() to block trades individually. This way individual
risk rules remain the authoritative gate; adaptive mode is a second layer.
"""

from __future__ import annotations

import time as _time
from datetime import datetime
from enum import Enum
from typing import Optional

from loguru import logger

from config import strategies as cfg
from config.settings import IST


class AdaptiveMode(str, Enum):
    NORMAL    = "NORMAL"     # default params, all signals active
    DEFENSIVE = "DEFENSIVE"  # tighter params, fewer entry conditions
    HALTED    = "HALTED"     # extreme conditions — suppress all new entries


# ── Parameter sets ─────────────────────────────────────────────────────
# NORMAL = the config values that strategies.py defines as defaults.
# We capture them on first import so that switching back to NORMAL
# always restores the original values — not whatever DEFENSIVE last wrote.

_BASELINE_PARAMS: dict = {}   # populated on first call to refresh()

_DEFENSIVE_PARAMS: dict = {
    "rsi_buy_min":           45,      # narrower neutral zone: only buy if not chasing
    "rsi_buy_max":           60,
    "rsi_sell_min":          50,      # only short if RSI not near oversold
    "rsi_exit":              85,      # HIGHER than normal (80) — require extreme overbought before
                                      # entering a short; rsi_exit=72 creates MORE shorts, not fewer
    "min_sl_pct":            0.0100,  # 1% min SL → wider cushion against noise
    "require_ema_alignment": True,    # always enforce in defensive
    "use_vwap_filter":       True,
}

_PARAM_KEYS = set(_DEFENSIVE_PARAMS.keys())   # only touch these keys in rsi_macd_combo

# ── TTL / refresh ──────────────────────────────────────────────────────
_REFRESH_INTERVAL = 60   # seconds between re-evaluations

# ── Shared state ───────────────────────────────────────────────────────
_state: dict = {
    "mode":               AdaptiveMode.NORMAL,
    "reason":             "Startup",
    "vix":                None,
    "regime":             "Unknown",
    "direction":          "NEUTRAL",
    "consecutive_losses": 0,
    "day_pnl_pct":        0.0,
    "timestamp":          0.0,
}


# ── Public API ─────────────────────────────────────────────────────────

def get_current_mode() -> AdaptiveMode:
    """Return the current adaptive mode without triggering a refresh."""
    return _state["mode"]


def get_state() -> dict:
    """Return a copy of the current adaptive state (for dashboard display)."""
    return dict(_state)


def refresh(
    consecutive_losses: int = 0,
    day_pnl_pct: float = 0.0,
) -> AdaptiveMode:
    """
    Re-evaluate market conditions and update strategy parameters if needed.

    Called every 5-minute cycle from signal_check() in job_runner.py.

    Args:
        consecutive_losses: RiskManager.state.consecutive_losses
        day_pnl_pct:        RiskManager.state.daily_loss_pct  (negative = losing)

    Returns:
        The current (possibly updated) AdaptiveMode.
    """
    global _state, _BASELINE_PARAMS
    now_ts = _time.monotonic()

    # Capture baseline on first call so we can restore it later
    if not _BASELINE_PARAMS:
        src = cfg.STRATEGY_CONFIGS.get("rsi_macd_combo", {})
        _BASELINE_PARAMS = {k: src[k] for k in _PARAM_KEYS if k in src}

    # Respect TTL — don't hammer VIX/regime fetches on every tick
    if now_ts - _state["timestamp"] < _REFRESH_INTERVAL:
        return _state["mode"]

    _state["timestamp"]          = now_ts
    _state["consecutive_losses"] = consecutive_losses
    _state["day_pnl_pct"]        = day_pnl_pct

    reasons: list[str] = []
    new_mode = AdaptiveMode.NORMAL

    # ── Signal 1: India VIX + direction ──────────────────────────────
    try:
        from data.india_vix import get_vix_data
        from analysis.market_direction import get_market_direction
        vix_data  = get_vix_data()
        vix_val: Optional[float] = vix_data.get("vix")
        _state["vix"] = vix_val

        direction = get_market_direction()
        _state["direction"] = direction.value

        if vix_data.get("skip_all"):
            new_mode = AdaptiveMode.HALTED
            reasons.append(f"VIX={vix_val:.1f} >30 (extreme fear)")
        elif vix_data.get("skip_sells"):
            # NIFTY trending UP under elevated VIX — only shorts are dangerous
            if new_mode == AdaptiveMode.NORMAL:
                new_mode = AdaptiveMode.DEFENSIVE
            reasons.append(f"VIX={vix_val:.1f} >22 + NIFTY UP → shorts suppressed")
        elif vix_data.get("skip_buys"):
            if new_mode == AdaptiveMode.NORMAL:
                new_mode = AdaptiveMode.DEFENSIVE
            reasons.append(f"VIX={vix_val:.1f} >22 + NIFTY DOWN → longs suppressed")
    except Exception:
        pass

    # ── Signal 2: Market Regime ────────────────────────────────────────
    if new_mode != AdaptiveMode.HALTED:
        try:
            from analysis.regime_detector import (
                get_current_regime, get_regime_details, MarketRegime,
            )
            regime  = get_current_regime()
            details = get_regime_details()
            _state["regime"] = regime.value if regime else "Unknown"

            if regime == MarketRegime.VOLATILE:
                new_mode = AdaptiveMode.HALTED
                reasons.append(
                    f"Regime=VOLATILE (ATR×{details.get('atr_ratio','?')} — stops hit by noise)"
                )
            elif regime == MarketRegime.RANGING and new_mode == AdaptiveMode.NORMAL:
                new_mode = AdaptiveMode.DEFENSIVE
                reasons.append(
                    f"Regime=RANGING (ADX={details.get('adx','?')} — crossovers unreliable)"
                )
        except Exception:
            pass

    # ── Signal 3: Risk State ──────────────────────────────────────────
    if new_mode != AdaptiveMode.HALTED:
        if consecutive_losses >= 2:
            if new_mode == AdaptiveMode.NORMAL:
                new_mode = AdaptiveMode.DEFENSIVE
            reasons.append(f"{consecutive_losses} consecutive losses")

        if day_pnl_pct <= -0.015:   # -1.5% of capital
            if new_mode == AdaptiveMode.NORMAL:
                new_mode = AdaptiveMode.DEFENSIVE
            reasons.append(f"Day P&L={day_pnl_pct:.1%} (below -1.5%)")

    # ── Signal 4: Time of Day ─────────────────────────────────────────
    if new_mode == AdaptiveMode.NORMAL:
        try:
            now_ist = datetime.now(IST)
            if now_ist.hour > 13 or (now_ist.hour == 13 and now_ist.minute >= 30):
                new_mode = AdaptiveMode.DEFENSIVE
                reasons.append(
                    f"Time={now_ist.strftime('%H:%M')} (post-1:30 PM — choppy close)"
                )
        except Exception:
            pass

    # ── Apply mode ────────────────────────────────────────────────────
    reason_str = " | ".join(reasons) if reasons else "All conditions normal"
    old_mode   = _state["mode"]
    _state["mode"]   = new_mode
    _state["reason"] = reason_str

    _apply_params(new_mode)

    if old_mode != new_mode:
        logger.info(
            f"AdaptiveMode CHANGED: {old_mode.value} → {new_mode.value} | {reason_str}"
        )
    else:
        logger.debug(f"AdaptiveMode: {new_mode.value} | {reason_str}")

    return new_mode


# ── Internal ───────────────────────────────────────────────────────────

def _apply_params(mode: AdaptiveMode) -> None:
    """
    Write the appropriate parameter set into cfg.STRATEGY_CONFIGS in-place.

    Because strategies read from cfg.STRATEGY_CONFIGS on every generate_signal()
    call (after _reload_params()), this change takes effect immediately — no
    restart needed.

    HALTED mode does not touch config; the existing VIX/regime checks in
    RiskManager.evaluate() already block entries in that state.
    """
    if mode == AdaptiveMode.DEFENSIVE:
        params = _DEFENSIVE_PARAMS
    else:
        # NORMAL or HALTED: restore baseline
        params = _BASELINE_PARAMS if _BASELINE_PARAMS else {}

    if params:
        cfg.STRATEGY_CONFIGS["rsi_macd_combo"].update(params)
