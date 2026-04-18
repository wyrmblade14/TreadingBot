"""
Strategy 5: VWAP Bounce

What is VWAP?
  VWAP (Volume-Weighted Average Price) is the average price paid for a stock
  during the day, weighted by volume. It's the single most-watched intraday
  level by institutional traders (mutual funds, FIIs, prop desks).

  When price pulls back to VWAP and holds:
    - Institutions step in to buy (they want the "fair price" of the day)
    - Volume typically surges at the VWAP touch as big buyers accumulate
    - Price then bounces back toward the day's high

  This is one of the most reliable intraday setups in liquid markets like NSE.

Why it wasn't captured by existing strategies:
  - EMA Crossover fires on 9/21 EMA cross — often *after* the VWAP bounce
  - RSI+MACD needs a full MACD cycle — adds 26-bar lag
  - ORB fires only once per day at the range breakout
  - None of these target the "dip to VWAP" pattern specifically

How it works (plain English):
  We wait for a moment when:
    1. Price has pulled back to within 0.3% of VWAP (institutional support)
    2. EMA9 > EMA21 (short-term uptrend — we're buying INTO the trend, not against it)
    3. RSI(6) is between 35–65 (not already overbought from the bounce)
    4. Time is between 9:45 AM and 1:30 PM (ORB settled, before choppy close)
    5. Volume on this candle is above the 20-bar average (confirmation)

  For short entries (bearish VWAP rejection):
    1. Price bounced up to VWAP but was rejected (closed below after touching)
    2. EMA9 < EMA21 (downtrend)
    3. RSI(6) between 35–65
    4. Same time and volume filters

Entry:  current close (VWAP touch confirmed on close)
SL:     1.5 × ATR below entry (BUY) / above entry (SELL)
Target: 2.0 × SL distance (2:1 reward:risk)

Best market conditions:
  TRENDING days (ADX > 25) with clear directional bias.
  On RANGING days, VWAP is crossed repeatedly — signals are noisy.
  The regime filter suppresses this strategy in RANGING markets.
"""

from __future__ import annotations

import math
from datetime import time

import pandas as pd
import ta
from loguru import logger

from analysis.regime_detector import get_current_regime, regime_allows_strategy
from config import strategies as cfg
from config.settings import IST, REGIME_FILTER_ENABLED
from indicators.vwap import compute_vwap
from strategies.base_strategy import Action, BaseStrategy, Signal


class VWAPBounceStrategy(BaseStrategy):
    """
    VWAP Bounce — buys when price pulls back to VWAP in an uptrend,
    shorts when price rejects at VWAP in a downtrend.
    """

    # Strategy allowed in RANGING regime? No — VWAP is crossed too often.
    # Add to regime_detector's _RANGING_ALLOWED set to enable if desired.
    _ENTRY_START = time(9, 45)   # after ORB settles
    _ENTRY_END   = time(13, 30)  # before choppy afternoon close

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(name="vwap_bounce")
        self.default_params = params or cfg.STRATEGY_CONFIGS.get("vwap_bounce", {})

    def _get_config(self, symbol: str) -> dict:
        """Return merged config: global defaults (incl. adaptive changes) + per-symbol overrides."""
        base = dict(cfg.STRATEGY_CONFIGS.get(self.name, {}))
        try:
            from learning.param_optimizer import load_optimized_params
            optimized = load_optimized_params(self.name, symbol)
            if optimized:
                base.update(optimized)
        except Exception:
            pass
        return base

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Signal:
        config = self._get_config(symbol)

        vwap_tolerance = config.get("vwap_tolerance_pct", 0.003)
        rsi_min        = config.get("rsi_min", 35)
        rsi_max        = config.get("rsi_max", 65)
        volume_mult    = config.get("volume_multiplier", 1.2)
        min_sl_pct     = config.get("min_sl_pct", 0.0075)
        rsi_period     = config.get("rsi_period", 6)

        current_price = df["close"].iloc[-1]

        # ── Regime filter ────────────────────────────────────────────
        # VWAP bounce works in trending markets; in ranging markets price
        # straddles VWAP constantly and generates too many false signals.
        if REGIME_FILTER_ENABLED:
            regime = get_current_regime()
            if not regime_allows_strategy(regime, self.name):
                return self.hold_signal(symbol, current_price)

        # Need enough candles for EMA(21) + RSI(6) + ATR(14)
        if len(df) < 30:
            return self.hold_signal(symbol, current_price)

        # ── Time filter ───────────────────────────────────────────────
        # Use the last candle's timestamp so backtests and replay work correctly.
        # Fall back to wall-clock time only when the DataFrame has no timezone info.
        try:
            import pytz
            candle_ts = df.index[-1]
            if candle_ts.tzinfo is None:
                candle_ts = candle_ts.tz_localize(IST)
            else:
                candle_ts = candle_ts.tz_convert(IST)
            candle_time = candle_ts.time()
        except Exception:
            from datetime import datetime as _dt
            candle_time = _dt.now(IST).time()

        if not (self._ENTRY_START <= candle_time <= self._ENTRY_END):
            return self.hold_signal(symbol, current_price)

        # ── Compute indicators ────────────────────────────────────────
        close = df["close"]

        try:
            vwap_series = compute_vwap(df)
            vwap_val    = float(vwap_series.iloc[-1])
            if math.isnan(vwap_val):
                return self.hold_signal(symbol, current_price)
        except Exception:
            return self.hold_signal(symbol, current_price)

        ema9_val  = float(ta.trend.EMAIndicator(close, window=9).ema_indicator().iloc[-1])
        ema21_val = float(ta.trend.EMAIndicator(close, window=21).ema_indicator().iloc[-1])
        if math.isnan(ema9_val) or math.isnan(ema21_val):
            return self.hold_signal(symbol, current_price)

        rsi_val = float(ta.momentum.RSIIndicator(close, window=rsi_period).rsi().iloc[-1])
        if math.isnan(rsi_val):
            return self.hold_signal(symbol, current_price)

        # Volume filter: this candle must be above-average volume
        if "volume" in df.columns and len(df) >= 20:
            vol_avg = float(df["volume"].rolling(20).mean().iloc[-1])
            vol_now = float(df["volume"].iloc[-1])
            vol_ok  = vol_now >= vol_avg * volume_mult
        else:
            vol_ok = True  # skip if volume data unavailable

        ema_bullish = ema9_val > ema21_val
        ema_bearish = ema9_val < ema21_val

        # How close is current price to VWAP?
        dist_pct = abs(current_price - vwap_val) / vwap_val

        atr = self._compute_atr(df)

        # ── VWAP cross confirmation ───────────────────────────────────
        # Require the PREVIOUS candle to have been on the opposite side of VWAP.
        # e.g. BUY: prev candle closed below VWAP, current candle closed above.
        # This confirms the bounce has already started — not just approaching.
        prev_close_price = float(df["close"].iloc[-2]) if len(df) >= 2 else current_price
        try:
            prev_vwap = float(compute_vwap(df.iloc[:-1]).iloc[-1])
        except Exception:
            prev_vwap = vwap_val

        bounced_up   = prev_close_price < prev_vwap and current_price >= vwap_val
        rejected_dn  = prev_close_price > prev_vwap and current_price <= vwap_val

        # ── BUY: price pulled back to VWAP, uptrend confirmed ─────────
        if (
            dist_pct <= vwap_tolerance
            and bounced_up                       # confirmed cross: was below, now above
            and ema_bullish                      # short-term uptrend
            and rsi_min <= rsi_val <= rsi_max
            and vol_ok
        ):
            sl_dist  = max(1.5 * atr, current_price * min_sl_pct)
            tgt_dist = sl_dist * 2.0
            stop_loss = round(current_price - sl_dist, 2)
            target    = round(current_price + tgt_dist, 2)

            logger.info(
                f"VWAP Bounce BUY | {symbol} | price={current_price:.2f} "
                f"VWAP={vwap_val:.2f} dist={dist_pct:.3%} "
                f"RSI={rsi_val:.1f} EMA9>{ema21_val:.1f}"
            )
            return Signal(
                symbol=symbol,
                action=Action.BUY,
                entry_price=current_price,
                stop_loss=stop_loss,
                target=target,
                strategy=self.name,
                reason=(
                    f"VWAP pullback bounce: price={current_price:.2f} within "
                    f"{dist_pct:.2%} of VWAP={vwap_val:.2f}, "
                    f"EMA9({ema9_val:.1f}) > EMA21({ema21_val:.1f}), RSI={rsi_val:.1f}"
                ),
            )

        # ── SELL: price rejected at VWAP, downtrend confirmed ─────────
        if (
            dist_pct <= vwap_tolerance
            and rejected_dn                      # confirmed cross: was above, now below
            and ema_bearish                      # short-term downtrend
            and rsi_min <= rsi_val <= rsi_max
            and vol_ok
        ):
            sl_dist  = max(1.5 * atr, current_price * min_sl_pct)
            tgt_dist = sl_dist * 2.0
            stop_loss = round(current_price + sl_dist, 2)
            target    = round(current_price - tgt_dist, 2)

            logger.info(
                f"VWAP Rejection SELL | {symbol} | price={current_price:.2f} "
                f"VWAP={vwap_val:.2f} dist={dist_pct:.3%} "
                f"RSI={rsi_val:.1f} EMA9<{ema21_val:.1f}"
            )
            return Signal(
                symbol=symbol,
                action=Action.SELL,
                entry_price=current_price,
                stop_loss=stop_loss,
                target=target,
                strategy=self.name,
                reason=(
                    f"VWAP rejection: price={current_price:.2f} within "
                    f"{dist_pct:.2%} of VWAP={vwap_val:.2f}, "
                    f"EMA9({ema9_val:.1f}) < EMA21({ema21_val:.1f}), RSI={rsi_val:.1f}"
                ),
            )

        return self.hold_signal(symbol, current_price)
