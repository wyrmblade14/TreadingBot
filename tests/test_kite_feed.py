"""
Tests for data/kite_feed.py.

These keep Kite API calls mocked so they run offline.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from data import kite_feed
from data.instruments import KITE_SYMBOLS, KITE_TO_YF
from config.settings import IST


def _reset_token_cache() -> None:
    kite_feed._token_cache.clear()


class TestKiteSymbols:

    def test_tata_motors_symbol_is_current(self):
        """Tata Motors demerger changed NSE symbol from TATAMOTORS to TMPV."""
        assert "TMPV" in KITE_SYMBOLS
        assert KITE_TO_YF["TMPV"] == "TMPV.NS"
        assert "TATAMOTORS" not in KITE_SYMBOLS
        assert "TATAMOTORS" not in KITE_TO_YF


class TestKiteFeed:

    def test_fetch_kite_ohlcv_handles_pytz_datetimes_from_kite(self):
        """
        Kite returns pytz-aware datetimes. pandas/Python 3.14 can fail if those
        are put directly into a DataFrame, so fetch_kite_ohlcv normalises them.
        """
        _reset_token_cache()
        kite = MagicMock()
        kite.instruments.return_value = [
            {"tradingsymbol": "HDFCBANK", "instrument_token": 341249},
        ]
        kite.historical_data.return_value = [
            {
                "date": datetime(2026, 4, 7, 9, 15, tzinfo=IST),
                "open": 100.0,
                "high": 101.0,
                "low": 99.5,
                "close": 100.5,
                "volume": 1000,
            },
            {
                "date": datetime(2026, 4, 7, 9, 20, tzinfo=IST),
                "open": 100.5,
                "high": 102.0,
                "low": 100.0,
                "close": 101.5,
                "volume": 1500,
            },
        ]

        with patch("data.kite_feed.get_kite_client", return_value=kite):
            df = kite_feed.fetch_kite_ohlcv("HDFCBANK", days=1, interval="5minute")

        assert df is not None
        assert len(df) == 2
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert str(df.index.tz) == "Asia/Kolkata"
        kite.historical_data.assert_called_once()

    def test_load_instrument_tokens_does_not_warn_for_tmpv_when_kite_has_symbol(self):
        _reset_token_cache()
        kite = MagicMock()
        kite.instruments.return_value = [
            {"tradingsymbol": "TMPV", "instrument_token": 123456},
        ]

        result = kite_feed._load_instrument_tokens(kite, ["TMPV"])

        assert result == {"TMPV": 123456}
