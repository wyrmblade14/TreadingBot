"""
Strategy 2: RSI + MACD Combo

This strategy combines two indicators that measure different things:
  RSI  → measures whether a stock is overbought or oversold (momentum extreme)
  MACD → measures the direction and strength of the current trend

Why combine them?
  Using one indicator alone leads to many false signals. By requiring BOTH
  to agree, we filter out noise and only trade when two independent signals
  confirm each other.

How it works (plain English):
  We wait for a moment when:
    1. MACD line just crossed above its signal line (upward momentum starting)
    2. RSI is in the "neutral zone" (40–60) — not already overbought

  The RSI filter is crucial: if RSI is already above 70, the stock has
  already moved a lot and we'd be buying at the top. By waiting for RSI
  to be neutral, we catch the move early, before it gets crowded.

Entry rules (ALL must be true):
  ✓ MACD line crossed above Signal line on the current candle
  ✓ RSI is between 40 and 60 (neutral — not extreme in either direction)

Stop-loss: entry_price − (1.5 × ATR)
Target:    entry_price + (3.0 × ATR)  → gives ~2:1 reward:risk ratio

Exit rules:
  ✓ Stop-loss hit
  ✓ Target hit
  ✓ MACD line crosses back below signal line (exit with whatever profit/loss)
  ✓ RSI reaches 75 (stock becoming overbought — take profit before reversal)
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from analysis.regime_detector import get_current_regime, regime_allows_strategy
from config import strategies as cfg
from config.settings import REGIME_FILTER_ENABLED
from indicators.macd import MACDIndicator
from indicators.rsi import RSIIndicator
from strategies.base_strategy import Action, BaseStrategy, Signal


class RSIMACDStrategy(BaseStrategy):
    """
    RSI + MACD combination strategy.
    Buys on MACD bullish crossover when RSI is in the neutral zone.
    """

    def __init__(self) -> None:
        super().__init__(name="rsi_macd_combo")
        params = cfg.STRATEGY_CONFIGS["rsi_macd_combo"]

        self.rsi_buy_min = params["rsi_buy_min"]
        self.rsi_buy_max = params["rsi_buy_max"]
        self.rsi_exit    = params["rsi_exit"]

        self._rsi  = RSIIndicator(
            period=params["rsi_period"],
            overbought=params["rsi_exit"],
        )
        self._macd = MACDIndicator(
            fast=params["macd_fast"],
            slow=params["macd_slow"],
            signal=params["macd_signal"],
        )

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Signal:
        """
        Analyse the latest candles and return a trading signal.

        Args:
            symbol: e.g. "TCS"
            df:     OHLCV DataFrame (needs at least 35 candles for MACD)
        """
        current_price = df["close"].iloc[-1]

        # ── Regime filter ─────────────────────────────────────────────
        # RSI+MACD is allowed in Ranging markets (RSI catches range extremes)
        # but suppressed in Volatile markets where price spikes hit stops randomly.
        if REGIME_FILTER_ENABLED:
            regime = get_current_regime()
            if not regime_allows_strategy(regime, self.name):
                logger.debug(
                    f"RSI+MACD suppressed for {symbol} — market regime: {regime.value}"
                )
                return self.hold_signal(symbol, current_price)

        # Need enough candles for both indicators
        min_candles = self._macd.min_candles + 2
        if len(df) < min_candles:
            return self.hold_signal(symbol, current_price)

        # Get current RSI value
        rsi_val = self._rsi.get_value(df)
        if rsi_val is None:
            return self.hold_signal(symbol, current_price)

        # Get MACD signal and histogram acceleration
        macd_signal = self._macd.get_signal(df)
        macd_val, signal_val, hist_curr = self._macd.get_values(df)
        _, _, hist_prev = self._macd.get_values(df.iloc[:-1]) if len(df) > 1 else (None, None, None)

        # Histogram acceleration: histogram must be positive AND growing for 2 bars.
        # This filters momentum crossovers that immediately stall — a common noise source.
        hist_accelerating = (
            hist_curr is not None
            and hist_prev is not None
            and hist_curr > 0
            and hist_curr > hist_prev
        )

        # ── BUY signal ──────────────────────────────────────────────
        # MACD just crossed up AND RSI is neutral AND histogram is accelerating
        if macd_signal == 1 and self.rsi_buy_min <= rsi_val <= self.rsi_buy_max and hist_accelerating:
            atr       = self._compute_atr(df)
            stop_loss = round(current_price - 1.5 * atr, 2)
            target    = round(current_price + 3.0 * atr, 2)

            logger.info(
                f"RSI+MACD BUY | {symbol} | price={current_price:.2f} "
                f"RSI={rsi_val:.1f} MACD_cross=+1 sl={stop_loss:.2f} target={target:.2f}"
            )
            return Signal(
                symbol=symbol,
                action=Action.BUY,
                entry_price=current_price,
                stop_loss=stop_loss,
                target=target,
                strategy=self.name,
                reason=(
                    f"MACD bullish crossover (MACD={macd_val:.4f} > Signal={signal_val:.4f}), "
                    f"RSI={rsi_val:.1f} in neutral zone [{self.rsi_buy_min}–{self.rsi_buy_max}]"
                ),
            )

        # ── SELL signal (exit) ───────────────────────────────────────
        # MACD just crossed down OR RSI has become overbought
        sell_reason = None
        if macd_signal == -1:
            sell_reason = f"MACD bearish crossover (MACD={macd_val:.4f} < Signal={signal_val:.4f})"
        elif rsi_val >= self.rsi_exit:
            sell_reason = f"RSI overbought exit (RSI={rsi_val:.1f} >= {self.rsi_exit})"

        if sell_reason:
            atr       = self._compute_atr(df)
            stop_loss = round(current_price + 1.5 * atr, 2)
            target    = round(current_price - 3.0 * atr, 2)

            logger.info(f"RSI+MACD SELL | {symbol} | {sell_reason}")
            return Signal(
                symbol=symbol,
                action=Action.SELL,
                entry_price=current_price,
                stop_loss=stop_loss,
                target=target,
                strategy=self.name,
                reason=sell_reason,
            )

        return self.hold_signal(symbol, current_price)
