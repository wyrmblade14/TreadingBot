"""
Bot lifecycle manager — start, stop, or restart the TreadingBot.

Usage:
    python scripts/restart_bot.py start    # start if not already running
    python scripts/restart_bot.py stop     # stop the running bot gracefully
    python scripts/restart_bot.py restart  # stop then start (default if no arg)
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT       = Path(__file__).resolve().parent.parent
PYTHON     = ROOT / "venv" / "Scripts" / "python.exe"
BOT_SCRIPT = ROOT / "scripts" / "run_bot.py"
LOG_FILE   = ROOT / "logs" / "bot_stdout.log"
STATE_FILE = ROOT / "logs" / "bot_state.json"


def _is_alive(pid: int) -> bool:
    """Check if a process is alive (Windows-compatible)."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True,
        )
        return str(pid) in result.stdout
    except Exception:
        return False


def _running_pid() -> int | None:
    """Read the bot's PID from bot_state.json; return None if not running."""
    if not STATE_FILE.exists():
        return None
    try:
        data = json.loads(STATE_FILE.read_text())
        pid  = int(data.get("pid", 0))
        if pid <= 0:
            return None
        return pid if _is_alive(pid) else None
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def _stop() -> None:
    pid = _running_pid()
    if pid is None:
        print("No running bot found — starting fresh.")
        return
    print(f"Stopping bot (PID {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(10):
            time.sleep(0.5)
            if not _is_alive(pid):
                break
        else:
            # Force kill on Windows via taskkill
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True)
    except Exception:
        pass
    STATE_FILE.unlink(missing_ok=True)
    print("Bot stopped.")


def _start() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    print("Starting bot...")
    with open(LOG_FILE, "a") as log_fd:
        proc = subprocess.Popen(
            [str(PYTHON), str(BOT_SCRIPT)],
            stdout=log_fd,
            stderr=log_fd,
            cwd=str(ROOT),
        )
    time.sleep(4)
    if _running_pid():
        print(f"Bot running (PID {proc.pid})")
        print(f"Logs: tail -f {LOG_FILE}")
    else:
        print("WARNING: Bot may have failed to start — check logs:")
        print(f"  {LOG_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="TreadingBot lifecycle manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/restart_bot.py start    # start if not running\n"
            "  python scripts/restart_bot.py stop     # stop gracefully\n"
            "  python scripts/restart_bot.py restart  # stop then start\n"
            "  python scripts/restart_bot.py          # same as restart"
        ),
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="restart",
        choices=["start", "stop", "restart"],
        help="Action to perform (default: restart)",
    )
    args = parser.parse_args()

    if args.action == "start":
        if _running_pid():
            print(f"Bot is already running (PID {_running_pid()}) — use 'restart' to reload.")
            sys.exit(0)
        _start()

    elif args.action == "stop":
        if _running_pid() is None:
            print("Bot is not running.")
            sys.exit(0)
        _stop()

    else:  # restart
        _stop()
        _start()
