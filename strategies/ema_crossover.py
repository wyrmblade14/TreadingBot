"""
Strategy 1: EMA Crossover

This is the simplest and most beginner-friendly strategy in the bot.

How it works (plain English):
  Imagine two lines drawn on a price chart — a "fast" line that reacts
  quickly to price changes and a "slow" line that is smoother.

  When the fast line crosses UP through the slow line, it means short-term
  momentum is turning bullish → we BUY.

  When the fast line crosses DOWN through the slow line, it means momentum
  is weakening → we SELL and exit.

  We add three filters to avoid bad trades:
    1. Trend filter: Supertrend(10, 3.0) must be bullish (price above the
       volatility-adjusted trend band). This replaces the simpler 50-EMA filter
       because Supertrend adapts to market volatility — it avoids false signals
       in choppy markets by widening its bands automatically.
    2. Volume filter: The crossover must happen on above-average volume.
       Low-volume crossovers are often false signals.
    3. VWAP filter: Only buy above VWAP (institutional buy bias), only sell
       below VWAP. Filters out low-conviction moves against the day's flow.
       Skipped automatically for daily candles (VWAP is intraday only).

Entry rules (ALL must be true):
  ✓ 9-EMA just crossed above 21-EMA on the current candle
  ✓ Supertrend is bullish (replaces the 50-EMA trend filter)
  ✓ Current candle's volume ≥ 1.5× the 20-candle average volume
  ✓ Price is above VWAP (BUY) or below VWAP (SELL) — skipped for daily data

Stop-loss: entry_price − (1.5 × ATR)
  ATR = how much the stock typically moves in a candle.
  We place the stop just below "normal" volatility so routine fluctuations
  don't knock us out, but a genuine reversal does.

Target: entry_price + (3.0 × ATR)
  This gives a reward-to-risk ratio of exactly 2:1 (3.0 / 1.5), meeting our minimum.

Exit rules:
  ✓ Stop-loss hit (automatic)
  ✓ Target hit (automatic)
  ✓ 9-EMA crosses back below 21-EMA (trend reversal)
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from analysis.regime_detector import get_current_regime, regime_allows_strategy
from config import strategies as cfg
from config.settings import REGIME_FILTER_ENABLED
from indicators.ema import EMAIndicator
from indicators.first_candle import get_first_candle_levels
from indicators.supertrend import SupertrendIndicator
from indicators.vwap import get_vwap_signal
from strategies.base_strategy import Action, BaseStrategy, Signal


class EMACrossoverStrategy(BaseStrategy):
    """
    EMA 9/21/50 crossover strategy with volume and trend filters.
    """

    def __init__(self) -> None:
        super().__init__(name="ema_crossover")
        params = cfg.STRATEGY_CONFIGS["ema_crossover"]

        self.short_period      = params["short_period"]
        self.long_period       = params["long_period"]
        self.trend_period      = params["trend_period"]
        self.volume_multiplier = params["volume_multiplier"]

        self._indicator = EMAIndicator(
            short_period=self.short_period,
            long_period=self.long_period,
            trend_period=self.trend_period,
            volume_multiplier=self.volume_multiplier,
        )
        self._supertrend = SupertrendIndicator(
            period=params["supertrend_period"],
            multiplier=params["supertrend_multiplier"],
        )
        self.use_first_candle_filter = params.get("use_first_candle_filter", False)

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Signal:
        """
        Analyse the latest candles and return a BUY, SELL, or HOLD signal.

        Args:
            symbol: e.g. "RELIANCE"
            df:     OHLCV DataFrame (5-minute candles, at least 55 candles needed)
        """
        current_price = df["close"].iloc[-1]

        # ── Regime filter ─────────────────────────────────────────────
        # EMA Crossover needs a trending market — crossovers in a ranging
        # market are noisy and frequently reverse. Suppress on RANGING + VOLATILE.
        if REGIME_FILTER_ENABLED:
            regime = get_current_regime()
            if not regime_allows_strategy(regime, self.name):
                logger.debug(
                    f"EMA Crossover suppressed for {symbol} — market regime: {regime.value}"
                )
                return self.hold_signal(symbol, current_price)

        # Need enough candles for both EMAs and Supertrend
        min_needed = max(self.trend_period + 2, self._supertrend.min_candles)
        if len(df) < min_needed:
            return self.hold_signal(symbol, current_price)

        result = self._indicator.compute(df)

        fast_col  = f"ema_{self.short_period}"
        slow_col  = f"ema_{self.long_period}"
        trend_col = f"ema_{self.trend_period}"

        curr = result.iloc[-1]
        prev = result.iloc[-2]

        # Guard NaN
        if any(pd.isna([curr[fast_col], curr[slow_col], curr[trend_col]])):
            return self.hold_signal(symbol, current_price)

        fast_now, fast_prev  = curr[fast_col], prev[fast_col]
        slow_now, slow_prev  = curr[slow_col], prev[slow_col]
        trend_ema            = curr[trend_col]   # kept for logging/display
        vol_avg              = curr.get("vol_avg20", 0)
        volume_ok            = vol_avg == 0 or curr["volume"] >= self.volume_multiplier * vol_avg

        # Supertrend trend filter — replaces the 50-EMA price comparison.
        # Supertrend adapts to volatility: in choppy markets its bands widen so
        # small EMA crossovers don't pass the filter; in strong trends it sits
        # close to price confirming the move quickly.
        supertrend_bullish = self._supertrend.is_bullish(df)
        supertrend_val     = self._supertrend.get_value(df)

        # VWAP filter: 0 means daily data (skip), +1 bullish, -1 bearish
        vwap_bias = get_vwap_signal(df)

        # ── First candle anchor filter ───────────────────────────────
        # BUY only when price is above the 9:15 candle high (bullish day confirmed).
        # SELL only when price is below the 9:15 candle low (bearish day confirmed).
        # Returns None for daily data or before 9:20 AM — skipped gracefully.
        first_candle_ok_buy  = True
        first_candle_ok_sell = True
        if self.use_first_candle_filter:
            fc_levels = get_first_candle_levels(df)
            if fc_levels is not None:
                fc_high, fc_low = fc_levels
                first_candle_ok_buy  = current_price > fc_high
                first_candle_ok_sell = current_price < fc_low

        # ── BUY signal ──────────────────────────────────────────────
        bullish_cross = (fast_prev < slow_prev) and (fast_now > slow_now)
        vwap_ok_buy   = vwap_bias >= 0   # above VWAP or daily (no filter)

        if bullish_cross and supertrend_bullish and volume_ok and vwap_ok_buy and first_candle_ok_buy:
            atr       = self._compute_atr(df)
            stop_loss = round(current_price - 1.5 * atr, 2)
            target    = round(current_price + 3.0 * atr, 2)  # 3/1.5 = 2:1 RR

            st_str = f"{supertrend_val:.2f}" if supertrend_val else "n/a"
            logger.info(
                f"EMA BUY | {symbol} | price={current_price:.2f} "
                f"supertrend={st_str} sl={stop_loss:.2f} target={target:.2f}"
            )
            return Signal(
                symbol=symbol,
                action=Action.BUY,
                entry_price=current_price,
                stop_loss=stop_loss,
                target=target,
                strategy=self.name,
                reason=(
                    f"EMA{self.short_period} ({fast_now:.2f}) crossed above "
                    f"EMA{self.long_period} ({slow_now:.2f}), "
                    f"Supertrend bullish ({st_str}), "
                    f"volume confirmed"
                ),
            )

        # ── SELL signal (exit / short) ───────────────────────────────
        bearish_cross = (fast_prev > slow_prev) and (fast_now < slow_now)
        vwap_ok_sell  = vwap_bias <= 0   # below VWAP or daily (no filter)

        if bearish_cross and vwap_ok_sell and first_candle_ok_sell:
            atr       = self._compute_atr(df)
            stop_loss = round(current_price + 1.5 * atr, 2)
            target    = round(current_price - 3.0 * atr, 2)  # 3/1.5 = 2:1 RR

            logger.info(
                f"EMA SELL | {symbol} | price={current_price:.2f}"
            )
            return Signal(
                symbol=symbol,
                action=Action.SELL,
                entry_price=current_price,
                stop_loss=stop_loss,
                target=target,
                strategy=self.name,
                reason=(
                    f"EMA{self.short_period} ({fast_now:.2f}) crossed below "
                    f"EMA{self.long_period} ({slow_now:.2f})"
                ),
            )

        return self.hold_signal(symbol, current_price)
