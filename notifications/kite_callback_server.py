"""
Kite OAuth Callback Server

Handles the Zerodha redirect after a successful browser login.

Flow:
  1. User taps /kite_login in Telegram
  2. Bot sends the Zerodha login URL
  3. User taps the URL on their phone → logs in on Zerodha's site
  4. Zerodha redirects the browser to THIS server at /kite/callback?request_token=xxx
  5. Server exchanges the request_token for an access_token
  6. Saves token to .env + hot-reloads in-process
  7. Returns a success page to the browser ("You can close this tab")
  8. Sends a Telegram confirmation

Kite Connect console setup:
  Set your app's Redirect URL to:   http://<tailscale-ip>/kite/callback
  (Nginx proxies /kite/callback → this server on port 7777 inside Docker)
"""

from __future__ import annotations

import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from loguru import logger

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

_SUCCESS_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kite Login</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; display: flex; align-items: center;
            justify-content: center; min-height: 100vh; margin: 0; background: #f0fdf4; }}
    .card {{ text-align: center; padding: 2rem; background: white;
             border-radius: 1rem; box-shadow: 0 4px 24px #0001; max-width: 360px; }}
    .icon {{ font-size: 3rem; }}
    h1 {{ color: #16a34a; margin: .5rem 0; font-size: 1.4rem; }}
    p  {{ color: #6b7280; margin: .5rem 0; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">✅</div>
    <h1>Login successful</h1>
    <p>Kite token saved. The bot is ready.</p>
    <p style="font-size:.85rem">You can close this tab.</p>
  </div>
</body>
</html>"""

_FAIL_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kite Login Failed</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; display: flex; align-items: center;
            justify-content: center; min-height: 100vh; margin: 0; background: #fef2f2; }}
    .card {{ text-align: center; padding: 2rem; background: white;
             border-radius: 1rem; box-shadow: 0 4px 24px #0001; max-width: 360px; }}
    .icon {{ font-size: 3rem; }}
    h1 {{ color: #dc2626; margin: .5rem 0; font-size: 1.4rem; }}
    p  {{ color: #6b7280; margin: .5rem 0; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">❌</div>
    <h1>Login failed</h1>
    <p>{reason}</p>
    <p style="font-size:.85rem">Send /kite_login in Telegram to try again.</p>
  </div>
</body>
</html>"""


def _update_env(key: str, value: str) -> None:
    content = _ENV_FILE.read_text(encoding="utf-8") if _ENV_FILE.exists() else ""
    pattern = rf"^{re.escape(key)}\s*=.*$"
    replacement = f"{key}={value}"
    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    else:
        content = content.rstrip("\n") + f"\n{replacement}\n"
    _ENV_FILE.write_text(content, encoding="utf-8")


def _hot_reload(access_token: str) -> None:
    os.environ["KITE_ACCESS_TOKEN"] = access_token
    try:
        import config.settings as _cfg
        _cfg.KITE_ACCESS_TOKEN = access_token
    except Exception:
        pass
    try:
        import data.kite_auth as _ka
        _ka.KITE_ACCESS_TOKEN = access_token  # type: ignore[attr-defined]
    except Exception:
        pass


def _exchange_token(request_token: str) -> tuple[bool, str, dict]:
    """Exchange request_token for access_token. Returns (ok, error_msg, session_data)."""
    from config.settings import KITE_API_KEY, KITE_API_SECRET
    if not KITE_API_KEY or not KITE_API_SECRET:
        return False, "KITE_API_KEY or KITE_API_SECRET not set in .env", {}
    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=KITE_API_KEY)
        data = kite.generate_session(request_token, api_secret=KITE_API_SECRET)
        return True, "", data
    except Exception as exc:
        return False, str(exc), {}


class _CallbackHandler(BaseHTTPRequestHandler):
    server_version = "TreadingBotKiteCallback/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        # Handle the Kite redirect: /kite/callback?request_token=xxx&status=success
        # Nginx strips the /kite/callback prefix, so this server also handles bare /?...
        tokens = qs.get("request_token") or qs.get("token", [])
        status = (qs.get("status") or [""])[0]

        if not tokens:
            self._html(400, _FAIL_HTML.format(reason="No request_token in the redirect URL."))
            return

        if status and status != "success":
            self._html(400, _FAIL_HTML.format(reason=f"Zerodha returned status: {status}"))
            return

        request_token = tokens[0]
        logger.info(f"Kite callback: received request_token={request_token[:8]}...")

        ok, err, session_data = _exchange_token(request_token)
        if not ok:
            logger.warning(f"Kite callback: token exchange failed — {err}")
            self._html(500, _FAIL_HTML.format(reason=err[:120]))
            self._notify_telegram(success=False, error=err)
            return

        access_token = session_data["access_token"]
        user_name    = session_data.get("user_name", "")
        user_id      = session_data.get("user_id", "")

        try:
            from config.secrets import set_secret
            set_secret("KITE_ACCESS_TOKEN", access_token)
        except Exception:
            _update_env("KITE_ACCESS_TOKEN", access_token)
        _hot_reload(access_token)

        logger.info(f"Kite callback: token saved for {user_name} ({user_id})")
        self._html(200, _SUCCESS_HTML)
        self._notify_telegram(success=True, user_name=user_name, user_id=user_id,
                              access_token=access_token)

    def _html(self, status: int, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _notify_telegram(
        self,
        success: bool,
        user_name: str = "",
        user_id: str = "",
        access_token: str = "",
        error: str = "",
    ) -> None:
        try:
            from notifications.telegram_command_handler import get_command_handler
            h = get_command_handler()
            if success:
                h._send(
                    f"✅ <b>Kite login complete</b>\n\n"
                    f"User   <code>{user_name} ({user_id})</code>\n"
                    f"Token  <code>{access_token[:8]}…</code>\n\n"
                    "Valid until midnight. Bot is trading with the fresh token."
                )
            else:
                h._send(
                    f"❌ <b>Kite login failed</b>\n"
                    f"<code>{error[:200]}</code>\n\n"
                    "Send /kite_login to try again."
                )
        except Exception as exc:
            logger.debug(f"Kite callback: Telegram notification failed — {exc}")

    def log_message(self, fmt: str, *args) -> None:
        logger.debug(f"kite-callback: {fmt % args}")


# ── Server lifecycle ──────────────────────────────────────────────────────────

_server: Optional[ThreadingHTTPServer] = None
_server_lock = threading.Lock()


def start_callback_server(host: str = "0.0.0.0", port: int = 7777) -> bool:
    """
    Start the Kite callback HTTP server in a daemon thread.
    Idempotent — safe to call multiple times. Returns True if started.
    """
    global _server
    with _server_lock:
        if _server is not None:
            return False   # already running
        try:
            _server = ThreadingHTTPServer((host, port), _CallbackHandler)
        except OSError as exc:
            logger.warning(f"Kite callback server: could not bind {host}:{port} — {exc}")
            return False

    thread = threading.Thread(
        target=_server.serve_forever,
        name="kite-callback-server",
        daemon=True,
    )
    thread.start()
    logger.info(f"Kite callback server listening on {host}:{port}")
    return True


def stop_callback_server() -> None:
    global _server
    with _server_lock:
        if _server:
            _server.shutdown()
            _server = None
