"""
Telegram Command Handler — incoming message processor for TreadingBot.

Why this exists:
  The Kite access_token expires every midnight (SEBI rule). Previously, refreshing
  it meant SSH-ing into the server or sitting at the machine to run
  `python scripts/kite_login.py`. This module lets you do it entirely from
  Telegram on your phone — even if you're away from your desk.

  It also adds live status queries so you can check the bot's state without
  opening the dashboard.

Security:
  ONLY responds to messages from your TELEGRAM_CHAT_ID. Any message from
  a different user is silently dropped. This is critical — commands write
  to .env and interact with live broker sessions.

Implementation:
  Uses long-polling (getUpdates with timeout=30) — no webhook, no public
  server endpoint needed. Runs as a daemon thread inside the bot process,
  OR as a standalone script before the bot starts (for morning token refresh).

Supported commands:
  /kite_login  — two-step Kite access_token refresh via Telegram
  /status      — open trades, day P&L, adaptive mode, VIX/regime
  /pause       — pause new signal entries (sets _new_entries_allowed = False)
  /resume      — resume signal entries
  /help        — list all commands
"""

from __future__ import annotations

import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import requests
from loguru import logger

from config.settings import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    KITE_API_KEY, KITE_API_SECRET,
    IST,
)

# ── Constants ─────────────────────────────────────────────────────────

_POLL_TIMEOUT  = 30     # seconds per long-poll request
_RETRY_DELAY   = 5      # seconds to wait after a network error
_MAX_RETRIES   = 3      # consecutive failures before backing off

# ── State machine ─────────────────────────────────────────────────────

_IDLE               = "IDLE"
_WAITING_FOR_TOKEN  = "WAITING_FOR_TOKEN"

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


# ─────────────────────────────────────────────────────────────────────
#  Core handler class
# ─────────────────────────────────────────────────────────────────────

class TelegramCommandHandler:
    """
    Long-polling Telegram bot that handles owner commands.

    Start it as a background daemon:
        handler = TelegramCommandHandler()
        handler.start()

    It runs until the process exits (daemon thread) or stop() is called.
    """

    _GETUPD_URL  = "https://api.telegram.org/bot{token}/getUpdates"
    _SEND_URL    = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(
        self,
        token:   str = TELEGRAM_BOT_TOKEN,
        chat_id: str = TELEGRAM_CHAT_ID,
    ) -> None:
        self._token   = (token   or "").strip()
        self._chat_id = (chat_id or "").strip()
        self._enabled = bool(self._token and self._chat_id)

        self._offset: int = 0
        self._state:  str = _IDLE
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        if not self._enabled:
            logger.debug(
                "TelegramCommandHandler: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID "
                "not set — command handler disabled."
            )

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the polling loop in a daemon thread."""
        if not self._enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="telegram-cmd-handler",
            daemon=True,
        )
        self._thread.start()
        logger.info("Telegram command handler started (polling for /kite_login, /status, /help)")

    def stop(self) -> None:
        """Signal the polling loop to exit cleanly."""
        self._stop_event.set()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ── Polling loop ──────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        """Main loop — calls getUpdates, dispatches each message."""
        consecutive_errors = 0
        while not self._stop_event.is_set():
            try:
                updates = self._get_updates()
                consecutive_errors = 0
                for update in updates:
                    self._dispatch(update)
            except requests.RequestException as exc:
                consecutive_errors += 1
                backoff = min(_RETRY_DELAY * consecutive_errors, 60)
                logger.warning(
                    f"Telegram poll error ({consecutive_errors}): {exc} "
                    f"— retrying in {backoff}s"
                )
                time.sleep(backoff)
            except Exception as exc:
                logger.error(f"Telegram command handler unexpected error: {exc}")
                time.sleep(_RETRY_DELAY)

    def _get_updates(self) -> list[dict]:
        """
        Fetch new updates via long-polling.
        Returns a list of update dicts; advances self._offset.
        Blocks for up to _POLL_TIMEOUT seconds if there are no messages.
        """
        url    = self._GETUPD_URL.format(token=self._token)
        params = {
            "offset":  self._offset,
            "timeout": _POLL_TIMEOUT,
            "allowed_updates": ["message"],
        }
        resp = requests.get(url, params=params, timeout=_POLL_TIMEOUT + 5)
        resp.raise_for_status()
        data = resp.json()

        updates = data.get("result", [])
        if updates:
            self._offset = updates[-1]["update_id"] + 1
        return updates

    # ── Dispatcher ────────────────────────────────────────────────────

    def _dispatch(self, update: dict) -> None:
        """Route an incoming message to the appropriate handler."""
        msg = update.get("message", {})
        if not msg:
            return

        # Security gate — drop messages from any other user
        incoming_chat_id = str(msg.get("chat", {}).get("id", ""))
        if incoming_chat_id != self._chat_id:
            logger.warning(
                f"Telegram: dropped message from unauthorised chat_id={incoming_chat_id}"
            )
            return

        text = (msg.get("text") or "").strip()
        if not text:
            return

        logger.debug(f"Telegram command received: {text!r}")

        # ── State-aware dispatch ──────────────────────────────────────
        # If we're waiting for the redirect URL from a prior /kite_login,
        # treat ANY message as a potential redirect URL.
        if self._state == _WAITING_FOR_TOKEN:
            if text.startswith("/"):
                # User typed a new command — abort the pending flow
                self._state = _IDLE
                self._send("⚠️ Kite login cancelled. Send /kite_login to restart.")
            else:
                self._handle_kite_redirect(text)
            return

        # ── Command dispatch (IDLE state) ─────────────────────────────
        cmd = text.split()[0].lower().split("@")[0]   # strip @botname suffix

        if cmd == "/kite_login":
            self._cmd_kite_login()
        elif cmd == "/status":
            self._cmd_status()
        elif cmd == "/pause":
            self._cmd_pause()
        elif cmd == "/resume":
            self._cmd_resume()
        elif cmd in ("/help", "/start"):
            self._cmd_help()
        else:
            self._send(
                "Unknown command. Send /help for the command list."
            )

    # ── Commands ──────────────────────────────────────────────────────

    def _cmd_kite_login(self) -> None:
        """
        Kite daily login — sends a tap-and-go link.

        The user taps the URL, logs in on Zerodha's site, and the browser is
        automatically redirected to the bot's callback server which exchanges
        the token and confirms via Telegram. No URL-pasting needed.

        Fallback: if the callback server is unreachable (e.g. running locally
        without Nginx), the old paste-URL flow is still supported.
        """
        if not KITE_API_KEY:
            self._send(
                "⚠️ <b>KITE_API_KEY not set</b>\n"
                "Add it to .env before attempting Kite login."
            )
            return

        try:
            from kiteconnect import KiteConnect
        except ImportError:
            self._send(
                "⚠️ <code>kiteconnect</code> package not installed.\n"
                "Run: <code>pip install kiteconnect</code>"
            )
            return

        try:
            kite = KiteConnect(api_key=KITE_API_KEY)
            login_url = kite.login_url()
        except Exception as exc:
            self._send(f"⚠️ Failed to generate login URL: <code>{exc}</code>")
            return

        # Check whether the callback server is running (started by bot_controller or telegram_daemon).
        # If it is, the flow is fully automatic — no token pasting needed.
        callback_running = _is_callback_server_running()

        if callback_running:
            # Tap-and-go flow: browser lands on callback server, token saved automatically.
            # Requires Kite Redirect URL to point at this server:
            #   docker-compose up  →  http://<tailscale-ip>:7777
            #   make prod-up       →  http://<tailscale-ip>/kite/callback
            self._state = _IDLE   # no waiting — callback server handles the rest
            self._send(
                "🔑 <b>Kite Login</b>\n\n"
                "Tap below, log in with your Zerodha credentials + TOTP.\n"
                "<b>That's it</b> — the bot will confirm here automatically.\n\n"
                f'<a href="{login_url}">👉 Log in to Zerodha</a>'
            )
        else:
            # Fallback: callback server not running — paste-URL flow
            self._state = _WAITING_FOR_TOKEN
            self._send(
                "🔑 <b>Kite Login</b>\n\n"
                f'<a href="{login_url}">👉 Open Zerodha login</a>\n\n'
                "After logging in, your browser redirects to a URL like:\n"
                "<code>http://127.0.0.1/?request_token=xxxxxx</code>\n\n"
                "Paste that full URL here."
            )

    def _handle_kite_redirect(self, text: str) -> None:
        """
        Step 2 — process the redirect URL pasted by the user.
        Extracts request_token, exchanges it for access_token, updates .env.
        """
        # Accept either the full URL or just "request_token=XXXX"
        match = re.search(r"request_token=([A-Za-z0-9]+)", text)
        if not match:
            self._send(
                "⚠️ Could not find <code>request_token=</code> in your message.\n"
                "Please paste the full redirect URL or send /kite_login to restart."
            )
            return

        request_token = match.group(1)
        self._state   = _IDLE   # reset state regardless of outcome

        self._send(f"⏳ Exchanging token <code>{request_token[:8]}…</code>")

        if not KITE_API_SECRET:
            self._send(
                "⚠️ <b>KITE_API_SECRET not set in .env</b>\n"
                "Cannot generate session without the API secret."
            )
            return

        try:
            from kiteconnect import KiteConnect
            kite = KiteConnect(api_key=KITE_API_KEY)
            session_data = kite.generate_session(request_token, api_secret=KITE_API_SECRET)
        except Exception as exc:
            self._send(
                f"❌ <b>Token exchange failed</b>\n"
                f"<code>{exc}</code>\n\n"
                "The request_token may have expired (it's valid for ~10 minutes). "
                "Send /kite_login to try again."
            )
            return

        access_token = session_data["access_token"]
        user_name    = session_data.get("user_name", "")
        user_id      = session_data.get("user_id", "")

        # 1. Persist token (Vault if configured, always .env as fallback)
        try:
            from config.secrets import set_secret
            set_secret("KITE_ACCESS_TOKEN", access_token)
        except Exception:
            _update_env("KITE_ACCESS_TOKEN", access_token)

        # 2. Hot-reload in the running process so the bot picks it up immediately
        #    without needing a restart.
        os.environ["KITE_ACCESS_TOKEN"] = access_token
        try:
            import config.settings as _cfg
            _cfg.KITE_ACCESS_TOKEN = access_token
        except Exception:
            pass

        # 3. Refresh the kite_auth module's cached client
        try:
            from data import kite_auth as _ka
            _ka.KITE_ACCESS_TOKEN = access_token   # type: ignore[attr-defined]
        except Exception:
            pass

        self._send(
            f"✅ <b>Kite token updated</b>\n\n"
            f"User       <code>{user_name} ({user_id})</code>\n"
            f"Token      <code>{access_token[:8]}…</code>\n\n"
            "Token valid until midnight tonight.\n"
            "<i>The running bot will use this token immediately. "
            "If running in Docker, containers pick up the new token on next restart.</i>"
        )
        logger.info(f"Kite token refreshed via Telegram for user {user_name} ({user_id})")

    def _cmd_status(self) -> None:
        """Send a live snapshot of the bot's current state."""
        lines = ["📊 <b>Bot Status</b>"]

        # ── Adaptive mode ─────────────────────────────────────────────
        try:
            from config.adaptive import get_state
            s = get_state()
            mode_icon = {"NORMAL": "🟢", "DEFENSIVE": "🟡", "HALTED": "🔴"}.get(
                s.get("mode", ""), "⚪"
            )
            lines.append(
                f"Mode       {mode_icon} <b>{s.get('mode', '?')}</b>"
                + (f"  <i>({s.get('reason', '')})</i>" if s.get("reason") else "")
            )
        except Exception:
            pass

        # ── VIX + direction ───────────────────────────────────────────
        try:
            from data.india_vix import get_vix_data
            vix_data = get_vix_data()
            vix_val  = vix_data.get("vix")
            if vix_val:
                lines.append(f"VIX        <code>{vix_val:.1f}</code>  ({vix_data.get('level','?').upper()})")
        except Exception:
            pass

        try:
            from analysis.regime_detector import get_current_regime
            from analysis.market_direction import get_market_direction
            reg = get_current_regime()
            dir_ = get_market_direction()
            regime_icon = {"TRENDING": "📈", "RANGING": "↔️", "VOLATILE": "⚡"}.get(
                reg.value if reg else "", "❓"
            )
            dir_icon = {"UP": "⬆️", "DOWN": "⬇️", "NEUTRAL": "➡️"}.get(
                dir_.value if dir_ else "", "➡️"
            )
            lines.append(f"Regime     {regime_icon} {reg.value if reg else '?'}")
            lines.append(f"Direction  {dir_icon} {dir_.value if dir_ else '?'}")
        except Exception:
            pass

        # ── Open trades ───────────────────────────────────────────────
        try:
            from scheduler.job_runner import _order_mgr
            if _order_mgr and _order_mgr.open_symbols:
                for sym in _order_mgr.open_symbols:
                    t = _order_mgr.get_open_trade(sym)
                    if t:
                        from broker.base_broker import BaseBroker
                        try:
                            from scheduler.job_runner import _broker
                            ltp = _broker.get_ltp(sym) if _broker else t.entry_price
                        except Exception:
                            ltp = t.entry_price
                        pnl_dir = 1 if t.action.value == "BUY" else -1
                        unreal = round((ltp - t.entry_price) * pnl_dir * t.quantity, 0)
                        sign   = "+" if unreal >= 0 else ""
                        lines.append(
                            f"📌 <b>{sym}</b> {t.action.value}  {t.quantity}×"
                            f"  entry ₹{t.entry_price:.0f}  LTP ₹{ltp:.0f}"
                            f"  ({sign}₹{unreal:.0f})"
                        )
            else:
                lines.append("Positions  None open")
        except Exception:
            lines.append("Positions  (unavailable)")

        # ── Day P&L ───────────────────────────────────────────────────
        try:
            from scheduler.job_runner import _trade_log
            if _trade_log:
                today_trades = _trade_log.get_today_trades()
                day_pnl = sum(t.get("net_pnl") or 0 for t in today_trades)
                closed  = sum(1 for t in today_trades if t.get("net_pnl") is not None)
                wins    = sum(1 for t in today_trades if (t.get("net_pnl") or 0) > 0)
                sign    = "+" if day_pnl >= 0 else ""
                lines.append(
                    f"Day P&amp;L   <b>{sign}₹{day_pnl:,.0f}</b>  "
                    f"({wins}W / {closed - wins}L of {closed} closed)"
                )
        except Exception:
            pass

        # ── Kite token status ─────────────────────────────────────────
        from config.settings import KITE_ACCESS_TOKEN as _KAT
        if _KAT:
            lines.append(f"Kite token <code>{_KAT[:8]}…</code> ✅")
        else:
            lines.append("Kite token ❌ <i>not set — send /kite_login</i>")

        self._send("\n".join(lines))

    def _cmd_pause(self) -> None:
        """Pause new signal entries without stopping the bot."""
        try:
            import scheduler.job_runner as _jr
            _jr._new_entries_allowed = False
            self._send("⏸ <b>New entries paused.</b> Open positions still monitored. Send /resume to re-enable.")
            logger.info("Telegram /pause: new entries disabled")
        except Exception as exc:
            self._send(f"⚠️ Pause failed: <code>{exc}</code>")

    def _cmd_resume(self) -> None:
        """Resume new signal entries."""
        try:
            import scheduler.job_runner as _jr
            _jr._new_entries_allowed = True
            self._send("▶️ <b>New entries resumed.</b>")
            logger.info("Telegram /resume: new entries re-enabled")
        except Exception as exc:
            self._send(f"⚠️ Resume failed: <code>{exc}</code>")

    def _cmd_help(self) -> None:
        cb = "✅ active" if _is_callback_server_running() else "⚠️ not running"
        self._send(
            "🤖 <b>TreadingBot Commands</b>\n\n"
            "/kite_login — Refresh Kite token (tap link, done)\n"
            "/status     — Open positions, day P&amp;L, VIX, regime\n"
            "/pause      — Pause new signal entries\n"
            "/resume     — Resume signal entries\n"
            "/help       — This message\n\n"
            f"<i>Callback server: {cb}</i>"
        )

    # ── Send helper ───────────────────────────────────────────────────

    def _send(self, html: str) -> None:
        """Send an HTML message to the owner chat. Runs synchronously (we're already in a thread)."""
        if not self._enabled:
            return
        url = self._SEND_URL.format(token=self._token)
        payload = {
            "chat_id":    self._chat_id,
            "text":       html,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if not resp.ok:
                logger.warning(f"Telegram send failed: {resp.status_code} {resp.text[:80]}")
        except requests.RequestException as exc:
            logger.warning(f"Telegram send error: {exc}")


# ── Helpers ───────────────────────────────────────────────────────────

def _is_callback_server_running() -> bool:
    """Return True if the Kite OAuth callback server is active."""
    try:
        from notifications.kite_callback_server import _server
        return _server is not None
    except Exception:
        return False


# ── .env writer ───────────────────────────────────────────────────────

def _update_env(key: str, value: str) -> None:
    """Update or insert a key=value line in .env (mirrors scripts/kite_login.py)."""
    content = _ENV_FILE.read_text(encoding="utf-8") if _ENV_FILE.exists() else ""
    pattern = rf"^{re.escape(key)}\s*=.*$"
    replacement = f"{key}={value}"
    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    else:
        content = content.rstrip("\n") + f"\n{replacement}\n"
    _ENV_FILE.write_text(content, encoding="utf-8")


# ── Module-level singleton ────────────────────────────────────────────

_handler: Optional[TelegramCommandHandler] = None


def get_command_handler() -> TelegramCommandHandler:
    """Return the process-wide singleton TelegramCommandHandler."""
    global _handler
    if _handler is None:
        _handler = TelegramCommandHandler()
    return _handler


def start_command_handler() -> None:
    """Start the command handler daemon thread (idempotent — safe to call multiple times)."""
    get_command_handler().start()


def send_login_prompt() -> None:
    """
    Trigger the Kite login flow from outside the handler (e.g. from the scheduler).
    Equivalent to the user sending /kite_login on Telegram.
    No-op if Telegram is not configured.
    """
    get_command_handler()._cmd_kite_login()
