"""
Kite Connect authentication helper.

Kite Connect requires a fresh access_token every trading day (SEBI rule).
The daily flow is:
  1. Run `python scripts/kite_login.py` each morning before 9:00 AM
  2. Visit the printed URL in your browser and log in with your Zerodha credentials
  3. After login you are redirected to a URL containing request_token=XXXX
  4. Paste that full URL back into the terminal
  5. The script exchanges it for an access_token and saves it to .env

This module provides `get_kite_client()` which returns an authenticated
KiteConnect instance ready for API calls. Returns None if no access_token
is set (i.e., before the daily login has been completed).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from loguru import logger

from config.settings import KITE_API_KEY, KITE_API_SECRET, KITE_ACCESS_TOKEN


def get_kite_client() -> Optional[object]:
    """
    Return an authenticated KiteConnect instance, or None if not configured.

    Returns None when:
      - KITE_API_KEY is not set in .env
      - KITE_ACCESS_TOKEN is not set (daily login not yet done)

    The returned object is a kiteconnect.KiteConnect instance. It is NOT
    cached — callers that need a persistent client should cache it themselves.
    """
    if not KITE_API_KEY:
        logger.debug("Kite: KITE_API_KEY not set — Kite feed disabled")
        return None

    if not KITE_ACCESS_TOKEN:
        logger.debug("Kite: KITE_ACCESS_TOKEN not set — run `python scripts/kite_login.py`")
        return None

    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=KITE_API_KEY)
        kite.set_access_token(KITE_ACCESS_TOKEN)
        return kite
    except Exception as exc:
        logger.warning(f"Kite: failed to create client — {exc}")
        return None


def is_kite_available() -> bool:
    """Quick check: returns True if Kite credentials are fully configured."""
    return bool(KITE_API_KEY and KITE_ACCESS_TOKEN)
