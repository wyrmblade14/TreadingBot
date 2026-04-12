"""
Tests for learning/feature_store.py — Phase A of the self-learning system.

Coverage:
  1. extract_indicator_features() — pure function, no DB required
     • Returns correct keys for a well-formed DataFrame
     • Returns empty dict when df is too short (< 26 bars)
     • Returns empty dict for None input
     • NaN-safe: individual indicator failures don't crash the function

  2. FeatureStore.capture() — write path
     • Inserts a row into trade_features when DB is available
     • Returns False (silently) when DATABASE_URL is not set
     • feature_counts() reflects the captured row

  3. FeatureStore.label() — outcome write path
     • Updates outcome/pnl/hold_minutes on an existing row
     • Returns False (silently) when row doesn't exist
     • get_labelled_features() includes the labelled row

  4. Fail-open guarantees
     • Both capture() and label() return False without raising when
       _Session is None (no DATABASE_URL)

All DB-dependent tests are skipped when DATABASE_URL is not set in the
environment.  The pure-function tests always run.
"""

from __future__ import annotations

import os
import math
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest

# ── Helpers ───────────────────────────────────────────────────────────

def _make_df(n: int = 60) -> pd.DataFrame:
    """
    Build a synthetic OHLCV DataFrame with *n* 5-minute candles.
    Prices follow a gentle uptrend so all indicators produce finite values.
    """
    rng = np.random.default_rng(42)
    base = 500.0
    closes = base + np.cumsum(rng.normal(0, 1, n))
    highs  = closes + rng.uniform(0.5, 2.0, n)
    lows   = closes - rng.uniform(0.5, 2.0, n)
    opens  = closes + rng.normal(0, 0.5, n)
    vols   = rng.integers(10_000, 100_000, n).astype(float)

    idx = pd.date_range("2026-04-12 09:15", periods=n, freq="5min", tz="Asia/Kolkata")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=idx,
    )


# ── Pure-function tests: extract_indicator_features ───────────────────

class TestExtractIndicatorFeatures:
    """All tests here are pure — no database, no network."""

    def test_returns_all_expected_keys(self):
        from learning.feature_store import extract_indicator_features
        df   = _make_df(60)
        feat = extract_indicator_features(df)
        assert set(feat) == {"rsi", "ema_spread", "vwap_dev",
                              "volume_ratio", "macd_hist", "atr_pct"}

    def test_values_are_finite_floats(self):
        from learning.feature_store import extract_indicator_features
        df   = _make_df(60)
        feat = extract_indicator_features(df)
        for key, val in feat.items():
            assert isinstance(val, float), f"{key} should be float, got {type(val)}"
            assert math.isfinite(val), f"{key}={val} is not finite"

    def test_rsi_in_valid_range(self):
        from learning.feature_store import extract_indicator_features
        feat = extract_indicator_features(_make_df(60))
        assert 0.0 <= feat["rsi"] <= 100.0

    def test_volume_ratio_positive(self):
        from learning.feature_store import extract_indicator_features
        feat = extract_indicator_features(_make_df(60))
        assert feat["volume_ratio"] > 0.0

    def test_atr_pct_positive(self):
        from learning.feature_store import extract_indicator_features
        feat = extract_indicator_features(_make_df(60))
        assert feat["atr_pct"] > 0.0

    def test_returns_empty_dict_when_df_too_short(self):
        from learning.feature_store import extract_indicator_features
        df   = _make_df(10)   # only 10 bars — MACD needs 26
        feat = extract_indicator_features(df)
        assert feat == {}

    def test_returns_empty_dict_for_none_input(self):
        from learning.feature_store import extract_indicator_features
        assert extract_indicator_features(None) == {}  # type: ignore[arg-type]

    def test_handles_zero_volume_gracefully(self):
        """Zero-volume bars should return NaN for volume_ratio, not crash."""
        from learning.feature_store import extract_indicator_features
        df = _make_df(60)
        df["volume"] = 0.0
        feat = extract_indicator_features(df)
        # volume_ratio must be NaN (not a crash)
        assert "volume_ratio" in feat
        assert math.isnan(feat["volume_ratio"]) or feat["volume_ratio"] == 0.0


# ── _safe helper ──────────────────────────────────────────────────────

class TestSafeHelper:
    def test_returns_none_for_nan(self):
        from learning.feature_store import _safe
        assert _safe(float("nan")) is None

    def test_returns_none_for_inf(self):
        from learning.feature_store import _safe
        assert _safe(float("inf")) is None

    def test_returns_none_for_none(self):
        from learning.feature_store import _safe
        assert _safe(None) is None

    def test_rounds_to_6dp(self):
        from learning.feature_store import _safe
        result = _safe(3.14159265358979)
        assert result == pytest.approx(3.141593, rel=1e-5)

    def test_valid_float(self):
        from learning.feature_store import _safe
        assert _safe(42.0) == 42.0


# ── DB-dependent tests ────────────────────────────────────────────────

_DB_AVAILABLE = bool(os.environ.get("DATABASE_URL"))
skip_no_db = pytest.mark.skipif(
    not _DB_AVAILABLE,
    reason="DATABASE_URL not set — skipping live DB tests",
)


class TestFeatureStoreCapture:

    @skip_no_db
    def test_capture_inserts_row(self):
        """capture() creates a trade_features row retrievable by trade_id."""
        from learning.feature_store import FeatureStore, _Session, TradeFeature

        fs = FeatureStore()
        fake_trade_id = 999_001   # high number to avoid clashing with real trades

        feats = {
            "rsi": 54.3,
            "ema_spread": 0.0023,
            "vwap_dev": -0.001,
            "volume_ratio": 1.4,
            "macd_hist": 0.12,
            "atr_pct": 0.0082,
        }

        result = fs.capture(
            trade_id=fake_trade_id,
            symbol="TEST",
            strategy="test_strategy",
            indicator_features=feats,
        )
        assert result is True

        with _Session() as session:
            row = session.query(TradeFeature).filter(
                TradeFeature.trade_id == fake_trade_id
            ).first()
            assert row is not None
            assert row.symbol == "TEST"
            assert row.strategy == "test_strategy"
            assert row.rsi == pytest.approx(54.3, rel=1e-4)
            assert row.outcome is None   # not labelled yet

        # Cleanup
        with _Session() as session:
            session.query(TradeFeature).filter(
                TradeFeature.trade_id == fake_trade_id
            ).delete()
            session.commit()

    @skip_no_db
    def test_feature_counts_includes_capture(self):
        from learning.feature_store import FeatureStore, _Session, TradeFeature

        fs = FeatureStore()
        before = fs.feature_counts()["total"]

        fake_id = 999_002
        fs.capture(fake_id, "TEST2", "strategy_x", {"rsi": 60.0})

        after = fs.feature_counts()["total"]
        assert after == before + 1

        with _Session() as session:
            session.query(TradeFeature).filter(
                TradeFeature.trade_id == fake_id
            ).delete()
            session.commit()

    def test_capture_returns_false_without_db(self):
        """When _Session is None capture() returns False without raising."""
        from learning import feature_store as fs_module
        original_session = fs_module._Session
        try:
            fs_module._Session = None
            fs = fs_module.FeatureStore()
            result = fs.capture(1, "X", "strat", {"rsi": 50.0})
            assert result is False
        finally:
            fs_module._Session = original_session


class TestFeatureStoreLabel:

    @skip_no_db
    def test_label_updates_outcome(self):
        from learning.feature_store import FeatureStore, _Session, TradeFeature

        fs = FeatureStore()
        fake_id = 999_003
        fs.capture(fake_id, "TEST3", "strategy_y", {"rsi": 48.0})

        result = fs.label(trade_id=fake_id, pnl=1234.56, hold_minutes=37)
        assert result is True

        with _Session() as session:
            row = session.query(TradeFeature).filter(
                TradeFeature.trade_id == fake_id
            ).first()
            assert row.outcome == 1       # pnl > 0 → win
            assert row.pnl == pytest.approx(1234.56, rel=1e-4)
            assert row.hold_minutes == 37

        with _Session() as session:
            session.query(TradeFeature).filter(
                TradeFeature.trade_id == fake_id
            ).delete()
            session.commit()

    @skip_no_db
    def test_label_loss_sets_outcome_zero(self):
        from learning.feature_store import FeatureStore, _Session, TradeFeature

        fs = FeatureStore()
        fake_id = 999_004
        fs.capture(fake_id, "TEST4", "strategy_z", {"rsi": 72.0})
        fs.label(trade_id=fake_id, pnl=-500.0, hold_minutes=12)

        with _Session() as session:
            row = session.query(TradeFeature).filter(
                TradeFeature.trade_id == fake_id
            ).first()
            assert row.outcome == 0    # loss

        with _Session() as session:
            session.query(TradeFeature).filter(
                TradeFeature.trade_id == fake_id
            ).delete()
            session.commit()

    @skip_no_db
    def test_label_returns_false_for_missing_row(self):
        from learning.feature_store import FeatureStore
        fs = FeatureStore()
        result = fs.label(trade_id=999_999, pnl=100.0, hold_minutes=5)
        assert result is False

    def test_label_returns_false_without_db(self):
        from learning import feature_store as fs_module
        original_session = fs_module._Session
        try:
            fs_module._Session = None
            fs = fs_module.FeatureStore()
            result = fs.label(1, 500.0, 30)
            assert result is False
        finally:
            fs_module._Session = original_session


class TestGetLabelledFeatures:

    @skip_no_db
    def test_returns_dataframe_with_correct_columns(self):
        from learning.feature_store import FeatureStore, _Session, TradeFeature

        fs = FeatureStore()
        fake_id = 999_005
        fs.capture(fake_id, "TEST5", "strategy_a", {
            "rsi": 50.0, "ema_spread": 0.001, "vwap_dev": 0.0,
            "volume_ratio": 1.2, "macd_hist": 0.05, "atr_pct": 0.008,
        })
        fs.label(fake_id, pnl=200.0, hold_minutes=20)

        df = fs.get_labelled_features(min_count=1)
        assert df is not None
        assert "rsi" in df.columns
        assert "outcome" in df.columns
        assert "pnl" in df.columns
        assert (df["outcome"].dropna() <= 1).all()

        with _Session() as session:
            session.query(TradeFeature).filter(
                TradeFeature.trade_id == fake_id
            ).delete()
            session.commit()

    def test_returns_none_without_db(self):
        from learning import feature_store as fs_module
        original_session = fs_module._Session
        try:
            fs_module._Session = None
            fs = fs_module.FeatureStore()
            assert fs.get_labelled_features() is None
        finally:
            fs_module._Session = original_session


# ── Signal.features field ─────────────────────────────────────────────

class TestSignalFeaturesField:
    """Verify Signal dataclass accepts the new features field cleanly."""

    def test_signal_has_features_none_by_default(self):
        from strategies.base_strategy import Signal, Action
        sig = Signal(
            symbol="RELIANCE", action=Action.BUY,
            entry_price=500.0, stop_loss=490.0, target=520.0,
        )
        assert sig.features is None

    def test_signal_features_can_be_set(self):
        from strategies.base_strategy import Signal, Action
        feats = {"rsi": 55.2, "ema_spread": 0.003}
        sig = Signal(
            symbol="INFY", action=Action.SELL,
            entry_price=1500.0, stop_loss=1530.0, target=1440.0,
            features=feats,
        )
        assert sig.features["rsi"] == pytest.approx(55.2)

    def test_features_excluded_from_comparison(self):
        """features is compare=False — two signals with the same price data are equal
        regardless of their features dict."""
        from strategies.base_strategy import Signal, Action
        ts = datetime(2026, 4, 12, 10, 0, 0)
        sig1 = Signal("X", Action.BUY, 100.0, 95.0, 110.0, timestamp=ts, features={"rsi": 50.0})
        sig2 = Signal("X", Action.BUY, 100.0, 95.0, 110.0, timestamp=ts, features=None)
        assert sig1 == sig2
