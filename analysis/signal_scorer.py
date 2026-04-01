"""
Signal Confidence Scorer — rates every signal from 0 to 5.

Why this exists:
  Your strategies generate BUY/SELL signals based on their own specific rules,
  but a signal that just barely passed the strategy's conditions is much weaker
  than one where EVERY technical factor lines up. The score makes that visible
  without changing any strategy logic.

  Think of it as a second opinion. A 5/5 signal means:
    - The trend is in your favour
    - Volume is unusually high (institutions are participating)
    - Price is on the right side of VWAP (institutional flow agrees)
    - RSI confirms the momentum without being extreme
    - MACD direction matches your trade

  A 2/5 signal means only 2 of those 5 things are true — you might still take
  it (the strategy cleared all its own rules), but you know it's marginal.

The 5 checks (each worth 1 point):

  1. Trend aligned    — Price is above EMA50 for BUY, below EMA50 for SELL.
                        EMA50 is a widely-watched trend filter used by
                        institutional traders. If price is below EMA50 on a
                        BUY signal, you're fighting the prevailing trend.

  2. Volume confirmed — The signal candle's volume is at least 1.5× the 20-candle
                        average. High-volume moves are more likely to follow through
                        because large players are participating — not retail noise.

  3. VWAP aligned    — For BUY: price is above VWAP (institutions are net buyers).
                        For SELL: price is below VWAP (institutions are net sellers).
                        Scored 1 if VWAP data is unavailable (daily candles).

  4. RSI not extreme  — RSI is between 30 and 70. If RSI is already above 70 on
                        a BUY signal, the stock is overbought and you're late.
                        If RSI is below 30 on a SELL, it's oversold and a bounce
                        is likely. Neutral RSI means there's room to move.

  5. MACD momentum    — MACD line is above its signal line for BUY (upward
                        momentum building). Below its signal line for SELL.
                        This checks if the broader momentum trend agrees with
                        your entry direction.

Score interpretation:
  5/5 → High conviction — all factors align. Best quality signals.
  4/5 → Strong — one factor missing but generally well-supported.
  3/5 → Moderate — take with awareness of what's missing.
  2/5 or below → Low conviction — strategy rules passed but conditions are weak.
                  Be cautious, especially early in your paper trading period.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import ta

from strategies.base_strategy import Action, Signal


@dataclass
class ScoreResult:
    """
    The output of scoring a signal.

    Fields:
        score:   Total points out of 5.
        checks:  Dict mapping each check name → (passed: bool, label: str).
                 The label is a short human-readable description.
    """
    score:  int
    checks: dict[str, tuple[bool, str]]

    @property
    def max_score(self) -> int:
        return 5

    @property
    def colour(self) -> str:
        """CSS colour for the score badge."""
        if self.score >= 4:
            return "#4caf50"    # green
        if self.score >= 3:
            return "#ffc107"    # amber
        return "#ef5350"        # red

    @property
    def label(self) -> str:
        """Short text label for the score tier."""
        if self.score >= 4:
            return "High"
        if self.score >= 3:
            return "Moderate"
        return "Low"

    def dot_string(self) -> str:
        """
        Visual dot representation, e.g. '●●●○○' for score 3.
        Filled dots = passed checks. Empty = failed.
        """
        return "●" * self.score + "○" * (self.max_score - self.score)


# ── Check names (used as dict keys and display labels) ────────────────

CHECK_TREND   = "Trend aligned"
CHECK_VOLUME  = "Volume confirmed"
CHECK_VWAP    = "VWAP aligned"
CHECK_RSI     = "RSI not extreme"
CHECK_MACD    = "MACD momentum"

ALL_CHECKS = [CHECK_TREND, CHECK_VOLUME, CHECK_VWAP, CHECK_RSI, CHECK_MACD]


# ── Thresholds ────────────────────────────────────────────────────────

EMA_TREND_PERIOD      = 50
VOLUME_LOOKBACK       = 20      # candles for average volume
VOLUME_MULTIPLIER     = 1.5     # signal volume must be ≥ this × average
RSI_PERIOD            = 14
RSI_LOW               = 30      # below this = oversold
RSI_HIGH              = 70      # above this = overbought


# ── Main scorer ───────────────────────────────────────────────────────

def score_signal(signal: Signal, df: pd.DataFrame) -> ScoreResult:
    """
    Score a trading signal against 5 independent technical checks.

    Args:
        signal: The Signal produced by a strategy (BUY or SELL).
        df:     The same OHLCV DataFrame that was passed to the strategy.
                Must have columns: open, high, low, close, volume.

    Returns:
        ScoreResult with total score and individual check details.
    """
    if signal.action == Action.HOLD:
        return ScoreResult(score=0, checks={k: (False, "N/A — HOLD signal") for k in ALL_CHECKS})

    checks: dict[str, tuple[bool, str]] = {}
    is_buy = (signal.action == Action.BUY)

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    current_price  = float(close.iloc[-1])
    current_volume = float(volume.iloc[-1])

    # ── Check 1: Trend aligned (EMA50) ───────────────────────────────
    # EMA50 is computed fresh here so the scorer is independent of which
    # strategy fired the signal. It's a universal trend benchmark.
    passed, detail = _check_trend(close, is_buy, current_price)
    checks[CHECK_TREND] = (passed, detail)

    # ── Check 2: Volume confirmed ─────────────────────────────────────
    passed, detail = _check_volume(volume, current_volume)
    checks[CHECK_VOLUME] = (passed, detail)

    # ── Check 3: VWAP aligned ─────────────────────────────────────────
    passed, detail = _check_vwap(df, is_buy, current_price)
    checks[CHECK_VWAP] = (passed, detail)

    # ── Check 4: RSI not extreme ──────────────────────────────────────
    passed, detail = _check_rsi(close, is_buy)
    checks[CHECK_RSI] = (passed, detail)

    # ── Check 5: MACD momentum direction ─────────────────────────────
    passed, detail = _check_macd(close, is_buy)
    checks[CHECK_MACD] = (passed, detail)

    total = sum(1 for passed, _ in checks.values() if passed)
    return ScoreResult(score=total, checks=checks)


# ── Individual checks ─────────────────────────────────────────────────

def _check_trend(
    close: pd.Series,
    is_buy: bool,
    current_price: float,
) -> tuple[bool, str]:
    """Price above EMA50 for BUY, below EMA50 for SELL."""
    if len(close) < EMA_TREND_PERIOD + 1:
        return True, f"EMA{EMA_TREND_PERIOD} unavailable (too few candles) — skipped"

    ema50 = ta.trend.EMAIndicator(
        close=close, window=EMA_TREND_PERIOD
    ).ema_indicator().iloc[-1]

    if pd.isna(ema50):
        return True, f"EMA{EMA_TREND_PERIOD} returned NaN — skipped"

    ema50 = round(float(ema50), 2)

    if is_buy:
        passed = current_price > ema50
        direction = "above" if passed else "below"
        return passed, f"Price ₹{current_price:.0f} is {direction} EMA{EMA_TREND_PERIOD} ₹{ema50:.0f}"
    else:
        passed = current_price < ema50
        direction = "below" if passed else "above"
        return passed, f"Price ₹{current_price:.0f} is {direction} EMA{EMA_TREND_PERIOD} ₹{ema50:.0f}"


def _check_volume(volume: pd.Series, current_volume: float) -> tuple[bool, str]:
    """Signal candle volume ≥ 1.5× the 20-candle rolling average."""
    if len(volume) < VOLUME_LOOKBACK + 1:
        return True, "Not enough history for volume average — skipped"

    avg_vol = float(volume.iloc[-VOLUME_LOOKBACK - 1: -1].mean())
    if avg_vol == 0:
        return True, "Volume average is zero — skipped"

    ratio  = current_volume / avg_vol
    passed = ratio >= VOLUME_MULTIPLIER
    return (
        passed,
        f"Volume {current_volume:,.0f} is {ratio:.1f}× the {VOLUME_LOOKBACK}-candle avg "
        f"({'confirmed' if passed else f'need ≥{VOLUME_MULTIPLIER}×'})"
    )


def _check_vwap(df: pd.DataFrame, is_buy: bool, current_price: float) -> tuple[bool, str]:
    """
    Price above VWAP for BUY, below VWAP for SELL.
    Scored as True (neutral) if VWAP cannot be computed (e.g. daily candles).
    """
    try:
        # VWAP requires a datetime index. If it's daily data, VWAP is not meaningful.
        if not hasattr(df.index, "hour"):
            return True, "Daily candles — VWAP is intraday only, skipped"

        idx = df.index
        # Check if all candles are on the same day (intraday data)
        if len(idx) == 0 or idx[-1].date() != idx[-1].date():
            return True, "Cross-day data — VWAP skipped"

        close  = df["close"]
        high   = df["high"]
        low    = df["low"]
        volume = df["volume"]

        typical_price = (high + low + close) / 3
        cum_tp_vol    = (typical_price * volume).cumsum()
        cum_vol       = volume.cumsum()
        vwap          = (cum_tp_vol / cum_vol).iloc[-1]

        if pd.isna(vwap) or float(vwap) == 0:
            return True, "VWAP computation returned NaN — skipped"

        vwap = round(float(vwap), 2)

        if is_buy:
            passed    = current_price > vwap
            direction = "above" if passed else "below"
            return passed, f"Price ₹{current_price:.0f} is {direction} VWAP ₹{vwap:.0f}"
        else:
            passed    = current_price < vwap
            direction = "below" if passed else "above"
            return passed, f"Price ₹{current_price:.0f} is {direction} VWAP ₹{vwap:.0f}"

    except Exception:
        return True, "VWAP computation unavailable — skipped"


def _check_rsi(close: pd.Series, is_buy: bool) -> tuple[bool, str]:
    """RSI must be in the neutral zone (30–70) — not already at an extreme."""
    if len(close) < RSI_PERIOD + 2:
        return True, f"RSI({RSI_PERIOD}) unavailable (too few candles) — skipped"

    rsi_val = ta.momentum.RSIIndicator(
        close=close, window=RSI_PERIOD
    ).rsi().iloc[-1]

    if pd.isna(rsi_val):
        return True, f"RSI({RSI_PERIOD}) returned NaN — skipped"

    rsi_val = round(float(rsi_val), 1)
    in_zone = RSI_LOW <= rsi_val <= RSI_HIGH

    if is_buy:
        if rsi_val > RSI_HIGH:
            return False, f"RSI {rsi_val} — overbought (>{RSI_HIGH}), late entry risk"
        if rsi_val < RSI_LOW:
            return True, f"RSI {rsi_val} — oversold, may bounce (BUY confirmed)"
        return True, f"RSI {rsi_val} — neutral zone, room to move up"
    else:
        if rsi_val < RSI_LOW:
            return False, f"RSI {rsi_val} — oversold (<{RSI_LOW}), late short risk"
        if rsi_val > RSI_HIGH:
            return True, f"RSI {rsi_val} — overbought, may fall (SELL confirmed)"
        return True, f"RSI {rsi_val} — neutral zone, room to move down"


def _check_macd(close: pd.Series, is_buy: bool) -> tuple[bool, str]:
    """MACD line above signal line for BUY, below for SELL."""
    MIN_CANDLES = 26 + 9 + 2   # slow EMA + signal + buffer
    if len(close) < MIN_CANDLES:
        return True, "Not enough candles for MACD — skipped"

    macd_obj   = ta.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    macd_line  = macd_obj.macd().iloc[-1]
    signal_line = macd_obj.macd_signal().iloc[-1]

    if pd.isna(macd_line) or pd.isna(signal_line):
        return True, "MACD returned NaN — skipped"

    macd_line   = round(float(macd_line), 3)
    signal_line = round(float(signal_line), 3)
    above       = macd_line > signal_line

    if is_buy:
        return above, (
            f"MACD {macd_line:+.2f} {'above' if above else 'below'} signal {signal_line:+.2f} "
            f"({'bullish ✓' if above else 'bearish momentum ✗'})"
        )
    else:
        return not above, (
            f"MACD {macd_line:+.2f} {'below' if not above else 'above'} signal {signal_line:+.2f} "
            f"({'bearish ✓' if not above else 'bullish momentum ✗'})"
        )
