"""
Strategy 4: Bollinger Band Mean Reversion

How it works (plain English):
  Bollinger Bands are three lines drawn around price:
    - Middle band: 20-period Simple Moving Average (the "average" price)
    - Upper band:  Middle + 2 standard deviations (unusually HIGH)
    - Lower band:  Middle - 2 standard deviations (unusually LOW)

  By statistics, roughly 95% of all closing prices stay inside the bands.
  When price reaches an outer band it is at an extreme — and tends to
  "revert to the mean" (return toward the middle band).

  This strategy bets on that reversion:
    BUY  when price touches the lower band AND RSI < 35 (confirms oversold)
         → expect a bounce back toward the middle band
    SELL when price touches the upper band AND RSI > 65 (confirms overbought)
         → expect a pull-back toward the middle band

  Key difference from the other three strategies:
    EMA Crossover, ORB, and Gap & Go are all MOMENTUM strategies —
    they trade WITH a strong move. This strategy is COUNTER-TREND —
    it trades AGAINST a short-term extreme, expecting a snap-back.
    That is why it works best in RANGING markets where momentum
    strategies struggle (and is allowed to fire in those conditions).

Entry rules — BUY (ALL must be true):
  ✓ Close price ≤ lower Bollinger Band (price at an extreme low)
  ✓ RSI < 35 (momentum confirms the stock is genuinely oversold)

Entry rules — SELL (ALL must be true):
  ✓ Close price ≥ upper Bollinger Band (price at an extreme high)
  ✓ RSI > 65 (momentum confirms the stock is genuinely overbought)

Stop-loss: entry ∓ (1.5 × ATR)
  Placed beyond normal daily noise; ATR adapts to current volatility.

Target: middle band (20-period SMA), with a minimum of entry ± (3.0 × ATR)
  The middle band is the natural reversion target. The 3.0 × ATR floor
  guarantees the reward-to-risk ratio never falls below 2:1 (3.0 / 1.5).

Regime filter:
  TRENDING  → allowed (pullback-to-mean entries work in all conditions)
  RANGING   → allowed (this is where mean reversion shines most)
  VOLATILE  → suppressed (bands blow out; "extreme" and "target" become
              unreachable, and the bounce may never come)
  UNKNOWN   → allowed (fail-safe)
"""

from __future__ import annotations

import pandas as pd
import ta
from loguru import logger

from analysis.regime_detector import get_current_regime, regime_allows_strategy
from config import strategies as cfg
from config.settings import REGIME_FILTER_ENABLED
from indicators.rsi import RSIIndicator
from strategies.base_strategy import Action, BaseStrategy, Signal


class BBMeanReversionStrategy(BaseStrategy):
    """
    Bollinger Band Mean Reversion strategy.
    Buys near the lower band when RSI confirms oversold conditions;
    sells near the upper band when RSI confirms overbought conditions.
    Targets the middle band (20-period SMA) with a minimum 2:1 RR.
    """

    def __init__(self) -> None:
        super().__init__(name="bb_mean_reversion")
        params = cfg.STRATEGY_CONFIGS["bb_mean_reversion"]

        self.bb_period      = params["bb_period"]        # SMA window for middle band
        self.bb_std_dev     = params["bb_std_dev"]       # Band width in standard deviations
        self.rsi_period     = params["rsi_period"]       # RSI lookback
        self.rsi_oversold   = params["rsi_oversold"]     # RSI below this → oversold (BUY filter)
        self.rsi_overbought = params["rsi_overbought"]   # RSI above this → overbought (SELL filter)

        self._rsi = RSIIndicator(period=self.rsi_period)

    # ── Public API ────────────────────────────────────────────────────

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Signal:
        """
        Analyse the latest candles and return a BUY, SELL, or HOLD signal.

        Args:
            symbol: e.g. "RELIANCE"
            df:     OHLCV DataFrame — at least 25 candles needed.
                    Works on any timeframe (5-min, hourly, daily).
        """
        current_price = df["close"].iloc[-1]

        # ── Regime filter ────────────────────────────────────────────
        # Mean reversion is allowed in both TRENDING and RANGING regimes.
        # Suppressed only in VOLATILE (bands blow out — no reliable target).
        if REGIME_FILTER_ENABLED:
            regime = get_current_regime()
            if not regime_allows_strategy(regime, self.name):
                logger.debug(
                    f"BB Mean Reversion suppressed for {symbol} — market regime: {regime.value}"
                )
                return self.hold_signal(symbol, current_price)

        # ── Data sufficiency check ────────────────────────────────────
        min_needed = max(self.bb_period, self.rsi_period) + 5
        if len(df) < min_needed:
            return self.hold_signal(symbol, current_price)

        # ── Compute Bollinger Bands ───────────────────────────────────
        bb = ta.volatility.BollingerBands(
            df["close"],
            window=self.bb_period,
            window_dev=self.bb_std_dev,
            fillna=False,
        )
        upper_band  = bb.bollinger_hband().iloc[-1]
        middle_band = bb.bollinger_mavg().iloc[-1]
        lower_band  = bb.bollinger_lband().iloc[-1]

        if pd.isna(upper_band) or pd.isna(middle_band) or pd.isna(lower_band):
            return self.hold_signal(symbol, current_price)

        # ── Compute RSI ───────────────────────────────────────────────
        rsi_val = self._rsi.get_value(df)
        if rsi_val is None:
            return self.hold_signal(symbol, current_price)

        atr = self._compute_atr(df)

        # ── BUY signal ────────────────────────────────────────────────
        # Price has reached or broken below the lower band — statistically rare.
        # RSI < rsi_oversold confirms the move is genuinely oversold.
        # We expect a bounce back toward the middle band (mean reversion).
        at_lower_band = current_price <= lower_band
        rsi_oversold  = rsi_val < self.rsi_oversold

        if at_lower_band and rsi_oversold:
            stop_loss = round(current_price - 1.5 * atr, 2)
            # Target = middle band, but never less than 2:1 RR
            min_target = round(current_price + 3.0 * atr, 2)
            target     = round(max(middle_band, min_target), 2)

            logger.info(
                f"BB BUY | {symbol} | price={current_price:.2f} "
                f"lower={lower_band:.2f} mid={middle_band:.2f} "
                f"rsi={rsi_val:.1f} sl={stop_loss:.2f} target={target:.2f}"
            )
            return Signal(
                symbol=symbol,
                action=Action.BUY,
                entry_price=current_price,
                stop_loss=stop_loss,
                target=target,
                strategy=self.name,
                reason=(
                    f"Price ({current_price:.2f}) at/below lower BB ({lower_band:.2f}), "
                    f"RSI={rsi_val:.1f} (oversold < {self.rsi_oversold}). "
                    f"Target: mean reversion to middle band ({middle_band:.2f})"
                ),
            )

        # ── SELL signal ───────────────────────────────────────────────
        # Price has reached or broken above the upper band — statistically rare.
        # RSI > rsi_overbought confirms the move is genuinely overbought.
        # We expect a pull-back toward the middle band.
        at_upper_band  = current_price >= upper_band
        rsi_overbought = rsi_val > self.rsi_overbought

        if at_upper_band and rsi_overbought:
            stop_loss  = round(current_price + 1.5 * atr, 2)
            # Target = middle band, but never less than 2:1 RR on the downside
            min_target = round(current_price - 3.0 * atr, 2)
            target     = round(min(middle_band, min_target), 2)

            logger.info(
                f"BB SELL | {symbol} | price={current_price:.2f} "
                f"upper={upper_band:.2f} mid={middle_band:.2f} "
                f"rsi={rsi_val:.1f} sl={stop_loss:.2f} target={target:.2f}"
            )
            return Signal(
                symbol=symbol,
                action=Action.SELL,
                entry_price=current_price,
                stop_loss=stop_loss,
                target=target,
                strategy=self.name,
                reason=(
                    f"Price ({current_price:.2f}) at/above upper BB ({upper_band:.2f}), "
                    f"RSI={rsi_val:.1f} (overbought > {self.rsi_overbought}). "
                    f"Target: mean reversion to middle band ({middle_band:.2f})"
                ),
            )

        return self.hold_signal(symbol, current_price)
