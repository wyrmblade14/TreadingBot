"""
Strategy: Trend Rider

Why this strategy exists:
  EMA crossover and RSI+MACD both enter on indicator *crossovers* — by the time
  a crossover fires, the stock has already moved significantly. In a sustained
  bear market (NIFTY -8% Feb–Apr 2026), MACD bearish crossovers arrived when
  RSI was already below 40 (oversold), getting stopped out on relief bounces.

  Trend Rider solves this by entering at the *moment* the underlying trend changes.
  Supertrend is an ATR-adaptive band that "flips" exactly once at the start of
  each new trend leg. Entering on that flip catches the move from the very
  beginning — before RSI has time to become oversold.

How it works (plain English):
  Supertrend draws a line above or below price. When price breaks below the line
  it flips to bearish; above the line it flips to bullish. That flip is a one-time
  event per trend leg — it can't re-fire until the next actual trend change.

  We also require ADX > 20 to confirm that the flip has real conviction behind it,
  not just intraday noise. In a choppy sideways market, ADX stays low and the
  strategy stays flat.

Entry rules:
  LONG:  Supertrend just flipped bearish→bullish  AND  ADX ≥ adx_min
  SHORT: Supertrend just flipped bullish→bearish  AND  ADX ≥ adx_min

Stop-loss: the Supertrend line at entry (the ATR band that was just broken)
Target:    entry ± 2× (entry − stop_loss)  →  2:1 reward:risk

Regime filter:
  TRENDING → allowed (this is the strategy's home turf)
  RANGING  → suppressed (Supertrend flips constantly in choppy markets)
  VOLATILE → suppressed (price spikes hit stops before trend confirms)
  UNKNOWN  → allowed (fail-safe)
"""

from __future__ import annotations

import math

import pandas as pd
import ta
from loguru import logger

from analysis.regime_detector import get_current_regime, regime_allows_strategy
from config import strategies as cfg
from config.settings import REGIME_FILTER_ENABLED
from indicators.supertrend import SupertrendIndicator
from strategies.base_strategy import Action, BaseStrategy, Signal


class TrendRiderStrategy(BaseStrategy):
    """
    Supertrend flip + ADX confirmation trend-following strategy.
    Enters short at the exact candle where Supertrend turns bearish;
    enters long at the exact candle where Supertrend turns bullish.
    """

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(name="trend_rider")
        self.default_params = params or cfg.STRATEGY_CONFIGS["trend_rider"]
        # Cache: symbol → (indicators_dict, config_dict)
        self._symbol_cache: dict[str, tuple[dict, dict]] = {}
        # Dedup: symbol → last flip bar index (persists independently of param cache)
        self._last_flip_bar: dict[str, object] = {}

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
            "supertrend": SupertrendIndicator(
                period=params.get("supertrend_period", 10),
                multiplier=params.get("supertrend_multiplier", 3.0),
            ),
        }

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Signal:
        """
        Return BUY/SELL on a Supertrend trend flip; HOLD otherwise.

        Args:
            symbol: e.g. "SBIN"
            df:     OHLCV DataFrame (needs at least supertrend_period + adx_period + 2 candles)
        """
        config = self._get_config(symbol)

        if symbol not in self._symbol_cache or self._symbol_cache[symbol][1] != config:
            self._symbol_cache[symbol] = (self._init_indicators(config), config)
        inds, params = self._symbol_cache[symbol]

        adx_min           = params.get("adx_min", 20)
        adx_period        = params.get("adx_period", 14)
        volume_multiplier = params.get("volume_multiplier", 1.2)
        min_sl_pct        = params.get("min_sl_pct", 0.005)

        current_price = float(df["close"].iloc[-1])

        # ── Regime filter ─────────────────────────────────────────────
        if REGIME_FILTER_ENABLED:
            regime = get_current_regime()
            if not regime_allows_strategy(regime, self.name):
                logger.debug(
                    f"TrendRider suppressed for {symbol} — regime: {regime.value}"
                )
                return self.hold_signal(symbol, current_price)

        # ── Data sufficiency ──────────────────────────────────────────
        st_ind = inds["supertrend"]
        min_candles = st_ind.min_candles + adx_period + 2
        if len(df) < min_candles:
            return self.hold_signal(symbol, current_price)

        # ── Supertrend computation ────────────────────────────────────
        st_df        = st_ind.compute(df)
        trend_now    = st_df["supertrend_trend"].iloc[-1]
        trend_prev   = st_df["supertrend_trend"].iloc[-2]
        st_val_now   = float(st_df["supertrend"].iloc[-1])

        if math.isnan(trend_now) or math.isnan(trend_prev):
            return self.hold_signal(symbol, current_price)

        # A "flip" is a single-candle direction change: -1→+1 or +1→-1
        just_flipped_bullish = (trend_prev == -1) and (trend_now == 1)
        just_flipped_bearish = (trend_prev == 1)  and (trend_now == -1)

        if not (just_flipped_bullish or just_flipped_bearish):
            return self.hold_signal(symbol, current_price)   # no flip this candle

        # ── Dedup: don't re-fire on stale data ───────────────────────
        bar_key = df.index[-1]
        if self._last_flip_bar.get(symbol) == bar_key:
            logger.debug(
                f"TrendRider flip skipped | {symbol} | duplicate bar {bar_key}"
            )
            return self.hold_signal(symbol, current_price)
        self._last_flip_bar[symbol] = bar_key

        # ── ADX strength filter ───────────────────────────────────────
        # ADX < adx_min means the market lacks directional conviction — the
        # Supertrend flip is likely noise rather than a genuine trend change.
        adx_series  = ta.trend.ADXIndicator(
            high=df["high"], low=df["low"], close=df["close"],
            window=adx_period
        ).adx()
        current_adx = float(adx_series.iloc[-1])

        if math.isnan(current_adx) or current_adx < adx_min:
            logger.debug(
                f"TrendRider flip skipped | {symbol} | ADX={current_adx:.1f} < {adx_min} — no conviction"
            )
            return self.hold_signal(symbol, current_price)

        # ── EMA trend alignment filter ────────────────────────────────
        # EMA9 vs EMA21 on the same candle timeframe gives the medium-term
        # trend direction. We only allow BUY flips when the medium-term trend
        # is also bullish (EMA9 > EMA21), and only SELL flips when bearish.
        # This kills the biggest whipsaw source: bullish Supertrend flips
        # during bear-market bounces, where EMA9 is still well below EMA21.
        if len(df) >= 21:
            close = df["close"]
            ema9  = float(ta.trend.EMAIndicator(close, window=9).ema_indicator().iloc[-1])
            ema21 = float(ta.trend.EMAIndicator(close, window=21).ema_indicator().iloc[-1])
            if not (math.isnan(ema9) or math.isnan(ema21)):
                ema_bullish = ema9 > ema21
                ema_bearish = ema9 < ema21
                if just_flipped_bullish and not ema_bullish:
                    logger.debug(
                        f"TrendRider BUY skipped | {symbol} | "
                        f"EMA9({ema9:.2f}) < EMA21({ema21:.2f}) — medium-term still bearish"
                    )
                    return self.hold_signal(symbol, current_price)
                if just_flipped_bearish and not ema_bearish:
                    logger.debug(
                        f"TrendRider SELL skipped | {symbol} | "
                        f"EMA9({ema9:.2f}) > EMA21({ema21:.2f}) — medium-term still bullish"
                    )
                    return self.hold_signal(symbol, current_price)

        # ── Volume confirmation ───────────────────────────────────────
        if "volume" in df.columns and volume_multiplier > 0:
            vol_avg = df["volume"].rolling(20).mean().iloc[-1]
            vol_now = float(df["volume"].iloc[-1])
            if not math.isnan(vol_avg) and vol_avg > 0:
                if vol_now < volume_multiplier * vol_avg:
                    logger.debug(
                        f"TrendRider flip skipped | {symbol} | "
                        f"vol={vol_now:.0f} < {volume_multiplier}× avg={vol_avg:.0f}"
                    )
                    return self.hold_signal(symbol, current_price)

        # ── Compute SL and target ─────────────────────────────────────
        # The Supertrend line IS the stop: it's the ATR band that was just broken.
        # For BUY: st_val_now is the lower band (support) → SL = st_val_now
        # For SELL: st_val_now is the upper band (resistance) → SL = st_val_now
        # Minimum SL distance: at least min_sl_pct of price to avoid noise hits.

        if just_flipped_bullish:
            sl_dist   = max(current_price - st_val_now, current_price * min_sl_pct)
            stop_loss = round(current_price - sl_dist, 2)
            target    = round(current_price + 2.0 * sl_dist, 2)

            logger.info(
                f"TrendRider BUY | {symbol} | price={current_price:.2f} "
                f"st={st_val_now:.2f} ADX={current_adx:.1f} "
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
                    f"Supertrend flipped bullish (was bearish) at {st_val_now:.2f}, "
                    f"ADX={current_adx:.1f}"
                ),
            )

        # just_flipped_bearish
        sl_dist   = max(st_val_now - current_price, current_price * min_sl_pct)
        stop_loss = round(current_price + sl_dist, 2)
        target    = round(current_price - 2.0 * sl_dist, 2)

        logger.info(
            f"TrendRider SELL | {symbol} | price={current_price:.2f} "
            f"st={st_val_now:.2f} ADX={current_adx:.1f} "
            f"sl={stop_loss:.2f} target={target:.2f}"
        )
        return Signal(
            symbol=symbol,
            action=Action.SELL,
            entry_price=current_price,
            stop_loss=stop_loss,
            target=target,
            strategy=self.name,
            reason=(
                f"Supertrend flipped bearish (was bullish) at {st_val_now:.2f}, "
                f"ADX={current_adx:.1f}"
            ),
        )
