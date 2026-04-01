"""
Telegram Notifier — sends trade alerts to your phone via Telegram.

Why Telegram?
  You can't watch the dashboard all day. Telegram lets the bot push
  important events to your phone the moment they happen:
    • A new trade is entered
    • A stop-loss or target is hit
    • The daily P&L summary at 3:30 PM
    • Bot start / stop events

Setup (one-time, takes ~5 minutes):
  1. Open Telegram and search for @BotFather
  2. Send /newbot → follow prompts → copy your BOT_TOKEN
  3. Start a chat with your new bot, then visit:
         https://api.telegram.org/bot<TOKEN>/getUpdates
     to find your CHAT_ID (the "id" field under "chat")
  4. Add to your .env file:
         TELEGRAM_BOT_TOKEN=123456:ABC-your-token
         TELEGRAM_CHAT_ID=987654321

If the token or chat_id is not set, all notify_*() calls are silent no-ops.
The bot still works normally — you just won't get phone notifications.

Message formatting uses Telegram MarkdownV2 where supported.
"""

from __future__ import annotations

import csv
import io
import threading
from typing import Optional

import requests
from loguru import logger

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


class TelegramNotifier:
    """
    Sends messages to a Telegram chat via the Bot API.

    Thread-safe: all sends happen in a daemon thread so they never
    block the scheduler's signal-check loop.
    """

    _API_URL     = "https://api.telegram.org/bot{token}/sendMessage"
    _API_DOC_URL = "https://api.telegram.org/bot{token}/sendDocument"
    _TIMEOUT = 5  # seconds

    def __init__(
        self,
        token:   str = TELEGRAM_BOT_TOKEN,
        chat_id: str = TELEGRAM_CHAT_ID,
    ) -> None:
        self._token   = token.strip() if token else ""
        self._chat_id = chat_id.strip() if chat_id else ""
        self._enabled = bool(self._token and self._chat_id)

        if self._enabled:
            logger.info("Telegram notifications enabled.")
        else:
            logger.debug(
                "Telegram not configured. Set TELEGRAM_BOT_TOKEN and "
                "TELEGRAM_CHAT_ID in .env to enable phone alerts."
            )

    # ── Typed notification helpers ────────────────────────────────────

    def notify_entry(
        self,
        symbol:   str,
        action:   str,        # "BUY" or "SELL"
        price:    float,
        sl:       float,
        target:   float,
        strategy: str,
        qty:      int,
    ) -> None:
        """Alert: new trade entered."""
        direction = "📈 BUY" if action == "BUY" else "📉 SELL"
        risk      = abs(price - sl)
        reward    = abs(target - price)
        rr        = round(reward / risk, 2) if risk else 0

        self.send(
            f"{direction} *{symbol}*\n"
            f"Entry:    ₹{price:,.2f} × {qty} shares\n"
            f"Stop:     ₹{sl:,.2f}  (−₹{risk * qty:,.0f} max loss)\n"
            f"Target:   ₹{target:,.2f}  (RR {rr}:1)\n"
            f"Strategy: {strategy}"
        )

    def notify_exit(
        self,
        symbol:    str,
        action:    str,
        exit_price: float,
        pnl:       float,
        reason:    str,
    ) -> None:
        """Alert: trade closed."""
        emoji = "✅" if pnl >= 0 else "❌"
        sign  = "+" if pnl >= 0 else ""
        self.send(
            f"{emoji} *{symbol}* closed\n"
            f"Direction: {action}\n"
            f"Exit:      ₹{exit_price:,.2f}\n"
            f"Net P&L:   {sign}₹{pnl:,.0f}\n"
            f"Reason:    {reason}"
        )

    def notify_daily_report(
        self,
        cash:       float,
        net_pnl:    float,
        num_trades: int,
    ) -> None:
        """Alert: end-of-day summary."""
        emoji = "🟢" if net_pnl >= 0 else "🔴"
        sign  = "+" if net_pnl >= 0 else ""
        self.send(
            f"{emoji} *Daily Report*\n"
            f"Trades:    {num_trades}\n"
            f"Net P&L:   {sign}₹{net_pnl:,.0f}\n"
            f"Cash:      ₹{cash:,.0f}"
        )

    def notify_bot_started(self, watchlist_size: int, capital: float) -> None:
        """Alert: scheduler started."""
        self.send(
            f"🚀 *TreadingBot Started*\n"
            f"Mode:      Paper Trading\n"
            f"Capital:   ₹{capital:,.0f}\n"
            f"Watchlist: {watchlist_size} NIFTY50 symbols"
        )

    def notify_bot_stopped(self) -> None:
        """Alert: scheduler stopped."""
        self.send("⏹ *TreadingBot Stopped* — all positions squared off.")

    def notify_risk_halt(self, reason: str) -> None:
        """Alert: risk manager halted trading."""
        self.send(f"⚠️ *Risk Halt*\n{reason}")

    def notify_eod_report(
        self,
        cash:       float,
        net_pnl:    float,
        num_trades: int,
        trades:     list[dict],
        trade_date: str = "",
    ) -> None:
        """
        Send end-of-day summary text + today's trades as a CSV attachment.

        Args:
            cash:        Remaining cash in paper account.
            net_pnl:     Today's net P&L after brokerage.
            num_trades:  Number of completed trades today.
            trades:      List of trade dicts from TradeLogger.get_today_trades().
            trade_date:  Date string for the filename (YYYY-MM-DD).
        """
        emoji = "🟢" if net_pnl >= 0 else "🔴"
        sign  = "+" if net_pnl >= 0 else ""
        summary = (
            f"{emoji} *Daily Report — {trade_date}*\n"
            f"Trades:  {num_trades}\n"
            f"Net P&L: {sign}₹{net_pnl:,.0f}\n"
            f"Cash:    ₹{cash:,.0f}"
        )
        self.send(summary)

        if not trades:
            return  # no trades today — no attachment needed

        # Build CSV in memory
        buf = io.StringIO()
        fieldnames = [
            "Time", "Symbol", "Action", "Qty",
            "Entry ₹", "Exit ₹", "Stop Loss", "Target",
            "Gross P&L ₹", "Brokerage ₹", "Net P&L ₹",
            "Strategy", "Exit Reason", "Result",
        ]
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for t in trades:
            ts = (t.get("timestamp") or "")[:19].replace("T", " ")
            net = t.get("net_pnl")
            result = ("WIN" if net and net > 0 else "LOSS" if net and net < 0 else "OPEN")
            writer.writerow({
                "Time":        ts,
                "Symbol":      t.get("symbol", ""),
                "Action":      t.get("action", ""),
                "Qty":         t.get("quantity", ""),
                "Entry ₹":     t.get("entry_price", ""),
                "Exit ₹":      t.get("exit_price", "") or "",
                "Stop Loss":   t.get("stop_loss", "") or "",
                "Target":      t.get("target", "") or "",
                "Gross P&L ₹": t.get("pnl", "") or "",
                "Brokerage ₹": t.get("brokerage", "") or "",
                "Net P&L ₹":   net or "",
                "Strategy":    t.get("strategy", ""),
                "Exit Reason": t.get("reason", "") or "",
                "Result":      result,
            })

        filename = f"trades_{trade_date or 'today'}.csv"
        caption  = f"Today's trades — {num_trades} trade(s), net P&L {sign}₹{net_pnl:,.0f}"
        self.send_document(
            filename=filename,
            content=buf.getvalue().encode("utf-8"),
            caption=caption,
        )

    # ── Core send ─────────────────────────────────────────────────────

    def send(self, text: str) -> None:
        """
        Send a plain-text message (non-blocking, fire-and-forget).
        Silently skips if not configured.
        """
        if not self._enabled:
            return
        # Run in daemon thread so it never blocks the trading loop
        t = threading.Thread(target=self._send_sync, args=(text,), daemon=True)
        t.start()

    def send_document(self, filename: str, content: bytes, caption: str = "") -> None:
        """
        Send a file attachment (non-blocking, fire-and-forget).
        Silently skips if not configured.
        """
        if not self._enabled:
            return
        t = threading.Thread(
            target=self._send_document_sync,
            args=(filename, content, caption),
            daemon=True,
        )
        t.start()

    def _send_sync(self, text: str) -> None:
        """Actual HTTP POST — runs in background thread."""
        url = self._API_URL.format(token=self._token)
        try:
            resp = requests.post(
                url,
                json={"chat_id": self._chat_id, "text": text},
                timeout=self._TIMEOUT,
            )
            if not resp.ok:
                logger.warning(
                    f"Telegram send failed: {resp.status_code} {resp.text[:120]}"
                )
        except requests.RequestException as exc:
            logger.warning(f"Telegram unreachable: {exc}")

    def _send_document_sync(self, filename: str, content: bytes, caption: str) -> None:
        """Actual multipart POST for file upload — runs in background thread."""
        url = self._API_DOC_URL.format(token=self._token)
        try:
            resp = requests.post(
                url,
                data={"chat_id": self._chat_id, "caption": caption},
                files={"document": (filename, content, "text/csv")},
                timeout=15,  # file upload needs more time
            )
            if not resp.ok:
                logger.warning(
                    f"Telegram document send failed: {resp.status_code} {resp.text[:120]}"
                )
        except requests.RequestException as exc:
            logger.warning(f"Telegram document upload failed: {exc}")


# ── Module-level singleton ────────────────────────────────────────────

_notifier: Optional[TelegramNotifier] = None


def get_notifier() -> TelegramNotifier:
    """Return the process-wide singleton TelegramNotifier."""
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier()
    return _notifier
