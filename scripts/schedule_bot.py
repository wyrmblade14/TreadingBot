"""
Cron scheduler helper — install, remove, or check the TreadingBot cron job.

What is cron?
  Cron is macOS/Linux's built-in task scheduler. It runs commands at set
  times automatically — even if you're not logged in (as long as the Mac
  is on and not asleep).

The bot runs Mon–Fri at 09:00 IST (03:30 UTC).
It auto-shuts down at 15:35 IST after the daily report.
NSE holidays are handled internally — jobs no-op on holidays.

Usage:
    python scripts/schedule_bot.py --install    # add cron job
    python scripts/schedule_bot.py --remove     # remove cron job
    python scripts/schedule_bot.py --status     # show current cron entry
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


def get_current_crontab() -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    # crontab -l exits 1 with "no crontab" when empty — that's fine
    return result.stdout if result.returncode == 0 else ""


def set_crontab(content: str) -> None:
    proc = subprocess.run(["crontab", "-"], input=content, text=True, capture_output=True)
    if proc.returncode != 0:
        print(f"Error setting crontab: {proc.stderr}")
        sys.exit(1)


def install() -> None:
    current = get_current_crontab()
    if MARKER in current:
        print("TreadingBot cron job is already installed:")
        for line in current.splitlines():
            if MARKER in line:
                print(f"  {line}")
        return

    new_crontab = current.rstrip("\n") + "\n" + CRON_LINE + "\n"
    set_crontab(new_crontab)
    print("✅ Cron job installed successfully.")
    print(f"   {CRON_LINE}")
    print()
    print("The bot will start automatically at 09:00 IST every weekday.")
    print("It auto-stops at 15:35 IST after the daily report.")
    print()
    print("⚠️  Make sure your Mac is ON and not asleep at 03:30 UTC.")
    print("   System Preferences → Battery → disable 'Enable Power Nap' if needed.")


def remove() -> None:
    current = get_current_crontab()
    if MARKER not in current:
        print("No TreadingBot cron job found.")
        return

    new_lines = [l for l in current.splitlines() if MARKER not in l]
    set_crontab("\n".join(new_lines) + "\n")
    print("✅ TreadingBot cron job removed.")


def status() -> None:
    current = get_current_crontab()
    found = [l for l in current.splitlines() if MARKER in l]
    if found:
        print("✅ TreadingBot cron job is INSTALLED:")
        for line in found:
            print(f"   {line}")
        print()
        print("Schedule: Mon–Fri | Start 09:00 IST | Auto-stop 15:35 IST")
    else:
        print("❌ TreadingBot cron job is NOT installed.")
        print("   Run: python scripts/schedule_bot.py --install")


def test_run() -> None:
    print("Starting bot now for testing (Ctrl+C to stop)...")
    venv_python = PROJECT_ROOT / "venv" / "bin" / "python"
    run_bot     = PROJECT_ROOT / "scripts" / "run_bot.py"
    try:
        subprocess.run([str(venv_python), str(run_bot)])
    except KeyboardInterrupt:
        pass  # child process already handled Ctrl+C and shut down cleanly


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage TreadingBot cron schedule",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true", help="Add cron job")
    group.add_argument("--remove",  action="store_true", help="Remove cron job")
    group.add_argument("--status",  action="store_true", help="Show current status")
    group.add_argument("--test",    action="store_true", help="Run bot right now")
    args = parser.parse_args()

    if args.install: install()
    elif args.remove: remove()
    elif args.status: status()
    elif args.test:   test_run()


if __name__ == "__main__":
    main()
