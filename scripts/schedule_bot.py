"""
Scheduler helper — install, remove, or check the TreadingBot scheduled jobs.

What is scheduling?
  On Mac/Linux, this uses cron — the built-in task scheduler. It runs the bot
  automatically at set times, even if you're not logged in (as long as the
  machine is on and not asleep).
  IMPORTANT: Your system timezone must be Asia/Kolkata (IST) for cron times to
  be correct. On Linux servers (which default to UTC) set TZ=Asia/Kolkata or
  convert times: 08:45 IST = 03:15 UTC.

  On Windows, this uses Windows Task Scheduler (schtasks), which is built
  into all Windows versions. Run the install command from an Administrator
  prompt if you see access-denied errors.

Daily schedule (all IST, Mon–Fri):
  08:45  Bot starts + fundamental watchlist pre-fetch
  08:45  Dashboard starts (http://localhost:8501)
  08:45  Watchdog starts (crash recovery loop)
  09:00  Pre-market scan (inside bot)
  09:15  Market open, strategies begin
  15:35  Bot auto-shuts down after daily report

Weekly (Saturday):
  10:00  Backtest all strategies, alert if win rate degrades

NSE holidays are handled internally — jobs no-op on holidays.

Usage:
    python scripts/schedule_bot.py --install    # add all scheduled jobs
    python scripts/schedule_bot.py --remove     # remove all scheduled jobs
    python scripts/schedule_bot.py --status     # show current status
    python scripts/schedule_bot.py --test       # run bot right now (for testing)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT    = Path(__file__).parent.parent.resolve()
START_SCRIPT    = PROJECT_ROOT / "scripts" / "start_bot.sh"
VENV_PYTHON     = (
    PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
    if sys.platform == "win32"
    else PROJECT_ROOT / "venv" / "bin" / "python"
)
MARKER          = "# TreadingBot"

# 08:45 IST = 03:15 UTC  |  Mon–Fri
# NOTE: cron times assume system TZ = Asia/Kolkata.
#       On UTC servers use "15 3 * * 1-5" instead.
CRON_BOT       = f"45 8 * * 1-5 {START_SCRIPT}  {MARKER}:bot"
CRON_DASHBOARD = f"45 8 * * 1-5 {VENV_PYTHON} {PROJECT_ROOT / 'scripts' / 'start_dashboard.sh'} >> {PROJECT_ROOT / 'logs' / 'dashboard.log'} 2>&1  {MARKER}:dashboard"
CRON_WATCHDOG  = f"45 8 * * 1-5 {VENV_PYTHON} {PROJECT_ROOT / 'scripts' / 'watchdog.py'} >> {PROJECT_ROOT / 'logs' / 'watchdog.log'} 2>&1  {MARKER}:watchdog"
CRON_BACKTEST  = f"0 10 * * 6 {VENV_PYTHON} {PROJECT_ROOT / 'scripts' / 'scheduled_backtest.py'} >> {PROJECT_ROOT / 'logs' / 'backtest_weekly.log'} 2>&1  {MARKER}:backtest"
ALL_CRON_LINES = [CRON_BOT, CRON_DASHBOARD, CRON_WATCHDOG, CRON_BACKTEST]

IS_WINDOWS = sys.platform == "win32"
TASK_NAME  = "TreadingBot"
TASK_DASHBOARD  = "TreadingBotDashboard"
TASK_WATCHDOG   = "TreadingBotWatchdog"
TASK_BACKTEST   = "TreadingBotWeeklyBacktest"


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


def _win_create_task(task_name: str, command: str, schedule: str, days: str, time_utc: str) -> None:
    """Create a single Windows Task Scheduler entry."""
    result = subprocess.run([
        "schtasks", "/Create",
        "/TN", task_name,
        "/TR", command,
        "/SC", schedule,
        "/D", days,
        "/ST", time_utc,
        "/F",
    ], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error creating task '{task_name}': {result.stderr.strip()}")
    else:
        print(f"  ✓ {task_name} — {schedule} {days} at {time_utc} UTC")


def _win_install() -> None:
    run_bot    = PROJECT_ROOT / "scripts" / "run_bot.py"
    watchdog   = PROJECT_ROOT / "scripts" / "watchdog.py"
    backtest   = PROJECT_ROOT / "scripts" / "scheduled_backtest.py"
    dashboard_cmd = f'"{VENV_PYTHON}" -m streamlit run "{PROJECT_ROOT / "dashboard" / "app.py"}"'

    print("Installing Windows Task Scheduler jobs…")
    _win_create_task(TASK_NAME,      f'"{VENV_PYTHON}" "{run_bot}"',  "WEEKLY", "MON,TUE,WED,THU,FRI", "03:15")
    _win_create_task(TASK_DASHBOARD, dashboard_cmd,                   "WEEKLY", "MON,TUE,WED,THU,FRI", "03:15")
    _win_create_task(TASK_WATCHDOG,  f'"{VENV_PYTHON}" "{watchdog}"', "WEEKLY", "MON,TUE,WED,THU,FRI", "03:15")
    _win_create_task(TASK_BACKTEST,  f'"{VENV_PYTHON}" "{backtest}"', "WEEKLY", "SAT",                  "04:30")
    print()
    print("All tasks run as the current user.")
    print("Schedule: 03:15 UTC = 08:45 IST | Backtest: 04:30 UTC = 10:00 IST (Saturday)")
    print("Ensure the PC is ON and not sleeping at those times.")


def _win_remove() -> None:
    for task in [TASK_NAME, TASK_DASHBOARD, TASK_WATCHDOG, TASK_BACKTEST]:
        result = subprocess.run(
            ["schtasks", "/Delete", "/TN", task, "/F"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"  Removed: {task}")
        else:
            print(f"  Not found (skipped): {task}")


def _win_status() -> None:
    any_found = False
    for task in [TASK_NAME, TASK_DASHBOARD, TASK_WATCHDOG, TASK_BACKTEST]:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", task, "/FO", "LIST"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            any_found = True
            # Print just the Status and Next Run Time lines
            for line in result.stdout.splitlines():
                if any(k in line for k in ("Task To Run", "Next Run", "Status", "Task Name")):
                    print(f"  {line.strip()}")
            print()
        else:
            print(f"  NOT installed: {task}")
    if not any_found:
        print("No TreadingBot tasks installed.")
        print("  Run: python scripts/schedule_bot.py --install")


# ── Public actions ─────────────────────────────────────────────────────────────

def install() -> None:
    if IS_WINDOWS:
        _win_install()
        return

    current = get_current_crontab()
    if MARKER in current:
        print("TreadingBot cron jobs are already installed:")
        for line in current.splitlines():
            if MARKER in line:
                print(f"  {line}")
        return

    additions = "\n".join(ALL_CRON_LINES)
    new_crontab = current.rstrip("\n") + "\n" + additions + "\n"
    set_crontab(new_crontab)
    print("Cron jobs installed successfully:")
    for line in ALL_CRON_LINES:
        print(f"  {line}")
    print()
    print("Bot + Dashboard + Watchdog: Mon–Fri at 08:45 IST")
    print("Weekly backtest           : Saturday at 10:00 IST")
    print("Bot auto-stops            : 15:35 IST after daily report")
    print()
    print("NOTE: Times assume system TZ = Asia/Kolkata.")
    print("      On UTC servers, use: 15 3 * * 1-5 (bot) and 30 4 * * 6 (backtest)")


def remove() -> None:
    if IS_WINDOWS:
        _win_remove()
        return

    current = get_current_crontab()
    if MARKER not in current:
        print("No TreadingBot cron jobs found.")
        return

    new_lines = [l for l in current.splitlines() if MARKER not in l]
    set_crontab("\n".join(new_lines) + "\n")
    print("All TreadingBot cron jobs removed.")


def status() -> None:
    if IS_WINDOWS:
        _win_status()
        return

    current = get_current_crontab()
    found = [l for l in current.splitlines() if MARKER in l]
    if found:
        print("TreadingBot cron jobs INSTALLED:")
        for line in found:
            tag = line.split(MARKER)[-1].strip().lstrip(":")
            print(f"  [{tag}] {line.split(MARKER)[0].strip()}")
        print()
        print("Bot + Dashboard + Watchdog: Mon–Fri 08:45 IST | Auto-stop 15:35 IST")
        print("Weekly backtest           : Saturday 10:00 IST")
    else:
        print("TreadingBot cron jobs are NOT installed.")
        print("  Run: python scripts/schedule_bot.py --install")


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
