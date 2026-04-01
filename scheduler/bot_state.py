"""
Shared bot state — persisted to disk so any process can read it.

Why a file?
  The CLI (`run_bot.py`) and the Streamlit dashboard are separate OS processes.
  Python singletons only live inside one process. A JSON file on disk is the
  simplest way for both to share a single source of truth about whether the
  bot is running, which PID owns it, and what config it's using.

File: logs/bot_state.json
  Written by BotController.start()
  Cleared by BotController.stop()
  Read by BotController.get_status() — in any process
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

_STATE_FILE = Path(__file__).parent.parent / "logs" / "bot_state.json"


def write(
    pid:            int,
    watchlist_size: int,
    capital:        float,
    started_at:     str,
    log_path:       str = "",
) -> None:
    _STATE_FILE.parent.mkdir(exist_ok=True)
    _STATE_FILE.write_text(json.dumps({
        "status":         "running",
        "pid":            pid,
        "watchlist_size": watchlist_size,
        "capital":        capital,
        "started_at":     started_at,
        "log_path":       log_path,
    }))


def read() -> Optional[dict]:
    """Return state dict if file exists and the recorded PID is still alive."""
    if not _STATE_FILE.exists():
        return None
    try:
        state = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None

    pid = state.get("pid")
    if not pid:
        clear()
        return None

    try:
        alive = _pid_alive(pid)
    except Exception:
        alive = True   # can't check — assume alive rather than deleting state

    if not alive:
        # Process is no longer alive — treat as stopped
        clear()
        return None

    return state


def clear() -> None:
    if _STATE_FILE.exists():
        _STATE_FILE.unlink(missing_ok=True)


def stop_remote(pid: int) -> bool:
    """Terminate a bot running in another process. Returns True if sent."""
    import sys
    if sys.platform == "win32":
        import ctypes
        try:
            handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
            if handle == 0:
                return False
            result = ctypes.windll.kernel32.TerminateProcess(handle, 0)
            ctypes.windll.kernel32.CloseHandle(handle)
            return bool(result)
        except Exception:
            return False
    import signal as _signal
    try:
        os.kill(pid, _signal.SIGTERM)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _pid_alive(pid: int) -> bool:
    """Check if a process is still running without killing it."""
    import sys
    if sys.platform == "win32":
        # os.kill(pid, 0) raises OSError on Windows — use psutil or ctypes instead
        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x0400, False, pid)  # PROCESS_QUERY_INFORMATION
            if handle == 0:
                return False
            exit_code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return exit_code.value == 259  # STILL_ACTIVE
        except Exception:
            return False
    try:
        os.kill(pid, 0)   # signal 0 = existence check only
        return True
    except (ProcessLookupError, PermissionError):
        return False
