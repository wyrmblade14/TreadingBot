"""
Fully-automated Kite Connect token refresh — no browser, no human needed.

How it works
────────────
Zerodha's web login is a plain HTTPS form flow (no JavaScript required):

  1. POST /api/login          with user_id + password  → request_id
  2. POST /api/twofa          with request_id + TOTP    → session cookie
  3. GET  /connect/login      follow redirect           → callback URL
  4. Extract request_token from the callback URL
  5. kite.generate_session()  exchange for access_token
  6. Write KITE_ACCESS_TOKEN to .env, hot-reload os.environ + in-process config

Prerequisites (add to .env):
  ZERODHA_USER_ID       — your Zerodha client ID (e.g. AB1234)
  ZERODHA_PASSWORD      — your Zerodha login password
  ZERODHA_TOTP_SECRET   — TOTP secret (NOT the 6-digit code — the base32 seed
                          shown when you first set up 2FA in Zerodha's settings)

TOTP secret setup:
  • Go to Zerodha Console → Account → Security → External TOTP
  • Enable it; when shown the QR code click "show secret" to see the raw key
  • Copy that key here (looks like JBSWY3DPEHPK3PXP or similar)
  • Add to .env:  ZERODHA_TOTP_SECRET=JBSWY3DPEHPK3PXP

Security:
  • Credentials are read from .env — never hard-coded.
  • HTTPS only — Zerodha's login endpoint redirects HTTP to HTTPS.
  • The request_id + TOTP exchange is the same as typing in the web app.
  • SEBI mandates daily re-auth; this script satisfies that requirement
    programmatically the same way any browser-based login does.

Returns True on success, False on failure.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# ── project root on path ──────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from loguru import logger

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# Zerodha base URL (do NOT change — they may rate-limit or block non-browser UAs)
_BASE = "https://kite.zerodha.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "X-Kite-Version": "3",
    "Content-Type": "application/x-www-form-urlencoded",
}


def _update_env(key: str, value: str) -> None:
    """Update or insert KEY=VALUE in .env (same helper used by kite_login.py)."""
    content = ENV_FILE.read_text(encoding="utf-8")
    pattern = rf"^{re.escape(key)}\s*=.*$"
    replacement = f"{key}={value}"
    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    else:
        content += f"\n{replacement}\n"
    ENV_FILE.write_text(content, encoding="utf-8")


def _hot_reload(access_token: str) -> None:
    """Update the running process in-memory so no container restart is needed."""
    os.environ["KITE_ACCESS_TOKEN"] = access_token
    try:
        import config.settings as _cfg
        _cfg.KITE_ACCESS_TOKEN = access_token
    except Exception:
        pass
    try:
        import data.kite_auth as _auth
        _auth.KITE_ACCESS_TOKEN = access_token
    except Exception:
        pass


def auto_login() -> bool:
    """
    Perform a fully-automated Kite Connect login using stored credentials + TOTP.

    Returns True if a fresh access_token was obtained and saved, False otherwise.
    """
    import requests
    import pyotp

    user_id     = os.environ.get("ZERODHA_USER_ID", "").strip()
    password    = os.environ.get("ZERODHA_PASSWORD", "").strip()
    totp_secret = os.environ.get("ZERODHA_TOTP_SECRET", "").strip()
    api_key     = os.environ.get("KITE_API_KEY", "").strip()
    api_secret  = os.environ.get("KITE_API_SECRET", "").strip()

    if not all([user_id, password, totp_secret, api_key, api_secret]):
        logger.debug(
            "auto_kite_login: missing one or more of "
            "ZERODHA_USER_ID / ZERODHA_PASSWORD / ZERODHA_TOTP_SECRET / "
            "KITE_API_KEY / KITE_API_SECRET — skipping auto-login."
        )
        return False

    session = requests.Session()
    session.headers.update(_HEADERS)

    # ── Step 1: credential login ──────────────────────────────────────────────
    try:
        r1 = session.post(
            f"{_BASE}/api/login",
            data={"user_id": user_id, "password": password},
            timeout=15,
        )
        r1.raise_for_status()
        j1 = r1.json()
    except Exception as exc:
        logger.warning(f"auto_kite_login: login step failed — {exc}")
        return False

    if j1.get("status") != "success":
        logger.warning(f"auto_kite_login: login rejected — {j1.get('message', j1)}")
        return False

    request_id = j1["data"]["request_id"]
    logger.debug(f"auto_kite_login: login OK, request_id={request_id[:8]}...")

    # ── Step 2: TOTP two-factor auth ──────────────────────────────────────────
    try:
        totp_code = pyotp.TOTP(totp_secret).now()
        r2 = session.post(
            f"{_BASE}/api/twofa",
            data={
                "request_id": request_id,
                "twofa_value": totp_code,
                "twofa_type": "totp",
            },
            timeout=15,
        )
        r2.raise_for_status()
        j2 = r2.json()
    except Exception as exc:
        logger.warning(f"auto_kite_login: TOTP step failed — {exc}")
        return False

    if j2.get("status") != "success":
        logger.warning(f"auto_kite_login: TOTP rejected — {j2.get('message', j2)}")
        return False

    logger.debug("auto_kite_login: TOTP OK")

    # ── Step 3: follow the OAuth redirect to grab request_token ──────────────
    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=api_key)
        connect_url = kite.login_url()

        # Follow all redirects; the final URL has request_token=...
        r3 = session.get(connect_url, timeout=15, allow_redirects=True)
        final_url = r3.url
    except Exception as exc:
        logger.warning(f"auto_kite_login: OAuth redirect step failed — {exc}")
        return False

    # Extract request_token from URL query params
    parsed = urlparse(final_url)
    qs     = parse_qs(parsed.query)
    tokens = qs.get("request_token") or qs.get("token")
    if not tokens:
        # Fallback: regex search
        m = re.search(r"request_token=([^&\s]+)", final_url)
        tokens = [m.group(1)] if m else []

    if not tokens:
        logger.warning(
            f"auto_kite_login: request_token not found in redirect URL — {final_url[:120]}"
        )
        return False

    request_token = tokens[0]
    logger.debug(f"auto_kite_login: request_token={request_token[:8]}...")

    # ── Step 4: exchange for access_token ─────────────────────────────────────
    try:
        data = kite.generate_session(request_token, api_secret=api_secret)
        access_token = data["access_token"]
        user_name    = data.get("user_name", user_id)
    except Exception as exc:
        logger.warning(f"auto_kite_login: generate_session failed — {exc}")
        return False

    # ── Step 5: persist + hot-reload ─────────────────────────────────────────
    try:
        from config.secrets import set_secret
        set_secret("KITE_ACCESS_TOKEN", access_token)
    except Exception:
        _update_env("KITE_ACCESS_TOKEN", access_token)
    _hot_reload(access_token)

    logger.info(
        f"auto_kite_login: success — fresh token for {user_name} "
        f"({access_token[:8]}...). Valid until midnight."
    )
    return True


def main() -> None:
    """CLI entry-point — run standalone: python scripts/auto_kite_login.py"""
    print("TreadingBot — Automated Kite Login")
    print("=" * 40)
    ok = auto_login()
    if ok:
        print("Login successful. Token saved to .env.")
        print("If the bot is running, it has already hot-reloaded the new token.")
    else:
        print(
            "Auto-login failed. Check that all of the following are set in .env:\n"
            "  ZERODHA_USER_ID, ZERODHA_PASSWORD, ZERODHA_TOTP_SECRET\n"
            "  KITE_API_KEY, KITE_API_SECRET\n\n"
            "Falling back to manual login:\n"
            "  make login     — browser + paste token\n"
            "  make telegram  — Telegram-based flow from your phone"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
