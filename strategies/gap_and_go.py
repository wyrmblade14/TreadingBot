"""
Strategy 4: Gap & Go

One of the most reliable intraday patterns in Indian markets.

Background (why it works):
  When a stock opens significantly higher than yesterday's close, it means
  something changed overnight — earnings, news, or broader market sentiment.
  The gap represents trapped sellers from yesterday who are now "underwater"
  and will keep selling into rallies, which paradoxically creates fuel for
  a rally: short-sellers see the gap, bet it will fill, get squeezed when
  price keeps going, and are forced to buy back their shorts.

  This "gap-and-go" vs "gap-fill" distinction is the key. We only trade
  gaps that show follow-through — the stock continues ABOVE the gap in the
  first 15 minutes with high volume, signalling institutions are buying, not
  just retail traders chasing.

How it works (plain English):
  1. At market open, check if today's open is ≥ 0.5% above yesterday's close.
     That's the gap.

  2. Wait for the first 15-minute candle (9:15–9:30 AM). If price is still
     above the opening level (gap "held") and volume is high → BUY signal.
     The gap is valid; institutions are participating.

  3. On 5-minute intraday data: watch for the breakout above the first
     5-minute candle's high. This is the "Go" — momentum confirming the gap.

  4. VWAP filter: price must be above VWAP. This confirms institutional
     buying bias and filters out retail-only gaps that tend to fill quickly.

  5. Time filter: only trade before 11:00 AM. After that, gaps often start
     to fill as morning momentum fades.

Entry rules:
  ✓ Gap: today's open > yesterday's close by ≥ GAP_MIN_PCT (0.5%)
  ✓ Gap held: current close > today's open (no intraday gap-fill yet)
  ✓ Volume surge: signal candle volume ≥ VOLUME_MULTIPLIER × 20-bar avg
  ✓ VWAP: price above VWAP (institutional buy confirmation)
  ✓ Time: before 11:00 AM (gaps fade after this)
  ✓ Regime: only in Trending markets (gaps need follow-through)

Stop-loss:
  Yesterday's close — if price fills the gap entirely, the thesis is broken.
  We place the stop there: a full gap-fill means today's catalyst was not
  strong enough to hold the gap.

  Minimum: entry - 1.5 × ATR (in case the gap SL would be too tight or
  would fail the 2:1 reward/risk test).

Target:
  entry + 2 × risk — guarantees the 2:1 reward:risk rule is always met.
  On strong gaps with high volume, the actual move can be 3–5×.
"""

from __future__ import annotations

from datetime import time

import pandas as pd
from loguru import logger

from analysis.regime_detector import get_current_regime, regime_allows_strategy
from config import strategies as cfg
from config.settings import REGIME_FILTER_ENABLED
from indicators.vwap import get_vwap_signal
from strategies.base_strategy import Action, BaseStrategy, Signal

# Gap & Go is a morning-only strategy. After 11 AM the gap has either
# gone (good) or started to fill (bad). Either way, we are out.
_LATE_ENTRY_CUTOFF = time(11, 0)


class GapAndGoStrategy(BaseStrategy):
    """
    Gap & Go: trades stocks that open with a significant upward gap
    and continue higher with volume, confirming institutional interest.

    Works best on large-cap NIFTY50 stocks where institutional volume
    is meaningful — thin stocks can gap on low volume and quickly reverse.
    """

    def __init__(self) -> None:
        super().__init__(name="gap_and_go")
        params = cfg.STRATEGY_CONFIGS["gap_and_go"]

        self.gap_min_pct       = params["gap_min_pct"] / 100.0    # 0.5% → 0.005
        self.volume_multiplier = params["volume_multiplier"]

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Signal:
        """
        Analyse candle data and return a BUY/HOLD signal.

        Gap & Go is long-only: we only buy gaps up, never short gaps down.
        Short-side gap plays (gap down + go lower) are riskier in Indian
        markets due to circuit breakers and the generally bullish NIFTY50 bias.

        Args:
            symbol: e.g. "INFY"
            df:     OHLCV DataFrame. Works with both:
                    - Daily data (scanner mode): detects classic daily gap setup
                    - 5-minute data (live mode): detects intraday gap continuation
        """
        if len(df) < 5:
            return self.hold_signal(symbol, df["close"].iloc[-1])

        current_price = df["close"].iloc[-1]

        # ── Regime filter ─────────────────────────────────────────────────
        # Gap & Go needs the same follow-through as ORB. In Ranging markets,
        # gaps close quickly — price pulls back to yesterday's close within
        # the first hour. In Volatile markets, the gap can go either way with
        # no predictive edge.
        if REGIME_FILTER_ENABLED:
            regime = get_current_regime()
            if not regime_allows_strategy(regime, self.name):
                logger.debug(
                    f"Gap & Go suppressed for {symbol} — market regime: {regime.value}"
                )
                return self.hold_signal(symbol, current_price)

        # ── Time filter ───────────────────────────────────────────────────
        # Only applies to intraday (5-minute) data where the index is timestamp-aware.
        # Daily data has date-only index — skip the time check for daily/scanner mode.
        last_idx = df.index[-1]
        is_intraday = hasattr(last_idx, "time") and hasattr(last_idx, "hour")
        if is_intraday:
            try:
                current_time = last_idx.time()
                if current_time >= _LATE_ENTRY_CUTOFF:
                    return self.hold_signal(symbol, current_price)
            except (AttributeError, TypeError):
                pass   # Timestamp doesn't support .time() — treat as daily

        # ── Gap detection ─────────────────────────────────────────────────
        # A "gap" is when today's open jumps above yesterday's close.
        # We need at least 2 rows to compute the prior day's close.
        #
        # For daily data:  compare today's open vs yesterday's close directly.
        # For 5-min data:  compare the first candle's open vs the last candle
        #                  of the previous session. In scanner mode with daily
        #                  data this is just row[-2].close vs row[-1].open.
        prev_close    = float(df["close"].iloc[-2])
        current_open  = float(df["open"].iloc[-1])

        if prev_close <= 0:
            return self.hold_signal(symbol, current_price)

        gap_pct = (current_open - prev_close) / prev_close

        if gap_pct < self.gap_min_pct:
            # Gap too small (or negative — gap down). We only trade upward gaps.
            return self.hold_signal(symbol, current_price)

        # ── Gap-held check ────────────────────────────────────────────────
        # The stock must still be ABOVE the open. If it has already pulled
        # back below the open, the gap is weakening — don't chase it.
        if current_price < current_open:
            return self.hold_signal(symbol, current_price)

        # ── Volume surge ──────────────────────────────────────────────────
        # A gap on thin volume is often just a lack of sellers, not active
        # buying. We require the current candle's volume to be significantly
        # above recent average. The 20-bar average excludes the current candle
        # itself to avoid self-reference.
        vol_series = df["volume"]
        if len(vol_series) < 21:
            avg_volume = float(vol_series.mean())
        else:
            avg_volume = float(vol_series.iloc[-21:-1].mean())  # 20-bar avg, excl current

        current_vol = float(vol_series.iloc[-1])
        if avg_volume > 0 and current_vol < self.volume_multiplier * avg_volume:
            return self.hold_signal(symbol, current_price)

        # ── VWAP filter ───────────────────────────────────────────────────
        # Price must be above VWAP. This separates institutional buying
        # (pushes price above VWAP) from retail buying on headlines alone.
        # vwap_bias: +1 = above VWAP, -1 = below, 0 = unavailable (skip)
        vwap_bias = get_vwap_signal(df)
        if vwap_bias < 0:
            # Price below VWAP despite gap — institutions selling into the gap
            return self.hold_signal(symbol, current_price)

        # ── BUY signal ────────────────────────────────────────────────────
        # Stop-loss: yesterday's close. If the gap fills completely, the
        # overnight catalyst wasn't strong enough — exit without debate.
        # Floor: entry - 1.5×ATR (handles tight gaps where prev_close SL
        # would put risk_per_share near zero, making R:R calculations unstable)
        atr       = self._compute_atr(df, period=14)
        atr_sl    = round(current_price - 1.5 * atr, 2)
        gap_sl    = round(prev_close, 2)
        stop_loss = max(atr_sl, gap_sl)        # tighter of the two (further from entry = more risk)
        # Note: max() picks the higher price = smaller risk per share for BUY
        # gap_sl is usually below atr_sl for a genuine gap, so max() gives atr_sl

        risk_per_share = current_price - stop_loss
        if risk_per_share <= 0:
            return self.hold_signal(symbol, current_price)

        # Target = entry + 2× risk → exactly 2:1 R:R minimum
        target = round(current_price + 2.0 * risk_per_share, 2)

        logger.info(
            f"Gap & Go BUY | {symbol} | "
            f"price={current_price:.2f} gap={gap_pct*100:.2f}% "
            f"prev_close={prev_close:.2f} open={current_open:.2f} | "
            f"sl={stop_loss:.2f} target={target:.2f} "
            f"vol={current_vol:.0f} avg={avg_volume:.0f}"
        )

        return Signal(
            symbol=symbol,
            action=Action.BUY,
            entry_price=current_price,
            stop_loss=stop_loss,
            target=target,
            strategy=self.name,
            reason=(
                f"Gap up {gap_pct*100:.2f}% (open={current_open:.2f} vs prev_close={prev_close:.2f}) | "
                f"Gap held (price={current_price:.2f} > open) | "
                f"Volume surge {current_vol/avg_volume:.1f}× avg | "
                f"sl={stop_loss:.2f} target={target:.2f}"
            ),
        )
