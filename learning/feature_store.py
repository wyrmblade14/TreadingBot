"""
Feature Store — Phase A of the TreadingBot self-learning system.

Why this exists:
  The bot currently logs *outcomes* (win/loss, P&L) but never records *why*
  it entered — what RSI was at entry, how far price was from VWAP, what the
  VIX was. Without that snapshot, there is nothing to learn from.

  This module closes the gap:
    1. capture()  — called on every entry: snapshots 12 indicator + context
                    features into the `trade_features` table.
    2. label()    — called on every exit: writes outcome (1=win, 0=loss),
                    P&L, and hold duration into the same row.

  After 100+ labelled rows, Phase B (signal_classifier.py) trains a
  logistic regression model on these features to predict win probability
  for future signals.

Design choices:
  • Same DATABASE_URL as trade_log.py — one Postgres instance, two tables.
  • Separate SQLAlchemy Base so this module has no import dependency on
    trade_log.py (avoids circular imports and keeps the two ORM models
    independently evolvable).
  • trade_id is a plain integer FK — no SQLAlchemy ForeignKey constraint,
    so this table can be created before or after 'trades' without ordering
    issues. Referential integrity is maintained by application logic.
  • All public methods are wrapped in try/except and return None/False on
    failure so a DB error or missing DATABASE_URL never blocks a trade.
  • extract_indicator_features() is a pure function (no I/O) so it can be
    unit-tested without a database.
"""

from __future__ import annotations

import math
import os
from datetime import datetime
from typing import Optional

import pandas as pd
from loguru import logger
from sqlalchemy import (
    Column, DateTime, Float, Integer, String,
    create_engine, inspect, text,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config.settings import IST


# ── Database setup ────────────────────────────────────────────────────

_DB_URL = os.environ.get("DATABASE_URL")

if _DB_URL:
    _engine  = create_engine(_DB_URL, echo=False, pool_pre_ping=True)
    _Session = sessionmaker(bind=_engine)
else:
    _engine  = None   # type: ignore[assignment]
    _Session = None   # type: ignore[assignment]


class _Base(DeclarativeBase):
    pass


class TradeFeature(_Base):
    """
    One row per trade entry — records the full market state snapshot plus
    the outcome once the trade closes.
    """
    __tablename__ = "trade_features"

    id           = Column(Integer,     primary_key=True, autoincrement=True)
    trade_id     = Column(Integer,     nullable=False, index=True)  # mirrors trades.id
    symbol       = Column(String(20),  nullable=False)
    strategy     = Column(String(50),  nullable=False)
    captured_at  = Column(DateTime,    nullable=False)              # wall-clock at entry

    # ── Indicator snapshot (normalised — scale-invariant) ─────────────
    rsi          = Column(Float)   # RSI(6) — intraday-sensitive
    ema_spread   = Column(Float)   # (EMA9 − EMA21) / price  → momentum direction
    vwap_dev     = Column(Float)   # (price − VWAP) / VWAP   → institutional bias
    volume_ratio = Column(Float)   # volume / 20-bar avg     → participation
    macd_hist    = Column(Float)   # MACD histogram (raw — same sign as diff)
    atr_pct      = Column(Float)   # ATR(14) / price         → volatility level

    # ── Market context at entry ───────────────────────────────────────
    vix          = Column(Float)        # India VIX value
    regime       = Column(String(20))   # TRENDING / RANGING / VOLATILE
    direction    = Column(String(10))   # UP / DOWN / NEUTRAL
    hour         = Column(Integer)      # IST hour at entry (9–14)
    day_of_week  = Column(Integer)      # 0=Mon … 4=Fri
    nifty_chg    = Column(Float)        # NIFTY50 intraday % change at entry

    # ── Outcome (written when trade closes) ───────────────────────────
    outcome      = Column(Integer)      # 1 = win, 0 = loss, NULL = still open
    pnl          = Column(Float)        # net P&L in ₹ (NULL while open)
    hold_minutes = Column(Integer)      # trade duration in minutes (NULL while open)


# ── Schema bootstrap ──────────────────────────────────────────────────

def init_db() -> None:
    """
    Create the trade_features table if it doesn't exist.
    Safe to call multiple times — idempotent.
    Raises RuntimeError only when DATABASE_URL is absent.
    """
    if _engine is None:
        raise RuntimeError(
            "DATABASE_URL is not set — feature store requires PostgreSQL.\n"
            "Add DATABASE_URL=postgresql://... to .env"
        )
    inspector = inspect(_engine)
    is_new = not inspector.has_table("trade_features")
    _Base.metadata.create_all(_engine)
    if is_new:
        logger.info("Feature store: trade_features table created")
    else:
        logger.debug("Feature store: trade_features table ready")


# ── Public API ────────────────────────────────────────────────────────

def extract_indicator_features(df: pd.DataFrame) -> dict:
    """
    Compute a normalised feature snapshot from the latest candle in df.

    All values are scale-invariant (ratios or bounded indicators) so the
    classifier can compare signals across different stocks and price levels.

    Requires at least 26 candles (MACD window_slow=26).
    Returns an empty dict if df is too short or import fails.
    Any individual indicator failure sets that key to float('nan').

    This is a pure function — no I/O, no side-effects. Safe to call in
    unit tests without a running database.
    """
    if df is None or len(df) < 26:
        return {}

    import ta  # lazy import — ta is a heavy dependency

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]
    last_price = float(close.iloc[-1])

    if last_price <= 0:
        return {}

    feats: dict = {}

    # RSI(6) — shorter window for intraday sensitivity (see AGENTS.md idea #32)
    try:
        feats["rsi"] = float(
            ta.momentum.RSIIndicator(close, window=6).rsi().iloc[-1]
        )
    except Exception:
        feats["rsi"] = float("nan")

    # EMA spread: (EMA9 − EMA21) / price
    # Positive = EMA9 above EMA21 = bullish momentum. Normalised by price
    # so a ₹500 stock and a ₹5000 stock produce comparable values.
    try:
        ema9  = float(ta.trend.EMAIndicator(close, window=9).ema_indicator().iloc[-1])
        ema21 = float(ta.trend.EMAIndicator(close, window=21).ema_indicator().iloc[-1])
        feats["ema_spread"] = (ema9 - ema21) / last_price
    except Exception:
        feats["ema_spread"] = float("nan")

    # VWAP deviation: (price − VWAP) / VWAP
    # Positive = above VWAP = institutional buy pressure.
    # VWAP is reset at 9:15 AM via cumsum on the day's candles.
    try:
        typical_price = (high + low + close) / 3
        cum_tp_vol    = (typical_price * volume).cumsum()
        cum_vol       = volume.cumsum()
        vwap_series   = cum_tp_vol / cum_vol
        vwap_val      = float(vwap_series.iloc[-1])
        feats["vwap_dev"] = (last_price - vwap_val) / vwap_val if vwap_val > 0 else float("nan")
    except Exception:
        feats["vwap_dev"] = float("nan")

    # Volume ratio: latest bar volume / 20-bar rolling average
    # > 1.5 = high participation; < 0.8 = thin tape
    try:
        avg_vol = float(volume.rolling(20).mean().iloc[-1])
        feats["volume_ratio"] = float(volume.iloc[-1]) / avg_vol if avg_vol > 0 else float("nan")
    except Exception:
        feats["volume_ratio"] = float("nan")

    # MACD histogram (raw, not normalised)
    # Positive and growing = accelerating momentum.
    try:
        macd_ind   = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
        feats["macd_hist"] = float(macd_ind.macd_diff().iloc[-1])
    except Exception:
        feats["macd_hist"] = float("nan")

    # ATR(14) as % of price — current volatility regime
    # High ATR% = wide stops needed; low ATR% = tight range
    try:
        prev_close = close.shift(1)
        true_range = pd.concat(
            [high - low,
             (high - prev_close).abs(),
             (low  - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        atr_val = float(true_range.rolling(14).mean().iloc[-1])
        feats["atr_pct"] = atr_val / last_price if last_price > 0 else float("nan")
    except Exception:
        feats["atr_pct"] = float("nan")

    return feats


class FeatureStore:
    """
    Thin wrapper around the trade_features table.

    Usage:
        fs = FeatureStore()
        fs.capture(trade_id=42, symbol="RELIANCE", strategy="ema_crossover",
                   indicator_features={"rsi": 54.3, "ema_spread": 0.003, ...})
        # ... later, when trade closes ...
        fs.label(trade_id=42, pnl=1250.0, hold_minutes=45)

    All methods fail silently when DATABASE_URL is not set or when a
    DB error occurs — the feature store is enhancement-only and must
    never interfere with live trading.
    """

    def __init__(self) -> None:
        if _engine is not None:
            try:
                init_db()
            except Exception as exc:
                logger.debug(f"FeatureStore init skipped: {exc}")

    # ── Write path ────────────────────────────────────────────────────

    def capture(
        self,
        trade_id: int,
        symbol: str,
        strategy: str,
        indicator_features: dict,
    ) -> bool:
        """
        Persist the feature snapshot at trade entry.

        Market context (VIX, regime, direction, NIFTY change) is fetched
        from the cached data modules — all are TTL-cached so this call is
        near-zero network cost.

        Returns True if saved successfully, False otherwise.
        """
        if _Session is None:
            return False

        vix_val, regime_val, direction_val, nifty_chg = _get_market_context()
        now = datetime.now(IST)

        try:
            record = TradeFeature(
                trade_id    = trade_id,
                symbol      = symbol,
                strategy    = strategy,
                captured_at = now,
                # indicator features
                rsi          = _safe(indicator_features.get("rsi")),
                ema_spread   = _safe(indicator_features.get("ema_spread")),
                vwap_dev     = _safe(indicator_features.get("vwap_dev")),
                volume_ratio = _safe(indicator_features.get("volume_ratio")),
                macd_hist    = _safe(indicator_features.get("macd_hist")),
                atr_pct      = _safe(indicator_features.get("atr_pct")),
                # market context
                vix         = vix_val,
                regime      = regime_val,
                direction   = direction_val,
                hour        = now.hour,
                day_of_week = now.weekday(),
                nifty_chg   = nifty_chg,
            )
            with _Session() as session:
                session.add(record)
                session.commit()
            logger.debug(
                f"FeatureStore captured trade_id={trade_id} "
                f"({symbol}/{strategy}) rsi={indicator_features.get('rsi'):.1f}"
            )
            return True
        except Exception as exc:
            logger.debug(f"FeatureStore.capture failed (trade_id={trade_id}): {exc}")
            return False

    def label(
        self,
        trade_id: int,
        pnl: float,
        hold_minutes: int,
    ) -> bool:
        """
        Write the trade outcome into the existing feature row.

        Called from OrderManager._close_trade() after net_pnl is computed.
        Returns True if updated, False if row not found or DB unavailable.
        """
        if _Session is None:
            return False
        try:
            with _Session() as session:
                row = session.query(TradeFeature).filter(
                    TradeFeature.trade_id == trade_id
                ).first()
                if row is None:
                    logger.debug(
                        f"FeatureStore.label: no feature row for trade_id={trade_id} — "
                        "capture() may have failed at entry"
                    )
                    return False
                row.outcome      = 1 if pnl > 0 else 0
                row.pnl          = round(pnl, 2)
                row.hold_minutes = max(0, int(hold_minutes))
                session.commit()
            logger.debug(
                f"FeatureStore labelled trade_id={trade_id} "
                f"outcome={'WIN' if pnl > 0 else 'LOSS'} pnl=₹{pnl:.2f}"
            )
            return True
        except Exception as exc:
            logger.debug(f"FeatureStore.label failed (trade_id={trade_id}): {exc}")
            return False

    # ── Read path (used by Phase B classifier and Phase C optimizer) ──

    def get_labelled_features(self, min_count: int = 10) -> Optional[pd.DataFrame]:
        """
        Return all labelled (closed) trade features as a DataFrame.

        Returns None if fewer than min_count rows exist.
        Used by signal_classifier.py to build the training set.

        Columns: rsi, ema_spread, vwap_dev, volume_ratio, macd_hist,
                 atr_pct, vix, hour, day_of_week, nifty_chg, outcome, pnl
        """
        if _Session is None:
            return None
        try:
            with _Session() as session:
                rows = session.execute(text(
                    """
                    SELECT rsi, ema_spread, vwap_dev, volume_ratio,
                           macd_hist, atr_pct, vix, regime, direction,
                           hour, day_of_week, nifty_chg,
                           outcome, pnl, hold_minutes, strategy, symbol,
                           captured_at
                    FROM trade_features
                    WHERE outcome IS NOT NULL
                    ORDER BY captured_at DESC
                    """
                )).fetchall()

            if len(rows) < min_count:
                return None

            df = pd.DataFrame([dict(r._mapping) for r in rows])
            return df
        except Exception as exc:
            logger.debug(f"FeatureStore.get_labelled_features failed: {exc}")
            return None

    def rolling_sharpe(self, strategy: str, last_n: int = 50) -> float:
        """
        Compute a rolling Sharpe ratio for the last N closed trades of a
        given strategy from the feature store.

        Used by Phase C (param_optimizer) to measure baseline performance
        before and after a parameter change.

        Returns 0.0 if insufficient data.
        """
        if _Session is None:
            return 0.0
        try:
            with _Session() as session:
                rows = session.execute(text(
                    """
                    SELECT pnl FROM trade_features
                    WHERE strategy = :strategy AND pnl IS NOT NULL
                    ORDER BY captured_at DESC
                    LIMIT :n
                    """
                ), {"strategy": strategy, "n": last_n}).fetchall()

            if len(rows) < 10:
                return 0.0

            pnls  = [float(r[0]) for r in rows]
            mean  = sum(pnls) / len(pnls)
            var   = sum((p - mean) ** 2 for p in pnls) / len(pnls)
            std   = var ** 0.5
            return round(mean / std, 3) if std > 0 else 0.0
        except Exception as exc:
            logger.debug(f"FeatureStore.rolling_sharpe failed: {exc}")
            return 0.0

    def feature_counts(self) -> dict:
        """
        Return summary counts for the dashboard.

        Returns:
            {
              "total":    int,   # all captured rows
              "labelled": int,   # rows with outcome set
              "wins":     int,
              "losses":   int,
            }
        """
        if _Session is None:
            return {"total": 0, "labelled": 0, "wins": 0, "losses": 0}
        try:
            with _Session() as session:
                row = session.execute(text(
                    """
                    SELECT
                        COUNT(*)                                          AS total,
                        COUNT(outcome)                                    AS labelled,
                        SUM(CASE WHEN outcome = 1 THEN 1 ELSE 0 END)    AS wins,
                        SUM(CASE WHEN outcome = 0 THEN 1 ELSE 0 END)    AS losses
                    FROM trade_features
                    """
                )).fetchone()
                return {
                    "total":    int(row[0] or 0),
                    "labelled": int(row[1] or 0),
                    "wins":     int(row[2] or 0),
                    "losses":   int(row[3] or 0),
                }
        except Exception as exc:
            logger.debug(f"FeatureStore.feature_counts failed: {exc}")
            return {"total": 0, "labelled": 0, "wins": 0, "losses": 0}


# ── Internal helpers ──────────────────────────────────────────────────

def _safe(val: object) -> Optional[float]:
    """Convert a value to float, returning None for NaN/None/inf."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 6)
    except (TypeError, ValueError):
        return None


def _get_market_context() -> tuple[Optional[float], str, str, float]:
    """
    Fetch cached market context: (vix, regime, direction, nifty_chg).

    All sources are TTL-cached in their respective modules — this call
    is near-zero network cost on the hot path.

    Returns safe defaults on any error so capture() never raises.
    """
    vix_val: Optional[float] = None
    regime_val:    str = "Unknown"
    direction_val: str = "NEUTRAL"
    nifty_chg:     float = 0.0

    try:
        from data.india_vix import get_vix_data
        vix_data = get_vix_data()
        vix_val  = vix_data.get("vix")
    except Exception:
        pass

    try:
        from analysis.regime_detector import get_current_regime
        regime = get_current_regime()
        regime_val = regime.value if regime else "Unknown"
    except Exception:
        pass

    try:
        from analysis.market_direction import get_market_direction
        direction = get_market_direction()
        direction_val = direction.value if direction else "NEUTRAL"
    except Exception:
        pass

    try:
        from analysis.nifty_correlation import get_nifty_change
        nifty_chg = float(get_nifty_change() or 0.0)
    except Exception:
        pass

    return vix_val, regime_val, direction_val, nifty_chg
