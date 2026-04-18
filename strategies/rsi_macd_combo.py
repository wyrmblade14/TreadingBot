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

import math

import pandas as pd
import ta
from loguru import logger

from analysis.regime_detector import get_current_regime, regime_allows_strategy
from config import strategies as cfg
from config.settings import REGIME_FILTER_ENABLED
from indicators.macd import MACDIndicator
from indicators.rsi import RSIIndicator
from indicators.vwap import compute_vwap
from strategies.base_strategy import Action, BaseStrategy, Signal


class RSIMACDStrategy(BaseStrategy):
    """
    RSI + MACD combination strategy.
    Buys on MACD bullish crossover when RSI is in the neutral zone.
    """

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(name="rsi_macd_combo")
        self.default_params = params or cfg.STRATEGY_CONFIGS["rsi_macd_combo"]
        # Cache: symbol → (indicators_dict, config_dict)
        self._symbol_cache: dict[str, tuple[dict, dict]] = {}
        # Dedup: symbol → last crossover bar index (persists independently of param cache)
        self._last_crossover_bar: dict[str, object] = {}

    def _get_config(self, symbol: str) -> dict:
        """Return merged config: global defaults (incl. adaptive changes) + per-symbol overrides."""
        base = dict(cfg.STRATEGY_CONFIGS[self.name])
        try:
            from learning.param_optimizer import load_optimized_params
            optimized = load_optimized_params(self.name, symbol)
            if optimized:
                base.update(optimized)
        except Exception:
            pass
        return base

    def _init_indicators(self, params: dict) -> dict:
        return {
            "rsi": RSIIndicator(
                period=params["rsi_period"],
                overbought=params["rsi_exit"],
            ),
            "macd": MACDIndicator(
                fast=params["macd_fast"],
                slow=params["macd_slow"],
                signal=params["macd_signal"],
            ),
        }

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Signal:
        """
        Analyse the latest candles and return a trading signal.

        Args:
            symbol: e.g. "TCS"
            df:     OHLCV DataFrame (needs at least 35 candles for MACD)
        """
        config = self._get_config(symbol)

        if symbol not in self._symbol_cache or self._symbol_cache[symbol][1] != config:
            self._symbol_cache[symbol] = (self._init_indicators(config), config)
        inds, params = self._symbol_cache[symbol]

        rsi_buy_min           = params["rsi_buy_min"]
        rsi_buy_max           = params["rsi_buy_max"]
        rsi_sell_min          = params.get("rsi_sell_min", 40)
        require_ema_alignment = params.get("require_ema_alignment", True)
        use_vwap_filter       = params.get("use_vwap_filter", True)
        min_sl_pct            = params.get("min_sl_pct", 0.0075)

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
        min_candles = inds["macd"].min_candles + 2
        if len(df) < min_candles:
            return self.hold_signal(symbol, current_price)

        # Get current RSI value
        rsi_val = inds["rsi"].get_value(df)
        if rsi_val is None:
            return self.hold_signal(symbol, current_price)

        # Get MACD signal and histogram acceleration
        macd_signal = inds["macd"].get_signal(df)

        # ── Crossover dedup ──────────────────────────────────────────
        # A crossover is a one-candle event.  When yfinance returns stale/
        # cached data the same closing candle re-appears every minute, causing
        # the crossover condition to re-fire hundreds of times on a single bar.
        # We track the last bar index (timestamp) that produced a crossover and
        # suppress re-fires on the same bar.
        if macd_signal != 0:
            bar_key = df.index[-1]
            if self._last_crossover_bar.get(symbol) == bar_key:
                logger.debug(
                    f"RSI+MACD {'BUY' if macd_signal == 1 else 'SELL'} skipped | "
                    f"{symbol} | duplicate crossover on same bar {bar_key}"
                )
                macd_signal = 0
            else:
                self._last_crossover_bar[symbol] = bar_key
        macd_val, signal_val, hist_curr = inds["macd"].get_values(df)
        _, _, hist_prev = inds["macd"].get_values(df.iloc[:-1]) if len(df) > 1 else (None, None, None)

        # Histogram acceleration: histogram must be positive AND growing for 2 bars.
        # This filters momentum crossovers that immediately stall — a common noise source.
        hist_accelerating = (
            hist_curr is not None
            and hist_prev is not None
            and hist_curr > 0
            and hist_curr > hist_prev
        )

        # ── EMA trend alignment ──────────────────────────────────────
        # EMA9 vs EMA21 tells us the current short-term trend direction.
        # In an uptrending stock (EMA9 > EMA21), MACD bearish crossovers are
        # just pullback noise — they resolve upward and hit SL if shorted.
        # Safety: if EMA can't be computed (< 21 candles), reject the signal —
        # early-morning trades on thin data cause the most random losses.
        ema_bullish = ema_bearish = True  # default: allow if filter disabled
        if require_ema_alignment:
            if len(df) < 21:
                return self.hold_signal(symbol, current_price)
            close = df["close"]
            ema9_val  = ta.trend.EMAIndicator(close, window=9).ema_indicator().iloc[-1]
            ema21_val = ta.trend.EMAIndicator(close, window=21).ema_indicator().iloc[-1]
            if math.isnan(ema9_val) or math.isnan(ema21_val):
                return self.hold_signal(symbol, current_price)
            ema_bullish = float(ema9_val) > float(ema21_val)
            ema_bearish = float(ema9_val) < float(ema21_val)

        # ── VWAP direction filter ────────────────────────────────────
        # VWAP (Volume-Weighted Average Price) is the institutional fair value
        # for the day.  Retail price above VWAP = market willing to pay up →
        # valid to short.  Price below VWAP = market already weak → shorting
        # further weakness is low-quality; wait for a bounce first.
        # Lesson from 2026-04-02: every single losing short was entered BELOW
        # VWAP, meaning the stock had already fallen and was due for a bounce.
        vwap_val = None
        if use_vwap_filter:
            try:
                vwap_series = compute_vwap(df)
                v = vwap_series.iloc[-1]
                if not math.isnan(float(v)):
                    vwap_val = float(v)
            except Exception:
                pass   # non-fatal: allow trade if VWAP unavailable

        # ── BUY signal ──────────────────────────────────────────────
        # MACD crossed up AND RSI neutral AND histogram accelerating
        if macd_signal == 1 and rsi_buy_min <= rsi_val <= rsi_buy_max and hist_accelerating:
            if not ema_bullish:
                logger.debug(f"RSI+MACD BUY skipped | {symbol} | EMA downtrend → no long")
                return self.hold_signal(symbol, current_price)

            # VWAP: only buy when price is below VWAP (buying relative weakness)
            if vwap_val is not None and current_price > vwap_val:
                logger.debug(
                    f"RSI+MACD BUY skipped | {symbol} | price={current_price:.2f} > VWAP={vwap_val:.2f}"
                )
                return self.hold_signal(symbol, current_price)

            atr = self._compute_atr(df)
            # Minimum SL distance: at least min_sl_pct of price to avoid noise hits
            sl_dist  = max(1.5 * atr, current_price * min_sl_pct)
            tgt_dist = sl_dist * 2.0   # 2:1 reward:risk
            stop_loss = round(current_price - sl_dist, 2)
            target    = round(current_price + tgt_dist, 2)

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
                    f"RSI={rsi_val:.1f} in neutral zone [{rsi_buy_min}–{rsi_buy_max}]"
                ),
            )

        # ── SELL signal ─────────────────────────────────────────────
        # Only MACD bearish crossover triggers a new short entry.
        #
        # RSI overbought (≥ rsi_exit) is intentionally NOT used here.
        # RSI ≥ 80 means strong upward momentum — entering a short against that
        # momentum leads to immediate stop-outs (confirmed by every Apr-02 RSI
        # overbought short: IDs 19–24 all lost ₹400–₹1,700 each).
        # The correct place to act on RSI extremes is exit monitoring for open
        # longs — not a fresh SHORT entry.
        sell_reason = None
        if macd_signal == -1:
            sell_reason = f"MACD bearish crossover (MACD={macd_val:.4f} < Signal={signal_val:.4f})"

        if sell_reason:
            if not ema_bearish:
                logger.debug(f"RSI+MACD SELL skipped | {symbol} | EMA uptrend → no short")
                return self.hold_signal(symbol, current_price)

            # RSI oversold gate: if RSI already very low, stock has fallen hard
            # and is primed for a bounce — entering a short here is chasing.
            # ICICIBANK RSI=16.2, AXISBANK RSI=16.5 on 2026-04-02 were the clearest
            # examples: both already crashed and promptly reversed upward.
            if rsi_val < rsi_sell_min:
                logger.debug(
                    f"RSI+MACD SELL skipped | {symbol} | RSI={rsi_val:.1f} < {rsi_sell_min} "
                    f"(already oversold — likely to bounce)"
                )
                return self.hold_signal(symbol, current_price)

            # VWAP: only short when price is above VWAP (shorting relative strength)
            # No band for SELL — shorting into weakness below VWAP leads to bounce stop-outs
            if vwap_val is not None and current_price < vwap_val:
                logger.debug(
                    f"RSI+MACD SELL skipped | {symbol} | price={current_price:.2f} < VWAP={vwap_val:.2f} "
                    f"(shorting below VWAP = chasing weakness)"
                )
                return self.hold_signal(symbol, current_price)

            atr = self._compute_atr(df)
            sl_dist  = max(1.5 * atr, current_price * min_sl_pct)
            tgt_dist = sl_dist * 2.0
            stop_loss = round(current_price + sl_dist, 2)
            target    = round(current_price - tgt_dist, 2)

            logger.info(f"RSI+MACD SELL | {symbol} | {sell_reason} | RSI={rsi_val:.1f}")
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
