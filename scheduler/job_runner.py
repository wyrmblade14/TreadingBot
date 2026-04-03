"""
APScheduler Job Runner — automates the trading day in paper mode.

What this does:
  Runs a set of scheduled jobs every market day (Mon–Fri) in IST timezone.
  Each job mirrors what a live trader would do at that time of day.

Since there is no live WebSocket feed yet (Phase 6), each signal-check job
fetches the latest 5-minute candles from yfinance at run time. This is a
close approximation — it uses real prices but with a few minutes' delay.

Daily schedule:
  09:00  pre_market_scan   — Log NIFTY50 breadth, advance/decline
  09:15  market_open       — Reset risk state, log capital
  09:20–14:25 (every 5m)   — Fetch candles → signal → risk check → execute
  14:30  stop_new_entries  — Log cutoff reached (OrderManager enforces this too)
  15:15  square_off_all    — Close all open positions
  15:30  daily_report      — Print day's P&L summary

Usage:
  python scripts/run_bot.py
  python scripts/run_bot.py --watchlist 10   # scan first N NIFTY50 symbols
  python scripts/run_bot.py --dry-run        # print schedule, don't start
"""

from __future__ import annotations

import signal as _signal
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from analysis.market_overview import get_nifty_overview
from data.nse_holidays import is_trading_day
from notifications.telegram_notifier import get_notifier
from broker.paper_broker import PaperBroker
from config.settings import (
    IST, VIRTUAL_CAPITAL, TRADING_MODE,
    MARKET_OPEN, SHORT_SELLING_ENABLED, SQUAREOFF_TIME,
)
from data.historical import fetch_ohlcv
from data.instruments import NIFTY50_INSTRUMENTS, KITE_TO_YF
from data.kite_auth import is_kite_available
from data.kite_feed import fetch_kite_ohlcv
from data.kite_ticker import get_ticker_feed
from execution.order_manager import OrderManager
from execution.portfolio import Portfolio
from execution.trade_log import TradeLogger
from risk.risk_manager import RiskManager
from strategies.base_strategy import Action, Signal
from strategies.ema_crossover import EMACrossoverStrategy
from strategies.rsi_macd_combo import RSIMACDStrategy
from strategies.opening_range_breakout import ORBStrategy
from strategies.vwap_bounce import VWAPBounceStrategy


# ── Module-level singletons (created once, shared across all jobs) ────
_broker:      Optional[PaperBroker]   = None
_risk_mgr:    Optional[RiskManager]   = None
_order_mgr:   Optional[OrderManager]  = None
_trade_log:   Optional[TradeLogger]   = None
_portfolio:   Optional[Portfolio]     = None
_strategies:  list                    = []
_watchlist:   list[str]               = []
_new_entries_allowed: bool            = True
_scheduler:   Optional[BlockingScheduler] = None

def _on_tick_exit(symbol: str, price: float) -> None:
    """
    Called from the KiteTicker WebSocket thread on every live tick.

    Checks SL/target for the symbol immediately — no waiting for the next
    signal_check cycle. This is what closes positions at the actual breach
    price rather than up to 60 seconds later.

    Must be fast and never raise — any exception is silently swallowed by
    the ticker's try/except wrapper.
    """
    if _order_mgr is None or symbol not in _order_mgr.open_symbols:
        return
    if _broker:
        _broker.update_ltp(symbol, price)
    pnl = _order_mgr.check_exits(symbol, price)
    if pnl is not None and _risk_mgr is not None:
        _risk_mgr.on_position_closed(symbol, pnl)
        try:
            get_notifier().notify_exit(
                symbol=symbol,
                action="EXIT",
                price=price,
                pnl=pnl,
            )
        except Exception:
            pass


# Duplicate-signal guard: tracks (symbol, strategy, 5m-candle-timestamp) of
# the last signal fired. Prevents the same signal from firing multiple times
# within the same 5-minute candle when signal_check runs every 1 minute.
_last_signal_key: set[tuple] = set()


def setup(watchlist_size: int = 10, capital: float = VIRTUAL_CAPITAL) -> None:
    """
    Initialise all singletons before the scheduler starts.

    Args:
        watchlist_size: How many NIFTY50 symbols to scan each cycle.
                        Fewer = faster (each needs a yfinance fetch).
        capital:        Starting paper capital in INR.
    """
    global _broker, _risk_mgr, _order_mgr, _trade_log, _portfolio
    global _strategies, _watchlist

    _broker    = PaperBroker(initial_capital=capital)
    _risk_mgr  = RiskManager(capital=capital)
    _trade_log = TradeLogger()
    _order_mgr = OrderManager(_broker, _trade_log, trading_mode="paper")
    _portfolio = Portfolio(_broker, initial_capital=capital)

    _strategies = [
        EMACrossoverStrategy(),
        RSIMACDStrategy(),
        ORBStrategy(),
        VWAPBounceStrategy(),
    ]

    _watchlist = [i.kite_symbol for i in NIFTY50_INSTRUMENTS[:watchlist_size]]

    logger.info(
        f"Scheduler setup | capital=₹{capital:,.0f} "
        f"| watchlist={_watchlist} "
        f"| strategies={[s.name for s in _strategies]}"
    )

    # ── Restore open trades from previous session ─────────────────────
    # If the bot was stopped mid-session, today's open trades (exit_price=NULL)
    # are reloaded so we don't lose track of positions that were entered earlier.
    open_records = _trade_log.get_open_trades_today()
    if open_records:
        logger.warning(
            f"Recovering {len(open_records)} open trade(s) from previous session..."
        )
        for rec in open_records:
            _order_mgr.restore_open_trade(rec)
            # Also re-register this symbol in the risk manager as an open position
            if _risk_mgr:
                _risk_mgr.on_position_opened(rec["symbol"])
        logger.warning(
            f"Recovery complete. Open positions: {_order_mgr.open_symbols}"
        )
    else:
        logger.debug("No open trades from previous session — clean start.")

    # ── Restore risk state from previous session ──────────────────────
    # Rebuild daily_pnl and consecutive_losses from today's closed trades so
    # the 3% daily-loss halt and 3-consecutive-loss pause survive bot restarts.
    closed_today = [t for t in _trade_log.get_today_trades() if t.get("net_pnl") is not None]
    _risk_mgr.restore_daily_state(closed_today)


# ── Job functions ─────────────────────────────────────────────────────

def _is_market_day() -> bool:
    """Return True if today is an NSE trading day. Logs and returns False on holidays."""
    from datetime import date
    today = date.today()
    if not is_trading_day(today):
        logger.info(f"Today ({today}) is a market holiday or weekend — skipping job.")
        return False
    return True


def pre_market_scan() -> None:
    """09:00 — Log market overview before session opens."""
    if not _is_market_day():
        return
    _data_src = "Kite Connect (NSE live)" if is_kite_available() else "yfinance (fallback)"
    logger.info(f"=== PRE-MARKET SCAN (09:00 IST) === | Data source: {_data_src}")
    overview = get_nifty_overview(top_n=3)
    if overview:
        logger.info(
            f"NIFTY50: {overview.nifty_price:.0f} ({overview.nifty_change_pct:+.2f}%) | "
            f"A/D: {overview.advances}/{overview.declines} | "
            f"Mood: {'BULLISH' if overview.advances > overview.declines else 'BEARISH'}"
        )
        if overview.top_gainers:
            logger.info(f"Top gainers: {[g['symbol'] for g in overview.top_gainers]}")
    else:
        logger.warning("Could not fetch market overview (network issue?)")

    try:
        from data.india_vix import get_vix_data
        _vix = get_vix_data()
        _status = (
            "ALL entries suppressed" if _vix["skip_all"]
            else "BUY entries suppressed" if _vix["skip_buys"]
            else "Normal trading"
        )
        logger.info(f"India VIX: {_vix['vix']:.1f} ({_vix['level'].upper()}) | {_status}")
    except Exception as exc:
        logger.warning(f"VIX fetch failed: {exc}")


def market_open() -> None:
    """09:15 — Market opens. Reset risk state and start Kite live tick feed."""
    if not _is_market_day():
        return
    global _new_entries_allowed
    _new_entries_allowed = True
    summary = _broker.get_summary() if _broker else {}
    if _risk_mgr:
        _risk_mgr.new_day(capital=summary.get("cash", VIRTUAL_CAPITAL))
    logger.info(
        f"=== MARKET OPEN (09:15 IST) === "
        f"Capital: ₹{summary.get('cash', VIRTUAL_CAPITAL):,.0f}"
    )

    # Start KiteTicker live feed (uses yfinance base DataFrames as backfill)
    if is_kite_available():
        feed = get_ticker_feed()
        if not feed.is_running():
            feed.register_exit_callback(_on_tick_exit)
            feed.start(watchlist=_watchlist)
            if feed.is_running():
                logger.info("KiteTickerFeed: live tick stream active | WebSocket exit monitoring enabled")


def _fetch_symbol_data(kite_sym: str) -> tuple[str, object, object]:
    """
    Fetch 5m candles for one symbol. Safe to run in a thread pool.

    Data source priority:
      1. KiteTickerFeed — historical backfill + live ticks merged (real-time)
      2. Kite REST API  — historical OHLCV when ticker not yet running
      3. yfinance       — fallback when Kite is unavailable
    """
    if is_kite_available():
        # ── 1. Live ticker feed — 5s ticks resampled to 5m candles ────
        feed = get_ticker_feed()
        if feed.is_running():
            df = feed.get_df_5m(kite_sym)
            if df is not None and len(df) >= 10:
                ltp = feed.get_ltp(kite_sym) or float(df["close"].iloc[-1])
                return kite_sym, df, ltp

        # ── 2. Kite REST API (historical, no real-time ticks) ──────────
        try:
            df = fetch_kite_ohlcv(kite_sym, days=5, interval="5minute")
            if df is not None and len(df) >= 10:
                ltp = float(df["close"].iloc[-1])
                # Seed the ticker's historical base so future checks use
                # live 5s ticks merged with this backfill instead of REST
                feed = get_ticker_feed()
                if feed.is_running():
                    feed.set_base_df(kite_sym, df)
                return kite_sym, df, ltp
        except Exception as exc:
            logger.debug(f"Kite REST failed for {kite_sym} ({exc}) — falling back to yfinance")

    # ── 3. yfinance fallback ───────────────────────────────────────────
    yf_sym = KITE_TO_YF.get(kite_sym, kite_sym + ".NS")
    try:
        df = fetch_ohlcv(yf_sym, period="5d", interval="5m")
        if df is not None and len(df) >= 10:
            ltp = float(df["close"].iloc[-1])
            return kite_sym, df, ltp
    except Exception as e:
        logger.debug(f"No 5m data for {kite_sym}: {e}")
    return kite_sym, None, None


def signal_check() -> None:
    """
    09:20–14:25 every 5 min — Fetch latest candles and check for signals.
    Skipped automatically on NSE holidays.

    For each watchlist symbol:
      1. Fetch today's 5m candles from yfinance (all symbols in parallel)
      2. Run all strategies (sequential — shares risk state)
      3. Pass approved signals to OrderManager
      4. Check exits on any open positions
    """
    if not _is_market_day() or not _new_entries_allowed:
        return

    # ── Adaptive mode refresh ────────────────────────────────────────
    # Re-evaluate VIX, regime, risk state and time-of-day every 60 s.
    # Updates cfg.STRATEGY_CONFIGS in-place → strategies pick up changes
    # on next generate_signal() call without any restart.
    if _risk_mgr is not None:
        try:
            from config.adaptive import refresh as _adaptive_refresh
            _adaptive_refresh(
                consecutive_losses=_risk_mgr.state.consecutive_losses,
                day_pnl_pct=_risk_mgr.state.daily_loss_pct,
            )
        except Exception as _exc:
            logger.debug(f"Adaptive refresh skipped: {_exc}")

    # Lazy-start KiteTicker if Kite is available but ticker missed market_open
    if is_kite_available():
        feed = get_ticker_feed()
        if not feed.is_running():
            feed.register_exit_callback(_on_tick_exit)
            feed.start(watchlist=_watchlist)

    now_ist = datetime.now(IST)
    if now_ist.time() < MARKET_OPEN:
        return  # too early

    logger.debug(f"Signal check @ {now_ist.strftime('%H:%M')}")

    # Fetch all symbols in parallel — max_workers=3 avoids yfinance rate-limiting
    symbol_data: dict[str, tuple] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_fetch_symbol_data, sym): sym for sym in _watchlist}
        for future in as_completed(futures):
            sym, df, ltp = future.result()
            symbol_data[sym] = (df, ltp)

    # Process signals sequentially (RiskManager and OrderManager share state)
    for kite_sym in _watchlist:
        df, ltp = symbol_data.get(kite_sym, (None, None))

        # ── Check exit for any open position ─────────────────────────
        if _order_mgr and _order_mgr.has_open_trade(kite_sym):
            try:
                if ltp:
                    _broker.update_ltp(kite_sym, ltp)
                    net_pnl = _order_mgr.check_exits(kite_sym, ltp)
                    if net_pnl is not None:
                        _risk_mgr.on_position_closed(kite_sym, net_pnl)
                        get_notifier().notify_exit(
                            symbol=kite_sym,
                            action="BUY/SELL",   # direction logged by order_mgr
                            exit_price=ltp,
                            pnl=net_pnl,
                            reason="SL/target hit",
                        )
            except Exception as e:
                logger.warning(f"Exit check failed for {kite_sym}: {e}")
            continue  # one action per symbol per cycle

        if df is None:
            continue

        # Sync capital from broker before each new entry evaluation so a trade placed
        # earlier in this same cycle reduces the available capital for subsequent symbols
        if _risk_mgr and _broker:
            cash = _broker.get_summary().get("cash", 0)
            if cash > 0:
                _risk_mgr.state.capital = cash

        # Update LTP so PaperBroker can fill orders for this symbol
        _broker.update_ltp(kite_sym, ltp)

        # 5m candle timestamp — used to deduplicate signals across 1-min checks
        last_candle_ts = df.index[-1] if df is not None and not df.empty else None

        for strategy in _strategies:
            try:
                signal: Signal = strategy.generate_signal(kite_sym, df)
                if signal.action == Action.HOLD:
                    continue

                # Deduplicate: skip if we already fired this signal on the same candle
                sig_key = (kite_sym, strategy.name, last_candle_ts)
                if sig_key in _last_signal_key:
                    continue
                _last_signal_key.add(sig_key)
                # Keep set bounded — only retain keys from the last 30 minutes
                if len(_last_signal_key) > 200:
                    _last_signal_key.clear()

                # NSE intraday (MIS) short selling is legal on the cash equity segment.
                # SHORT_SELLING_ENABLED controls whether this bot uses it.
                if signal.action == Action.SELL and not SHORT_SELLING_ENABLED:
                    logger.debug(
                        f"Skipping SELL signal [{kite_sym} / {strategy.name}]: "
                        f"SHORT_SELLING_ENABLED=False"
                    )
                    continue

                decision = _risk_mgr.evaluate(signal)
                if not decision.approved:
                    logger.debug(
                        f"Signal rejected [{kite_sym} / {strategy.name}]: "
                        f"{decision.reason}"
                    )
                    continue

                placed = _order_mgr.execute_signal(decision.signal)
                if placed:
                    _risk_mgr.on_position_opened(kite_sym)
                    logger.info(
                        f"ORDER PLACED | {kite_sym} | {signal.action.value} "
                        f"| strategy={strategy.name} "
                        f"| entry={signal.entry_price:.2f} "
                        f"| sl={signal.stop_loss:.2f} "
                        f"| target={signal.target:.2f}"
                    )
                    get_notifier().notify_entry(
                        symbol=kite_sym,
                        action=signal.action.value,
                        price=signal.entry_price,
                        sl=signal.stop_loss,
                        target=signal.target,
                        strategy=strategy.name,
                        qty=decision.signal.quantity or 0,
                    )
                break  # one signal per symbol per cycle (first strategy wins)
            except Exception as e:
                logger.warning(f"Strategy error [{kite_sym} / {strategy.name}]: {e}")


def stop_new_entries() -> None:
    """14:30 — No new positions after this time."""
    if not _is_market_day():
        return
    global _new_entries_allowed
    _new_entries_allowed = False
    open_syms = _order_mgr.open_symbols if _order_mgr else []
    logger.info(
        f"=== NO NEW ENTRIES (14:30 IST) === "
        f"Open positions: {open_syms or 'none'}"
    )


def square_off_all() -> None:
    """15:15 — Force-close all open positions."""
    if not _is_market_day() or not _order_mgr:
        return
    # Update LTPs before squaring off
    for sym in list(_order_mgr.open_symbols):
        try:
            yf_sym = KITE_TO_YF.get(sym, sym + ".NS")
            ltp = _get_ltp(yf_sym)
            if ltp:
                _broker.update_ltp(sym, ltp)
        except Exception:
            pass

    results = _order_mgr.square_off_all()
    for sym, pnl in results.items():
        _risk_mgr.on_position_closed(sym, pnl)
    logger.info(
        f"=== SQUARE-OFF (15:15 IST) === "
        f"Closed {len(results)} position(s): {results}"
    )

    # Stop the live tick feed — market is closing
    feed = get_ticker_feed()
    if feed.is_running():
        feed.stop()


def daily_report() -> None:
    """15:30 — Print end-of-day summary and send Telegram report with CSV attachment."""
    if not _is_market_day() or not _broker:
        return
    summary = _broker.get_summary()
    today   = str(datetime.now(IST).date())
    pnl_rows = _trade_log.get_daily_pnl() if _trade_log else []
    today_pnl = next((r["net_pnl"] or 0 for r in pnl_rows if r["date"] == today), 0.0)
    num_trades = summary.get("total_trades", 0)
    cash       = summary.get("cash", 0)

    logger.info("=" * 60)
    logger.info("DAILY REPORT (15:30 IST)")
    logger.info(f"  Cash:          ₹{cash:,.0f}")
    logger.info(f"  Realised P&L:  ₹{summary.get('realised_pnl', 0):,.0f}")
    logger.info(f"  Today trades:  {num_trades}")
    logger.info(f"  Today net P&L: ₹{today_pnl:,.0f}")
    logger.info("=" * 60)

    today_trades = _trade_log.get_today_trades() if _trade_log else []
    get_notifier().notify_eod_report(
        cash=cash,
        net_pnl=today_pnl,
        num_trades=num_trades,
        trades=today_trades,
        trade_date=today,
    )


def auto_shutdown() -> None:
    """15:35 — Gracefully terminate the bot process after the trading day is done."""
    if not _is_market_day():
        return
    logger.info("=== AUTO-SHUTDOWN (15:35 IST) === Trading day complete. Bye!")
    import os as _os, signal as _sig
    _os.kill(_os.getpid(), _sig.SIGTERM)


# ── Helper ─────────────────────────────────────────────────────────────

def _get_ltp(yf_sym: str) -> Optional[float]:
    """Fetch latest traded price from yfinance (last close of today's 5m data)."""
    try:
        df = fetch_ohlcv(yf_sym, period="1d", interval="5m")
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])
    except Exception:
        pass
    return None


# ── Scheduler builder ─────────────────────────────────────────────────

def build_scheduler() -> BlockingScheduler:
    """Create and configure the APScheduler with all 6 market-day jobs."""
    global _scheduler
    sched = BlockingScheduler(timezone=IST)

    # Only on weekdays (Monday=0 … Friday=4)
    weekdays = "mon-fri"

    sched.add_job(pre_market_scan,  CronTrigger(day_of_week=weekdays, hour=9,  minute=0,  timezone=IST), id="pre_market_scan")
    sched.add_job(market_open,      CronTrigger(day_of_week=weekdays, hour=9,  minute=15, timezone=IST), id="market_open")
    sched.add_job(signal_check,     CronTrigger(day_of_week=weekdays, hour="9-14", minute="*/1", timezone=IST), id="signal_check")
    sched.add_job(stop_new_entries, CronTrigger(day_of_week=weekdays, hour=14, minute=30, timezone=IST), id="stop_new_entries")
    sched.add_job(square_off_all,   CronTrigger(day_of_week=weekdays, hour=15, minute=15, timezone=IST), id="square_off_all")
    sched.add_job(daily_report,     CronTrigger(day_of_week=weekdays, hour=15, minute=30, timezone=IST), id="daily_report")
    sched.add_job(auto_shutdown,    CronTrigger(day_of_week=weekdays, hour=15, minute=35, timezone=IST), id="auto_shutdown")

    _scheduler = sched
    return sched


def print_schedule(sched: BlockingScheduler) -> None:
    """Print the next fire time for each scheduled job."""
    print("\nScheduled jobs:")
    print(f"  {'Job':<22} {'Next run (IST)'}")
    print("  " + "-" * 50)
    for job in sched.get_jobs():
        # next_run_time is None before scheduler.start() — show trigger instead
        trigger_str = str(job.trigger)
        print(f"  {job.id:<22} {trigger_str}")
    print()


def _shutdown_handler(sig, frame) -> None:
    """Graceful shutdown: square off all positions, then exit."""
    logger.info("Shutdown signal received — squaring off all positions...")
    square_off_all()
    daily_report()
    if _scheduler:
        _scheduler.shutdown(wait=False)
    sys.exit(0)
