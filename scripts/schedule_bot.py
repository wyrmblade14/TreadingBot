"""
Scheduler helper — install, remove, or check the TreadingBot scheduled job.

What is scheduling?
  On Mac/Linux, this uses cron — the built-in task scheduler. It runs the bot
  automatically at set times, even if you're not logged in (as long as the
  machine is on and not asleep).

  On Windows, this uses Windows Task Scheduler (schtasks), which is built
  into all Windows versions. Run the install command from an Administrator
  prompt if you see access-denied errors.

The bot runs Mon–Fri at 09:00 IST (03:30 UTC).
It auto-shuts down at 15:35 IST after the daily report.
NSE holidays are handled internally — jobs no-op on holidays.

Usage:
    python scripts/schedule_bot.py --install    # add scheduled job
    python scripts/schedule_bot.py --remove     # remove scheduled job
    python scripts/schedule_bot.py --status     # show current status
    python scripts/schedule_bot.py --test       # run bot right now (for testing)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
START_SCRIPT = PROJECT_ROOT / "scripts" / "start_bot.sh"
MARKER       = "# TreadingBot"

# 09:00 IST = 03:30 UTC  |  Mon–Fri
CRON_LINE = f"0 9 * * 1-5 {START_SCRIPT}  {MARKER}"

IS_WINDOWS = sys.platform == "win32"
TASK_NAME  = "TreadingBot"


# ── Unix crontab helpers ──────────────────────────────────────────────────────

def get_current_crontab() -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    # crontab -l exits 1 with "no crontab" when empty — that's fine
    return result.stdout if result.returncode == 0 else ""


def set_crontab(content: str) -> None:
    proc = subprocess.run(["crontab", "-"], input=content, text=True, capture_output=True)
    if proc.returncode != 0:
        print(f"Error setting crontab: {proc.stderr}")
        sys.exit(1)


# ── Windows Task Scheduler helpers ────────────────────────────────────────────

def _win_task_exists() -> bool:
    result = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def _win_install() -> None:
    venv_python = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
    run_bot     = PROJECT_ROOT / "scripts" / "run_bot.py"
    if _win_task_exists():
        print("TreadingBot task is already installed in Task Scheduler.")
        return
    result = subprocess.run([
        "schtasks", "/Create",
        "/TN", TASK_NAME,
        "/TR", f'"{venv_python}" "{run_bot}"',
        "/SC", "WEEKLY",
        "/D", "MON,TUE,WED,THU,FRI",
        "/ST", "03:30",   # 03:30 UTC = 09:00 IST
        "/F",
    ], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error creating task: {result.stderr}")
        sys.exit(1)
    print("Task Scheduler job installed successfully.")
    print(f"  Task name : {TASK_NAME}")
    print("  Schedule  : Mon-Fri at 03:30 UTC (09:00 IST)")
    print()
    print("Note: The task runs as the current user.")
    print("      Ensure the PC is ON and not sleeping at 03:30 UTC.")


def _win_remove() -> None:
    if not _win_task_exists():
        print("No TreadingBot task found in Task Scheduler.")
        return
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Error removing task: {result.stderr}")
        sys.exit(1)
    print("TreadingBot Task Scheduler job removed.")


def _win_status() -> None:
    if _win_task_exists():
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"],
            capture_output=True, text=True,
        )
        print("TreadingBot task is INSTALLED:")
        print(result.stdout)
    else:
        print("TreadingBot task is NOT installed.")
        print("  Run: python scripts/schedule_bot.py --install")


# ── Public actions ─────────────────────────────────────────────────────────────

def install() -> None:
    if IS_WINDOWS:
        _win_install()
        return

    current = get_current_crontab()
    if MARKER in current:
        print("TreadingBot cron job is already installed:")
        for line in current.splitlines():
            if MARKER in line:
                print(f"  {line}")
        return

    new_crontab = current.rstrip("\n") + "\n" + CRON_LINE + "\n"
    set_crontab(new_crontab)
    print("Cron job installed successfully.")
    print(f"   {CRON_LINE}")
    print()
    print("The bot will start automatically at 09:00 IST every weekday.")
    print("It auto-stops at 15:35 IST after the daily report.")
    print()
    print("Make sure your machine is ON and not asleep at 03:30 UTC.")


def remove() -> None:
    if IS_WINDOWS:
        _win_remove()
        return

    current = get_current_crontab()
    if MARKER not in current:
        print("No TreadingBot cron job found.")
        return

    new_lines = [l for l in current.splitlines() if MARKER not in l]
    set_crontab("\n".join(new_lines) + "\n")
    print("TreadingBot cron job removed.")


def status() -> None:
    if IS_WINDOWS:
        _win_status()
        return

    current = get_current_crontab()
    found = [l for l in current.splitlines() if MARKER in l]
    if found:
        print("TreadingBot cron job is INSTALLED:")
        for line in found:
            print(f"   {line}")
        print()
        print("Schedule: Mon-Fri | Start 09:00 IST | Auto-stop 15:35 IST")
    else:
        print("TreadingBot cron job is NOT installed.")
        print("   Run: python scripts/schedule_bot.py --install")


def test_run() -> None:
    print("Starting bot now for testing (Ctrl+C to stop)...")
    venv_python = (
        PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
        if IS_WINDOWS
        else PROJECT_ROOT / "venv" / "bin" / "python"
    )
    run_bot = PROJECT_ROOT / "scripts" / "run_bot.py"
    try:
        subprocess.run([str(venv_python), str(run_bot)])
    except KeyboardInterrupt:
        pass  # child process already handled Ctrl+C and shut down cleanly


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage TreadingBot scheduled job",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true", help="Add scheduled job")
    group.add_argument("--remove",  action="store_true", help="Remove scheduled job")
    group.add_argument("--status",  action="store_true", help="Show current status")
    group.add_argument("--test",    action="store_true", help="Run bot right now")
    args = parser.parse_args()

    if args.install: install()
    elif args.remove: remove()
    elif args.status: status()
    elif args.test:   test_run()


if __name__ == "__main__":
    main()
