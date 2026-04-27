"""
Kite Connect login via Telegram — interactive OAuth flow for CI/GitHub Actions.

Flow:
  1. Generate Kite login URL and send it to you on Telegram
  2. You log in via browser (phone/desktop) and get redirected to a URL with request_token
  3. Paste that full redirect URL (or just the request_token) back on Telegram
  4. Script exchanges request_token for access_token and writes it to .env

Required env vars (GitHub Secrets → .env in CI):
  KITE_API_KEY        — Kite Connect app API key
  KITE_API_SECRET     — Kite Connect app API secret
  TELEGRAM_BOT_TOKEN  — from @BotFather
  TELEGRAM_CHAT_ID    — your personal chat ID with the bot (run @userinfobot to get it)

Returns exit code 0 on success, 1 on failure.
If it fails, the weekly review continues with yfinance data (no live prices).
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from loguru import logger

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
OTP_TIMEOUT_S = 600  # 10 minutes to complete the login


# ── Telegram helpers ──────────────────────────────────────────────────────────

def _tg_send(token: str, chat_id: str, text: str) -> None:
    import requests
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": False},
        timeout=10,
    ).raise_for_status()


def _tg_poll(token: str, chat_id: str, offset: int | None) -> tuple[list[dict], int | None]:
    """Single long-poll (30s). Returns (messages_from_our_chat, next_offset)."""
    import requests
    params = {"timeout": 30, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    r = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params=params, timeout=35,
    )
    updates = r.json().get("result", [])
    next_offset = (updates[-1]["update_id"] + 1) if updates else offset
    msgs = [
        u["message"] for u in updates
        if "message" in u
        and str(u["message"].get("chat", {}).get("id", "")) == str(chat_id)
    ]
    return msgs, next_offset


def _tg_drain(token: str, chat_id: str) -> int | None:
    """Drain pending updates so we don't process stale messages. Returns next offset."""
    import requests
    r = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params={"timeout": 0}, timeout=10,
    )
    updates = r.json().get("result", [])
    return (updates[-1]["update_id"] + 1) if updates else None


def _extract_request_token(text: str) -> str | None:
    """Extract request_token from a pasted redirect URL or raw token string."""
    text = text.strip()
    # Try as URL first
    parsed = urlparse(text)
    qs = parse_qs(parsed.query)
    if "request_token" in qs:
        return qs["request_token"][0]
    # Regex fallback (handles partial pastes)
    m = re.search(r"request_token=([A-Za-z0-9]+)", text)
    if m:
        return m.group(1)
    # Maybe they pasted the raw token directly (32+ hex/alphanum chars)
    if re.fullmatch(r"[A-Za-z0-9]{20,}", text):
        return text
    return None


# ── Main login flow ───────────────────────────────────────────────────────────

def _update_env(key: str, value: str) -> None:
    content = ENV_FILE.read_text(encoding="utf-8")
    pattern = rf"^{re.escape(key)}\s*=.*$"
    replacement = f"{key}={value}"
    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    else:
        content += f"\n{replacement}\n"
    ENV_FILE.write_text(content, encoding="utf-8")


def login_via_telegram() -> bool:
    tg_token   = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat    = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    api_key    = os.environ.get("KITE_API_KEY", "").strip()
    api_secret = os.environ.get("KITE_API_SECRET", "").strip()

    if not all([tg_token, tg_chat, api_key, api_secret]):
        logger.warning(
            "kite_login_via_telegram: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID / "
            "KITE_API_KEY / KITE_API_SECRET not set — skipping Kite login"
        )
        return False

    from kiteconnect import KiteConnect
    kite = KiteConnect(api_key=api_key)
    login_url = kite.login_url()

    # Drain stale updates before we start listening
    offset = _tg_drain(tg_token, tg_chat)

    _tg_send(tg_token, tg_chat,
        "🤖 TreadingBot weekly strategy review is starting.\n\n"
        "👉 Log in to Kite using the link below, then paste the full redirect URL here.\n\n"
        f"{login_url}\n\n"
        "The redirect URL will look like:\n"
        "https://your-redirect/?request_token=XXXXXX&action=login&status=success\n\n"
        "⏳ You have 10 minutes."
    )
    logger.info(f"kite_login_via_telegram: login URL sent, waiting for request_token...")

    deadline = time.monotonic() + OTP_TIMEOUT_S
    while time.monotonic() < deadline:
        msgs, offset = _tg_poll(tg_token, tg_chat, offset)
        for msg in msgs:
            text = msg.get("text", "").strip()
            request_token = _extract_request_token(text)
            if request_token:
                logger.info(f"kite_login_via_telegram: request_token received ({request_token[:8]}...)")
                break
        else:
            continue
        break
    else:
        _tg_send(tg_token, tg_chat,
            "⏰ Timed out waiting for login. "
            "Weekly review will continue with yfinance data (no live prices)."
        )
        return False

    # Exchange request_token for access_token
    try:
        data = kite.generate_session(request_token, api_secret=api_secret)
        access_token = data["access_token"]
        user_name    = data.get("user_name", "unknown")
    except Exception as exc:
        _tg_send(tg_token, tg_chat, f"❌ generate_session failed: {exc}\nWeekly review continues with yfinance.")
        logger.warning(f"kite_login_via_telegram: generate_session failed — {exc}")
        return False

    # Persist
    try:
        from config.secrets import set_secret
        set_secret("KITE_ACCESS_TOKEN", access_token)
    except Exception:
        _update_env("KITE_ACCESS_TOKEN", access_token)

    os.environ["KITE_ACCESS_TOKEN"] = access_token

    _tg_send(tg_token, tg_chat,
        f"✅ Kite login successful — {user_name}\n"
        f"Token: {access_token[:8]}... (valid until midnight IST)\n\n"
        f"Running weekly strategy review now..."
    )
    logger.success(f"kite_login_via_telegram: success — token for {user_name}")
    return True


if __name__ == "__main__":
    ok = login_via_telegram()
    sys.exit(0 if ok else 1)
