"""
KiteTicker real-time candle builder.

Streams live NSE tick data via Zerodha's WebSocket feed and aggregates
ticks into OHLCV candles at any interval (5s, 1m, 5m, etc.).

How it works:
  1. KiteTicker connects to NSE via Zerodha's WebSocket
  2. Every price update (tick) calls on_ticks()
  3. Ticks are bucketed by interval and aggregated into OHLCV candles
  4. Completed candles are appended to each symbol's DataFrame
  5. signal_check() can call get_df(symbol) to get historical + live data

Why KiteTicker instead of yfinance during market hours?
  - yfinance delay: up to 15 minutes during live market
  - KiteTicker delay: < 1 second (real NSE WebSocket feed)
  - Enables 1-minute (or 5-second) signal checks vs 5-minute polling

Candle interval:
  TICK_CANDLE_SECONDS = 300  (5 minutes, default — matches current bot)
  Set to 60 for 1-minute candles (more signals, more noise)
  Set to 5 for 5-second candles (fastest possible)

Usage:
    from data.kite_ticker import get_ticker_feed

    feed = get_ticker_feed()    # singleton
    feed.start(watchlist)       # pass list of Kite symbols
    df   = feed.get_df("INFY")  # historical + live candles merged
    ltp  = feed.get_ltp("INFY") # latest tick price
    feed.stop()
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
from loguru import logger

from config.settings import IST
from data.kite_auth import get_kite_client, is_kite_available

# ── Tick candle granularity ───────────────────────────────────────────
# Ticks are bucketed into TICK_CANDLE_SECONDS bars.
# Strategies always receive 5-minute candles (resampled from these bars).
# Smaller value = more granular price history, but more memory per symbol.
TICK_CANDLE_SECONDS = 5   # 5-second bars — resampled to 5m for strategies


class _TickCandle:
    """Accumulates ticks within one time bucket into an OHLCV candle."""

    __slots__ = ("open", "high", "low", "close", "volume", "ts")

    def __init__(self, price: float, volume: int, ts: datetime) -> None:
        self.open   = price
        self.high   = price
        self.low    = price
        self.close  = price
        self.volume = volume
        self.ts     = ts   # candle open timestamp (bucket start)

    def update(self, price: float, volume: int) -> None:
        if price > self.high:
            self.high = price
        if price < self.low:
            self.low = price
        self.close  = price
        self.volume += volume

    def to_row(self) -> dict:
        return {
            "open":   self.open,
            "high":   self.high,
            "low":    self.low,
            "close":  self.close,
            "volume": self.volume,
        }


def _bucket_ts(ts: datetime, seconds: int) -> datetime:
    """Round a timestamp DOWN to the nearest N-second bucket."""
    epoch = ts.timestamp()
    bucketed = (epoch // seconds) * seconds
    return datetime.fromtimestamp(bucketed, tz=ts.tzinfo)


class KiteTickerFeed:
    """
    Manages a KiteTicker WebSocket connection and builds live OHLCV candles.

    Thread-safe: ticks arrive in the WebSocket thread; get_df() is called
    from the scheduler thread. All shared state is protected by _lock.
    """

    def __init__(self) -> None:
        self._kws          = None      # KiteTicker instance
        self._lock         = threading.Lock()
        self._token_map: dict[int, str]  = {}   # instrument_token → kite_symbol
        self._live_candles: dict[str, _TickCandle] = {}   # symbol → current open candle
        self._completed:   dict[str, list[dict]]   = defaultdict(list)  # symbol → list of closed candles
        self._ltp:         dict[str, float]         = {}   # symbol → latest price
        self._base_dfs:    dict[str, pd.DataFrame]  = {}   # historical backfill per symbol
        self._running      = False
        self._exit_callback = None   # fn(symbol, price) — called on every tick for exit monitoring

    # ── Public API ────────────────────────────────────────────────────

    def start(self, watchlist: list[str], base_dfs: dict[str, pd.DataFrame] | None = None) -> bool:
        """
        Connect to KiteTicker and start streaming ticks.

        Args:
            watchlist: list of Kite symbols, e.g. ["HDFCBANK", "INFY"]
            base_dfs:  optional dict of historical DataFrames per symbol
                       (from yfinance backfill) to merge with live candles

        Returns True if connected successfully, False otherwise.
        """
        if self._running:
            return True

        if not is_kite_available():
            logger.warning("KiteTickerFeed: Kite credentials not set — feed disabled")
            return False

        kite = get_kite_client()
        if kite is None:
            return False

        # Load base historical DataFrames
        if base_dfs:
            with self._lock:
                self._base_dfs.update(base_dfs)

        # Resolve instrument tokens for watchlist
        try:
            instruments = kite.instruments("NSE")
        except Exception as exc:
            logger.warning(f"KiteTickerFeed: could not fetch instruments — {exc}")
            return False

        token_map: dict[int, str] = {}
        watchlist_set = set(watchlist)
        for inst in instruments:
            sym = inst["tradingsymbol"]
            if sym in watchlist_set:
                token_map[inst["instrument_token"]] = sym

        if not token_map:
            logger.warning("KiteTickerFeed: no instrument tokens found for watchlist")
            return False

        missing = watchlist_set - set(token_map.values())
        if missing:
            logger.warning(f"KiteTickerFeed: no token for {missing} — they will use yfinance")

        with self._lock:
            self._token_map = token_map

        from config.settings import KITE_API_KEY, KITE_ACCESS_TOKEN
        from kiteconnect import KiteTicker

        self._kws = KiteTicker(KITE_API_KEY, KITE_ACCESS_TOKEN)
        self._kws.on_ticks   = self._on_ticks
        self._kws.on_connect = self._on_connect
        self._kws.on_close   = self._on_close
        self._kws.on_error   = self._on_error

        self._kws.connect(threaded=True)
        self._running = True
        logger.info(
            f"KiteTickerFeed started | {len(token_map)} symbols | "
            f"candle interval: {TICK_CANDLE_SECONDS}s"
        )
        return True

    def stop(self) -> None:
        """Disconnect WebSocket and stop the feed."""
        if self._kws and self._running:
            try:
                self._kws.close()
            except Exception:
                pass
        self._running = False
        logger.info("KiteTickerFeed stopped")

    def get_ltp(self, symbol: str) -> Optional[float]:
        """Return the latest tick price for a symbol, or None if no tick yet."""
        with self._lock:
            return self._ltp.get(symbol)

    def get_df(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        Return a merged DataFrame: historical backfill + live candles.
        Same format as fetch_ohlcv (open/high/low/close/volume, IST index).
        Returns None if no data available at all.
        """
        with self._lock:
            base    = self._base_dfs.get(symbol)
            closed  = self._completed.get(symbol, [])
            current = self._live_candles.get(symbol)

        rows = list(closed)
        if current is not None:
            rows.append({"ts": current.ts, **current.to_row()})

        if not rows and base is None:
            return None

        if rows:
            live_df = pd.DataFrame(rows)
            live_df = live_df.set_index("ts")
            live_df.index.name = None
            if live_df.index.tzinfo is None:
                live_df.index = live_df.index.tz_localize(IST)
            if base is not None:
                # Drop any historical candles that overlap with live data
                cutoff = live_df.index[0]
                base   = base[base.index < cutoff]
                return pd.concat([base, live_df]).sort_index()
            return live_df

        return base

    def register_exit_callback(self, fn) -> None:
        """
        Register a function called on every tick for real-time SL/target monitoring.

        The callback signature: fn(symbol: str, price: float) -> None
        Called from the WebSocket thread — must be fast and thread-safe.
        """
        self._exit_callback = fn

    def set_base_df(self, symbol: str, df: pd.DataFrame) -> None:
        """Register a historical DataFrame as the backfill baseline for a symbol."""
        with self._lock:
            self._base_dfs[symbol] = df

    def get_df_5m(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        Return a 5-minute OHLCV DataFrame for use by strategies.

        Merges:
          1. Historical 5m candles (from Kite REST / yfinance backfill)
          2. Today's live 5s tick bars resampled to 5m

        The last 5m candle is always "in progress" — its close price updates
        every 5 seconds as new ticks arrive. This lets strategies detect
        crossovers as they happen rather than waiting for the next 5m mark.

        Returns None if no data is available yet.
        """
        with self._lock:
            base    = self._base_dfs.get(symbol)
            closed  = list(self._completed.get(symbol, []))
            current = self._live_candles.get(symbol)

        # Build live 5s DataFrame
        rows = closed[:]
        if current is not None:
            rows.append({"ts": current.ts, **current.to_row()})

        if not rows:
            return base  # no live ticks yet — return historical only

        live_5s = pd.DataFrame(rows).set_index("ts")
        if live_5s.index.tzinfo is None:
            live_5s.index = live_5s.index.tz_localize(IST)
        else:
            live_5s.index = live_5s.index.tz_convert(IST)

        # Resample 5s → 5m: open=first tick, high=max, low=min,
        #                    close=last tick, volume=sum
        live_5m = live_5s.resample("5min").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        ).dropna(subset=["open"])

        if base is not None and not live_5m.empty:
            cutoff = live_5m.index[0]
            base   = base[base.index < cutoff]
            return pd.concat([base, live_5m]).sort_index()

        return live_5m if not live_5m.empty else base

    def is_running(self) -> bool:
        return self._running

    # ── WebSocket callbacks ───────────────────────────────────────────

    def _on_connect(self, ws, response) -> None:
        tokens = list(self._token_map.keys())
        ws.subscribe(tokens)
        # MODE_QUOTE gives last_price + volume — needed for accurate OHLCV candles
        ws.set_mode(ws.MODE_QUOTE, tokens)
        logger.info(f"KiteTickerFeed connected | subscribed to {len(tokens)} symbols")

    def _on_ticks(self, ws, ticks: list[dict]) -> None:
        now = datetime.now(IST)
        with self._lock:
            for tick in ticks:
                token = tick.get("instrument_token")
                sym   = self._token_map.get(token)
                if sym is None:
                    continue

                price  = float(tick.get("last_price", 0))
                volume = int(tick.get("last_quantity", 0))
                if price <= 0:
                    continue

                # Update LTP
                self._ltp[sym] = price

                # Real-time exit monitoring — fire callback immediately on every tick
                if self._exit_callback is not None:
                    try:
                        self._exit_callback(sym, price)
                    except Exception:
                        pass

                # Determine candle bucket
                bucket = _bucket_ts(now, TICK_CANDLE_SECONDS)
                candle = self._live_candles.get(sym)

                if candle is None:
                    # First tick for this symbol
                    self._live_candles[sym] = _TickCandle(price, volume, bucket)
                elif candle.ts == bucket:
                    # Same bucket — extend current candle
                    candle.update(price, volume)
                else:
                    # New bucket — close current candle, start new one
                    self._completed[sym].append({"ts": candle.ts, **candle.to_row()})
                    self._live_candles[sym] = _TickCandle(price, volume, bucket)

    def _on_close(self, ws, code, reason) -> None:
        self._running = False
        logger.warning(f"KiteTickerFeed disconnected: {code} — {reason}")

    def _on_error(self, ws, code, reason) -> None:
        logger.error(f"KiteTickerFeed error: {code} — {reason}")


# ── Module-level singleton ────────────────────────────────────────────
_feed: Optional[KiteTickerFeed] = None
_feed_lock = threading.Lock()


def get_ticker_feed() -> KiteTickerFeed:
    """Return the module-level KiteTickerFeed singleton."""
    global _feed
    with _feed_lock:
        if _feed is None:
            _feed = KiteTickerFeed()
    return _feed
