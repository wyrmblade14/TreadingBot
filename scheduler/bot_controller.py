"""
BotController — singleton that manages the trading bot lifecycle from the UI.

Why BackgroundScheduler (not BlockingScheduler)?
  Streamlit runs in a thread; BlockingScheduler would freeze it.
  BackgroundScheduler runs all jobs in daemon threads — the Streamlit
  process keeps responding while the bot ticks in the background.

Why a state file?
  The CLI (run_bot.py) and the Streamlit dashboard are separate OS processes.
  Python singletons only live inside one process. logs/bot_state.json is the
  shared source of truth: any process that calls get_status() sees the real
  state, regardless of which process started the bot.

Usage (from dashboard):
    from scheduler.bot_controller import get_controller
    ctrl = get_controller()

    ok, msg = ctrl.start(watchlist_size=WATCHLIST_SIZE, capital=VIRTUAL_CAPITAL)
    ok, msg = ctrl.stop()
    status  = ctrl.get_status()   # dict — reads state file, works cross-process
    events  = ctrl.get_events()   # list[dict] newest-first (in-process only)
"""

from __future__ import annotations

import os
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from config.settings import IST, VIRTUAL_CAPITAL, WATCHLIST_SIZE
import scheduler.bot_state as _state


def _oci_backup() -> None:
    """
    02:00 IST daily — dump PostgreSQL to Oracle Object Storage.
    Silently skipped if OCI CLI is not configured (local dev, non-Oracle deploys).
    """
    import subprocess
    script = Path(__file__).parent.parent / "oci" / "backup.sh"
    if not script.exists():
        return
    try:
        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            logger.info(f"OCI backup: {result.stdout.strip().splitlines()[-1]}")
        else:
            logger.warning(f"OCI backup failed: {result.stderr.strip()[:200]}")
    except FileNotFoundError:
        pass   # bash not available — skip silently
    except Exception as exc:
        logger.debug(f"OCI backup skipped: {exc}")

_RUNS_DIR = Path(__file__).parent.parent / "logs" / "runs"
_LOG_FMT  = "{time:YYYY-MM-DD HH:mm:ss} IST | {level:<8} | {message}"


class BotController:
    """
    Thread-safe singleton for start/stop/status of the paper trading bot.

    get_status() always reads the shared state file so the dashboard reflects
    bots started from the CLI as well as bots started from the UI.
    """

    _instance: Optional["BotController"] = None
    _class_lock = threading.Lock()

    def __new__(cls) -> "BotController":
        with cls._class_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._ready = False
                cls._instance = inst
        return cls._instance

    def __init__(self) -> None:
        if self._ready:
            return
        self._lock = threading.Lock()
        self._scheduler: Optional[BackgroundScheduler] = None
        self._events: deque = deque(maxlen=200)
        self._sink_id: Optional[int] = None      # loguru → event deque
        self._file_sink_id: Optional[int] = None  # loguru → log file
        self._log_path: Optional[Path] = None
        self._ready = True

    # ── Public API ─────────────────────────────────────────────────────

    def start(
        self,
        watchlist_size: int = WATCHLIST_SIZE,
        capital: float = VIRTUAL_CAPITAL,
    ) -> tuple[bool, str]:
        """
        Start the background scheduler.

        Returns:
            (True, message)  on success
            (False, message) if already running (checked via state file)
        """
        with self._lock:
            # Check state file — bot may be running in another process
            existing = _state.read()
            if existing:
                return False, (
                    f"Bot is already running (PID {existing['pid']}, "
                    f"started {existing['started_at']})."
                )

            # Add sinks BEFORE setup() so every log line is captured from the start
            self._sink_id = logger.add(
                self._loguru_sink,
                level="INFO",
                format="{message}",
            )

            _RUNS_DIR.mkdir(parents=True, exist_ok=True)
            date_str = datetime.now(IST).strftime("%Y-%m-%d")
            self._log_path = _RUNS_DIR / f"{date_str}.log"

            # Merge any leftover timestamped log files from today into the day file,
            # then delete them. This handles the case where the previous run was
            # killed hard (SIGKILL / Task Manager) and couldn't clean up its sink.
            import re as _re
            _ts_pattern = _re.compile(rf"^{_re.escape(date_str)}_\d{{2}}-\d{{2}}-\d{{2}}\.log$")
            for _old in sorted(_RUNS_DIR.iterdir()):
                if _ts_pattern.match(_old.name):
                    try:
                        with open(self._log_path, "a", encoding="utf-8") as _out:
                            _out.write(f"\n{'='*60}\n[merged from {_old.name}]\n{'='*60}\n")
                            _out.write(_old.read_text(encoding="utf-8", errors="replace"))
                        _old.unlink()
                    except OSError:
                        pass  # still locked — leave it, next restart will pick it up

            self._file_sink_id = logger.add(
                str(self._log_path),
                level="DEBUG",
                format=_LOG_FMT,
                encoding="utf-8",
                mode="a",   # append — multiple restarts on the same day share one file
                delay=False,
            )

            from scheduler.job_runner import setup
            setup(watchlist_size=watchlist_size, capital=capital)

            sched = BackgroundScheduler(timezone=IST)
            weekdays = "mon-fri"

            from scheduler.job_runner import (
                kite_login_reminder,
                pre_market_scan, market_open, signal_check,
                stop_new_entries, square_off_all, daily_report, auto_shutdown,
            )

            sched.add_job(_oci_backup,         CronTrigger(hour=2, minute=0, timezone=IST),   id="oci_backup")
            sched.add_job(kite_login_reminder, CronTrigger(day_of_week=weekdays, hour=8,      minute=30,   timezone=IST), id="kite_login_reminder")
            sched.add_job(pre_market_scan,     CronTrigger(day_of_week=weekdays, hour=9,      minute=0,    timezone=IST), id="pre_market_scan")
            sched.add_job(market_open,      CronTrigger(day_of_week=weekdays, hour=9,      minute=15,   timezone=IST), id="market_open")
            sched.add_job(signal_check,     CronTrigger(day_of_week=weekdays, hour="9-14", minute="*/1",timezone=IST), id="signal_check")
            sched.add_job(stop_new_entries, CronTrigger(day_of_week=weekdays, hour=14,     minute=30,   timezone=IST), id="stop_new_entries")
            sched.add_job(square_off_all,   CronTrigger(day_of_week=weekdays, hour=15,     minute=15,   timezone=IST), id="square_off_all")
            sched.add_job(daily_report,     CronTrigger(day_of_week=weekdays, hour=15,     minute=30,   timezone=IST), id="daily_report")
            sched.add_job(auto_shutdown,    CronTrigger(day_of_week=weekdays, hour=15,     minute=35,   timezone=IST), id="auto_shutdown")

            sched.start()
            self._scheduler = sched

            # Start Telegram command handler (handles /kite_login, /status, /pause, /resume)
            try:
                from notifications.telegram_command_handler import start_command_handler
                start_command_handler()
            except Exception as _tg_exc:
                logger.debug(f"Telegram command handler not started: {_tg_exc}")

            # Start Kite OAuth callback server (catches the browser redirect after login)
            try:
                from notifications.kite_callback_server import start_callback_server
                start_callback_server()
            except Exception as _cb_exc:
                logger.debug(f"Kite callback server not started: {_cb_exc}")

            started_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S %Z")
            _state.write(
                pid=os.getpid(),
                watchlist_size=watchlist_size,
                capital=capital,
                started_at=started_at,
                log_path=str(self._log_path),
            )

            msg = (
                f"Bot started | paper mode | "
                f"watchlist={watchlist_size} symbols | capital=₹{capital:,.0f}"
            )
            self._append("START", msg)

            from notifications.telegram_notifier import get_notifier
            from data.nse_holidays import is_trading_day, get_holiday_reason
            if is_trading_day():
                get_notifier().notify_bot_started(watchlist_size=watchlist_size, capital=capital)
            else:
                reason = get_holiday_reason()
                get_notifier().notify_market_closed(reason=reason)
            return True, msg

    def stop(self) -> tuple[bool, str]:
        """
        Stop the scheduler and square off all open positions.

        Works whether the bot was started in this process or the CLI process.
        If started in another process, sends SIGTERM to that PID.
        """
        with self._lock:
            existing = _state.read()
            if not existing:
                return False, "Bot is not running."

            bot_pid    = existing["pid"]
            my_pid     = os.getpid()
            is_mine    = (bot_pid == my_pid)

            if is_mine:
                # Bot lives in this process — clean shutdown
                from scheduler.job_runner import square_off_all, daily_report
                try:
                    square_off_all()
                    daily_report()
                except Exception as exc:
                    self._append("WARN", f"Error during square-off: {exc}")

                if self._scheduler:
                    self._scheduler.shutdown(wait=False)
                    self._scheduler = None

                if self._sink_id is not None:
                    try:
                        logger.remove(self._sink_id)
                    except Exception:
                        pass
                    self._sink_id = None

                if self._file_sink_id is not None:
                    try:
                        logger.remove(self._file_sink_id)
                    except Exception:
                        pass
                    self._file_sink_id = None
            else:
                # Bot lives in the CLI process — send SIGTERM
                sent = _state.stop_remote(bot_pid)
                if not sent:
                    _state.clear()
                    return False, f"Bot process (PID {bot_pid}) is no longer alive."

            _state.clear()
            msg = "Bot stopped. All positions squared off."
            self._append("STOP", msg)

            from notifications.telegram_notifier import get_notifier
            get_notifier().notify_bot_stopped()
            return True, msg

    def get_status(self) -> dict:
        """
        Return current bot status — reads the shared state file.

        Works cross-process: reflects bots started from CLI or from UI.
        """
        file_state = _state.read()

        if file_state:
            # Bot is running somewhere — show its config
            # Next jobs only available if this process owns the scheduler
            next_jobs: list[dict] = []
            if self._scheduler and file_state["pid"] == os.getpid():
                for job in self._scheduler.get_jobs():
                    nrt = job.next_run_time
                    next_jobs.append({
                        "id":       job.id,
                        "next_run": nrt.strftime("%H:%M %Z") if nrt else "—",
                    })

            return {
                "status":         "running",
                "started_at":     file_state.get("started_at"),
                "watchlist_size": file_state.get("watchlist_size", 10),
                "capital":        file_state.get("capital", VIRTUAL_CAPITAL),
                "pid":            file_state["pid"],
                "owned_by_ui":    file_state["pid"] == os.getpid(),
                "next_jobs":      next_jobs,
                "log_path":       file_state.get("log_path", ""),
            }

        return {
            "status":         "stopped",
            "started_at":     None,
            "watchlist_size": WATCHLIST_SIZE,
            "capital":        VIRTUAL_CAPITAL,
            "pid":            None,
            "owned_by_ui":    False,
            "next_jobs":      [],
        }

    def get_events(self) -> list[dict]:
        """Return recent log events, newest first. Only available in the owning process."""
        return list(self._events)

    def clear_events(self) -> None:
        self._events.clear()

    # ── Internal ───────────────────────────────────────────────────────

    def _loguru_sink(self, message) -> None:
        record = message.record
        self._append(record["level"].name, record["message"])

    def _append(self, level: str, msg: str) -> None:
        ts = datetime.now(IST).strftime("%H:%M:%S")
        self._events.appendleft({"time": ts, "level": level, "msg": msg})


def get_controller() -> BotController:
    """Return the process-wide singleton BotController."""
    return BotController()
