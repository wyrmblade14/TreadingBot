"""
TreadingBot crash watchdog.

Runs alongside the bot (starting at 08:45 IST). Checks every 60 seconds
whether the bot is alive. If not, restarts it — up to MAX_RESTARTS times
per day to avoid restart loops on persistent crashes.

Exits naturally at 15:40 IST (market is closed, bot has already shut down).

Usage:
    python scripts/watchdog.py          # normally launched by cron / Task Scheduler
    python scripts/watchdog.py --once   # single check-and-restart (for testing)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scheduler import bot_state
from data.nse_holidays import is_holiday

# How long to wait between liveness checks (seconds)
CHECK_INTERVAL = 60
# Maximum restarts in one trading day before giving up
MAX_RESTARTS = 3

PYTHON     = (
    ROOT / "venv" / "Scripts" / "python.exe"
    if sys.platform == "win32"
    else ROOT / "venv" / "bin" / "python"
)
BOT_SCRIPT = ROOT / "scripts" / "run_bot.py"
LOG_FILE   = ROOT / "logs" / "watchdog.log"


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts}  {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _send_alert(msg: str) -> None:
    """Best-effort Telegram alert — never crashes the watchdog."""
    try:
        from notifications.telegram_notifier import TelegramNotifier
        TelegramNotifier().send_message(f"🔁 Watchdog: {msg}")
    except Exception:
        pass


def _now_ist() -> datetime:
    """Current time in IST (UTC+5:30)."""
    from pytz import timezone
    return datetime.now(timezone("Asia/Kolkata")).replace(tzinfo=None)


def _within_market_hours(now: datetime) -> bool:
    """True between 08:45 and 15:40 IST on weekdays that are not NSE holidays."""
    if now.weekday() >= 5:          # Saturday / Sunday
        return False
    if is_holiday(now.date()):
        return False
    start = now.replace(hour=8,  minute=45, second=0, microsecond=0)
    end   = now.replace(hour=15, minute=40, second=0, microsecond=0)
    return start <= now <= end


def _restart_bot() -> None:
    """Spawn run_bot.py as a background process."""
    log = ROOT / "logs" / "bot_stdout.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as f:
        subprocess.Popen(
            [str(PYTHON), str(BOT_SCRIPT)],
            stdout=f,
            stderr=f,
            cwd=str(ROOT),
        )


def run(once: bool = False) -> None:
    _log("Watchdog started")
    restart_count = 0

    while True:
        now = _now_ist()

        if not _within_market_hours(now):
            if once:
                _log("Outside market hours — exiting (--once mode)")
                return
            # Exit cleanly after market close; before market open just sleep
            if now.hour >= 15 and now.minute >= 40:
                _log("Market closed — watchdog exiting")
                return
            time.sleep(CHECK_INTERVAL)
            continue

        state = bot_state.read()  # returns None if PID is dead / state missing

        if state is None:
            restart_count += 1
            if restart_count > MAX_RESTARTS:
                msg = f"Bot is down but max restarts ({MAX_RESTARTS}) reached — manual intervention needed"
                _log(msg)
                _send_alert(msg)
            else:
                msg = f"Bot not running — restarting (attempt {restart_count}/{MAX_RESTARTS})"
                _log(msg)
                _send_alert(msg)
                _restart_bot()
                # Give the bot time to write its state file before next check
                time.sleep(10)
        else:
            _log(f"Bot alive (PID {state.get('pid')}) — OK")

        if once:
            return

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TreadingBot crash watchdog")
    parser.add_argument("--once", action="store_true", help="Single check only (for testing)")
    args = parser.parse_args()
    run(once=args.once)
