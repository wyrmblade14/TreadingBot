"""
Daily Kite Connect token generator.

Run this ONCE each morning before the market opens (before 9:00 AM IST):

    python scripts/kite_login.py

What it does:
  1. Prints a login URL — open it in your browser
  2. Log in with your Zerodha credentials
  3. After login you are redirected to a URL like:
         https://127.0.0.1/?request_token=xxxxxxxxxxxxxx&action=login&status=success
  4. Paste that full URL here
  5. The script generates a fresh access_token and saves it to .env

The access_token expires at midnight every day (SEBI rule).
Without a fresh token, Kite data feed is unavailable and the bot falls back to yfinance.

Why daily?
  SEBI mandates that brokers re-authenticate users every day to prevent
  unattended automated trading — a safety rule to protect retail investors.
"""

import os
import re
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import KITE_API_KEY, KITE_API_SECRET

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _update_env(key: str, value: str) -> None:
    """Update or insert a key=value line in .env."""
    content = ENV_FILE.read_text(encoding="utf-8")
    pattern = rf"^{re.escape(key)}\s*=.*$"
    replacement = f"{key}={value}"
    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    else:
        content += f"\n{replacement}\n"
    ENV_FILE.write_text(content, encoding="utf-8")


def main() -> None:
    if not KITE_API_KEY or not KITE_API_SECRET:
        print("ERROR: KITE_API_KEY and KITE_API_SECRET must be set in .env first.")
        sys.exit(1)

    try:
        from kiteconnect import KiteConnect
    except ImportError:
        print("ERROR: kiteconnect not installed. Run: pip install kiteconnect")
        sys.exit(1)

    kite = KiteConnect(api_key=KITE_API_KEY)
    login_url = kite.login_url()

    print()
    print("=" * 60)
    print("  KITE CONNECT — Daily Login")
    print("=" * 60)
    print()
    print("Step 1: Open this URL in your browser:")
    print()
    print(f"  {login_url}")
    print()
    print("Step 2: Log in with your Zerodha credentials.")
    print()
    print("Step 3: After login you will be redirected to a URL like:")
    print("  https://127.0.0.1/?request_token=xxxxxxxx&action=login&status=success")
    print()
    redirect_url = input("Step 4: Paste the full redirect URL here: ").strip()

    # Extract request_token from URL
    match = re.search(r"request_token=([^&]+)", redirect_url)
    if not match:
        print("ERROR: Could not find request_token in the URL. Please try again.")
        sys.exit(1)

    request_token = match.group(1)
    print(f"\nExtracting token: {request_token[:8]}...")

    try:
        data = kite.generate_session(request_token, api_secret=KITE_API_SECRET)
        access_token = data["access_token"]
        user_name    = data.get("user_name", "")
        user_id      = data.get("user_id", "")
    except Exception as exc:
        print(f"ERROR: Failed to generate session — {exc}")
        sys.exit(1)

    # Save to .env
    _update_env("KITE_ACCESS_TOKEN", access_token)

    print()
    print(f"Logged in as: {user_name} ({user_id})")
    print(f"Access token saved to .env")
    print()
    print("Token valid until midnight tonight.")
    print("If you ran this via 'make login', containers are restarting automatically.")
    print("If you ran this directly, restart the containers to pick up the new token:")
    print("  docker-compose restart bot dashboard watchdog")
    print()


if __name__ == "__main__":
    main()
