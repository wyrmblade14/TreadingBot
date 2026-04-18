"""
TreadingBot — main entry point for automated paper trading.

What this does:
  Starts the APScheduler job runner which simulates a full trading day
  in paper mode. Jobs fire at their scheduled IST times every weekday.

  Uses BotController so that the dashboard UI (Bot Control page) always
  reflects the real running state — whether the bot was started here or
  from the Streamlit UI.

Usage:
    python scripts/run_bot.py                    # start (paper mode)
    python scripts/run_bot.py --watchlist 5      # select top 5 fundamental candidates
    python scripts/run_bot.py --capital 50000    # custom starting capital
    python scripts/run_bot.py --dry-run          # print schedule and exit

Note:
    Live Kite integration is Phase 6b (deferred).
    This always runs in paper mode — no real orders are placed.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from loguru import logger
from config.settings import VIRTUAL_CAPITAL, WATCHLIST_SIZE, IST
from scheduler.bot_controller import get_controller


def _sleep_until_next_morning() -> None:
    """
    If the bot is restarted after market close (>=15:35 IST), sleep until
    08:29 IST the next calendar day, then exit so Docker brings it back
    fresh before market open.

    This avoids a wasteful setup + idle cycle when Docker's restart policy
    kicks in after the 15:35 auto_shutdown fires.
    """
    now = datetime.now(IST)
    after_close = now.hour > 15 or (now.hour == 15 and now.minute >= 35)
    if not after_close:
        return

    wake = (now + timedelta(days=1)).replace(hour=8, minute=29, second=0, microsecond=0)
    sleep_secs = (wake - now).total_seconds()
    logger.info(
        f"Started after market close ({now.strftime('%H:%M')} IST) — "
        f"sleeping {sleep_secs / 3600:.1f}h until {wake.strftime('%Y-%m-%d %H:%M')} IST, "
        f"then Docker will restart cleanly."
    )
    time.sleep(sleep_secs)
    sys.exit(0)


def _startup_token_refresh() -> None:
    """
    Called once at startup. If the Kite token is missing or expired, attempt
    a fully-automated login (ZERODHA_USER_ID + PASSWORD + TOTP_SECRET).
    Falls back gracefully — never blocks the bot from starting.
    """
    import os
    try:
        import config.settings as _cfg
        if _cfg.KITE_API_KEY and _cfg.KITE_ACCESS_TOKEN:
            from kiteconnect import KiteConnect
            kite = KiteConnect(api_key=_cfg.KITE_API_KEY)
            kite.set_access_token(_cfg.KITE_ACCESS_TOKEN)
            kite.profile()   # raises TokenException if expired
            logger.info("Startup: Kite token is valid — no refresh needed.")
            return
    except Exception:
        logger.info("Startup: Kite token missing or expired — attempting auto-login.")

    try:
        from scripts.auto_kite_login import auto_login
        if auto_login():
            logger.info("Startup: auto-login succeeded — token refreshed.")
        else:
            logger.warning(
                "Startup: auto-login skipped (ZERODHA_* credentials not set). "
                "Token will be refreshed via Telegram at 8:30 AM or run `make login` manually."
            )
    except Exception as exc:
        logger.warning(f"Startup: auto-login error — {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TreadingBot Paper Trading Scheduler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--watchlist", default=WATCHLIST_SIZE, type=int,
                        help=f"Number of fundamentals-ranked NIFTY50 symbols to scan (default: {WATCHLIST_SIZE})")
    parser.add_argument("--capital",   default=VIRTUAL_CAPITAL, type=float,
                        help=f"Starting paper capital in INR (default: ₹{VIRTUAL_CAPITAL:,.0f})")
    parser.add_argument("--dry-run",   action="store_true",
                        help="Print job schedule and exit without starting")
    args = parser.parse_args()

    # Guard: if Docker restarted us after the 15:35 auto_shutdown, sleep
    # through the night rather than doing a useless setup + idle cycle.
    _sleep_until_next_morning()

    logger.info("TreadingBot starting | mode=PAPER | no real money at risk")

    # ── Startup: auto-refresh Kite token if expired / missing ────────────────
    # This runs ONCE at startup so the bot never needs human intervention after
    # deploy — Docker restarts, server reboots, etc. all handled automatically.
    _startup_token_refresh()

    if args.dry_run:
        # Preview schedule without starting anything
        from scheduler.job_runner import setup, build_scheduler, print_schedule
        setup(watchlist_size=args.watchlist, capital=args.capital)
        sched = build_scheduler()
        print_schedule(sched)
        logger.info("--dry-run flag set. Scheduler NOT started. Exiting.")
        return

    # Start via BotController — keeps UI in sync with CLI state
    ctrl = get_controller()
    ok, msg = ctrl.start(watchlist_size=args.watchlist, capital=args.capital)
    if not ok:
        logger.warning(f"Could not start: {msg}")
        return

    logger.info(msg)
    logger.info("Press Ctrl+C to stop and square off all positions.")
    logger.info("Dashboard: http://localhost:3000  (React) | API: http://localhost:8000")

    def _shutdown(sig, frame):
        logger.info("Shutdown signal received — stopping bot...")
        ctrl.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    # SIGTERM: supported on Linux/Mac; on Windows it terminates the process
    # immediately (TerminateProcess) so the handler may not fire — that is
    # acceptable because the caller (dashboard stop button) clears the state
    # file itself after sending the signal.
    try:
        signal.signal(signal.SIGTERM, _shutdown)
    except (OSError, ValueError):
        pass   # Windows may not support custom SIGTERM handlers in all contexts

    # BackgroundScheduler runs in daemon threads; keep main thread alive.
    # State file is already written by ctrl.start() so the dashboard can
    # see this process as "running" immediately.
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        ctrl.stop()


if __name__ == "__main__":
    main()
