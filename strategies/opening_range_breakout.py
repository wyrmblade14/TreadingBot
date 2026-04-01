"""
Strategy 3: Opening Range Breakout (ORB)

This is one of the most popular intraday strategies among Indian traders.

Background (why it works):
  Every morning when the NSE market opens at 9:15 AM, there's intense
  activity as traders react to overnight news, global markets, and
  pre-market orders. Prices fluctuate wildly in the first 15 minutes
  as buyers and sellers establish a "fair price" for the day.

  By 9:30 AM, this price discovery phase is usually complete. The range
  between the high and low of 9:15–9:30 AM becomes the "opening range".

  Key insight: Institutional traders (large mutual funds, FIIs) who move
  the market tend to pick a direction and commit to it after 9:30 AM.
  When price breaks out of the opening range with strong volume, it signals
  that institutions have chosen a direction — and we follow them.

How it works (plain English):
  1. Record the highest price (orb_high) and lowest price (orb_low)
     of the first 15 minutes (9:15–9:30 AM).

  2. After 9:30 AM, wait for a 5-minute candle to CLOSE above orb_high
     with above-average volume.

  3. That's our BUY signal — we expect price to continue upward.

  4. If price closes BELOW orb_low instead, that's a SELL signal.

  5. All ORB positions must be exited by 2:30 PM. After that, the
     market often reverses before close and we don't want to be caught.

Entry rules:
  ✓ Current time is after 9:30 AM (opening range complete)
  ✓ Current time is before 2:30 PM (ORB works in the morning)
  ✓ 5-min candle closes above orb_high (BUY) or below orb_low (SELL)
  ✓ Volume on the breakout candle ≥ 1.5× 20-candle average

Stop-loss:
  BUY trade:  orb_low  (if price comes back into the opening range, the
              breakout was false — exit quickly)
  SELL trade: orb_high (same logic, opposite direction)

Target:
  BUY:  orb_high + (orb_high − orb_low) × 1.5  — project the range upward
  SELL: orb_low  − (orb_high − orb_low) × 1.5  — project the range downward

This gives a natural target based on the morning's volatility.
"""

from __future__ import annotations

from datetime import time

import pandas as pd
from loguru import logger

from analysis.regime_detector import get_current_regime, regime_allows_strategy
from config import strategies as cfg
from config.settings import REGIME_FILTER_ENABLED
from indicators.orb import ORBIndicator
from indicators.supertrend import SupertrendIndicator
from indicators.vwap import get_vwap_signal
from strategies.base_strategy import Action, BaseStrategy, Signal

_EXIT_TIME        = time(14, 30)  # No new ORB entries after 2:30 PM
_LATE_ENTRY_CUTOFF = time(11, 0)   # Late breakouts (>11 AM) are usually false — skip them


class ORBStrategy(BaseStrategy):
    """
    Opening Range Breakout strategy.
    Trades breakouts from the 9:15–9:30 AM price range.
    """

    def __init__(self) -> None:
        super().__init__(name="opening_range_breakout")
        params = cfg.STRATEGY_CONFIGS["opening_range_breakout"]

        self.volume_multiplier = params["volume_multiplier"]
        self._indicator = ORBIndicator(
            orb_end_time=time(9, 30),
            volume_multiplier=self.volume_multiplier,
        )
        self._supertrend = SupertrendIndicator(
            period=params["supertrend_period"],
            multiplier=params["supertrend_multiplier"],
        )

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Signal:
        """
        Analyse candle data and return a BUY/SELL/HOLD signal.

        Args:
            symbol: e.g. "INFY"
            df:     OHLCV DataFrame with IST-timezone index (5-minute candles)
        """
        current_price = df["close"].iloc[-1]

        if len(df) < 4:
            return self.hold_signal(symbol, current_price)

        # ── Regime filter ─────────────────────────────────────────────
        # ORB breakouts need follow-through after the range break. In a Ranging
        # market, the breakout quickly reverses back into the range. In a Volatile
        # market, false spikes trigger the breakout with no real commitment.
        if REGIME_FILTER_ENABLED:
            regime = get_current_regime()
            if not regime_allows_strategy(regime, self.name):
                logger.debug(
                    f"ORB suppressed for {symbol} — market regime: {regime.value}"
                )
                return self.hold_signal(symbol, current_price)

        # Check time constraints
        current_time = df.index[-1].time()
        if current_time >= _EXIT_TIME:
            return self.hold_signal(symbol, current_price)
        if current_time >= _LATE_ENTRY_CUTOFF:
            return self.hold_signal(symbol, current_price)

        orb_range = self._indicator.get_range(df)
        if orb_range is None:
            return self.hold_signal(symbol, current_price)

        orb_high, orb_low = orb_range
        orb_width = orb_high - orb_low

        if orb_width <= 0:
            return self.hold_signal(symbol, current_price)

        orb_signal = self._indicator.get_signal(df)
        vwap_bias  = get_vwap_signal(df)   # 0 = daily/unavailable (skip filter)

        # Supertrend trend filter: ensures the breakout aligns with the day's
        # underlying trend. A bullish ORB breakout against a bearish Supertrend
        # often fails — institutions are not actually buying.
        st_signal = self._supertrend.get_signal(df)

        # ── BUY signal ──────────────────────────────────────────────
        # Supertrend bullish (+1) AND VWAP confirms (institutional buy bias)
        if orb_signal == 1 and vwap_bias >= 0 and st_signal >= 0:
            stop_loss      = round(orb_low, 2)
            risk           = current_price - orb_low          # actual risk from entry
            projected_tgt  = orb_high + orb_width * 2.0       # classic ORB 2× extension
            min_2to1_tgt   = current_price + 2.0 * risk       # guarantees 2:1 from entry
            target         = round(max(projected_tgt, min_2to1_tgt), 2)

            logger.info(
                f"ORB BUY | {symbol} | price={current_price:.2f} "
                f"orb_high={orb_high:.2f} orb_low={orb_low:.2f} "
                f"sl={stop_loss:.2f} target={target:.2f}"
            )
            return Signal(
                symbol=symbol,
                action=Action.BUY,
                entry_price=current_price,
                stop_loss=stop_loss,
                target=target,
                strategy=self.name,
                reason=(
                    f"Breakout above ORB high ({orb_high:.2f}) | "
                    f"ORB range: [{orb_low:.2f} – {orb_high:.2f}] | "
                    f"width={orb_width:.2f}"
                ),
            )

        # ── SELL signal ──────────────────────────────────────────────
        # Supertrend bearish (-1) or neutral (0 = not enough data, allow through)
        if orb_signal == -1 and vwap_bias <= 0 and st_signal <= 0:
            stop_loss     = round(orb_high, 2)
            risk          = orb_high - current_price          # actual risk from entry
            projected_tgt = orb_low - orb_width * 2.0         # classic ORB 2× extension
            min_2to1_tgt  = current_price - 2.0 * risk        # guarantees 2:1 from entry
            target        = round(min(projected_tgt, min_2to1_tgt), 2)

            logger.info(
                f"ORB SELL | {symbol} | price={current_price:.2f} "
                f"orb_low={orb_low:.2f} sl={stop_loss:.2f} target={target:.2f}"
            )
            return Signal(
                symbol=symbol,
                action=Action.SELL,
                entry_price=current_price,
                stop_loss=stop_loss,
                target=target,
                strategy=self.name,
                reason=(
                    f"Breakdown below ORB low ({orb_low:.2f}) | "
                    f"ORB range: [{orb_low:.2f} – {orb_high:.2f}]"
                ),
            )

        return self.hold_signal(symbol, current_price)
