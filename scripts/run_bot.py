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
    python scripts/run_bot.py --watchlist 5      # scan only first 5 NIFTY50 symbols
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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from config.settings import VIRTUAL_CAPITAL
from scheduler.bot_controller import get_controller


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TreadingBot Paper Trading Scheduler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--watchlist", default=10, type=int,
                        help="Number of NIFTY50 symbols to scan (default: 10)")
    parser.add_argument("--capital",   default=VIRTUAL_CAPITAL, type=float,
                        help=f"Starting paper capital in INR (default: ₹{VIRTUAL_CAPITAL:,.0f})")
    parser.add_argument("--dry-run",   action="store_true",
                        help="Print job schedule and exit without starting")
    args = parser.parse_args()

    logger.info("TreadingBot starting | mode=PAPER | no real money at risk")

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
    logger.info("Dashboard: streamlit run dashboard/app.py")

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
