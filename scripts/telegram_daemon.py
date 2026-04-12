"""
Standalone Telegram command daemon.

Run this BEFORE the main bot starts to enable Telegram-based Kite login:

    python scripts/telegram_daemon.py

This is useful when you need to refresh the Kite token in the morning
before the bot is running — e.g. from a Docker entrypoint or as a
systemd unit.

Once started, send /kite_login from your Telegram account to begin
the token refresh flow.

The daemon runs until Ctrl+C.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from loguru import logger
from notifications.telegram_command_handler import get_command_handler


def main() -> None:
    handler = get_command_handler()

    if not handler._enabled:
        print(
            "ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env\n"
            "Add them and rerun."
        )
        sys.exit(1)

    # Start the OAuth callback server so the browser redirect is caught automatically
    try:
        from notifications.kite_callback_server import start_callback_server
        started = start_callback_server()
        if started:
            print("Kite callback server running on port 7777.")
    except Exception as exc:
        print(f"Warning: Kite callback server not started — {exc}")

    handler.start()
    print("Telegram daemon running. Send /help to your bot to see available commands.")
    print("Press Ctrl+C to stop.")

    try:
        while handler.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        handler.stop()
        print("\nStopped.")


if __name__ == "__main__":
    main()
