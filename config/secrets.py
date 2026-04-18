"""
Secrets manager — loads secrets from .env and os.environ.

Usage:
  from config.secrets import set_secret

  # Update a secret at runtime (e.g. new Kite token after daily login):
  set_secret("KITE_ACCESS_TOKEN", new_token)   # writes os.environ + .env
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from loguru import logger

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
_lock     = threading.Lock()


def set_secret(key: str, value: str) -> None:
    """Update a secret in os.environ and persist it to the local .env file."""
    os.environ[key] = value
    _update_env_file(key, value)


def _update_env_file(key: str, value: str) -> None:
    """Write key=value to .env (fallback persistence)."""
    with _lock:
        try:
            content = _ENV_FILE.read_text(encoding="utf-8") if _ENV_FILE.exists() else ""
            pattern = rf"^{re.escape(key)}\s*=.*$"
            replacement = f"{key}={value}"
            if re.search(pattern, content, flags=re.MULTILINE):
                content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
            else:
                content = content.rstrip("\n") + f"\n{replacement}\n"
            _ENV_FILE.write_text(content, encoding="utf-8")
        except Exception as exc:
            logger.debug(f"secrets: .env write failed — {exc}")
