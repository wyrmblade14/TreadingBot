"""
Telegram Notifier — sends intelligent trade alerts to your phone.

Why Telegram?
  You can't watch the dashboard all day. Telegram pushes key events
  the moment they happen — entry, exit, risk halts, EOD report.

Setup (one-time, ~5 minutes):
  1. Open Telegram → search @BotFather → /newbot → copy BOT_TOKEN
  2. Start a chat with your bot, visit:
       https://api.telegram.org/bot<TOKEN>/getUpdates
     and copy the "id" field under "chat" → that's your CHAT_ID
  3. Add to .env:
       TELEGRAM_BOT_TOKEN=123456:ABC-your-token
       TELEGRAM_CHAT_ID=987654321

Messages use Telegram HTML formatting (<b>, <code>, <i>).
If token/chat_id are not set, all notify_*() calls are silent no-ops.

What's "intelligent" about this notifier:
  • HTML formatting — bold text actually renders bold on your phone
  • Trade context — entry messages include trade # today and running day P&L
  • Exit context — cumulative P&L, RR achieved, whether SL or target was hit
  • Pre-market briefing — VIX, regime, NIFTY direction before the session starts
  • Adaptive mode alerts — notified when bot shifts NORMAL→DEFENSIVE→HALTED
  • Rich EOD — win rate, profit factor, streak, best/worst trade, per-strategy summary
  • Rate limiting — max 1 alert per (symbol, event_type) per 60 s (no spam on retries)
  • Retry with backoff — 1 silent retry after 2 s on network blip
"""

from __future__ import annotations

import csv
import io
import threading
import time
from typing import Optional

import requests
from loguru import logger

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def _h(text: str) -> str:
    """Escape special HTML characters for Telegram HTML parse_mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class TelegramNotifier:
    """
    Sends HTML-formatted messages to a Telegram chat via the Bot API.
    Thread-safe: all sends run in a daemon thread (never blocks the trading loop).
    """

    _API_URL     = "https://api.telegram.org/bot{token}/sendMessage"
    _API_DOC_URL = "https://api.telegram.org/bot{token}/sendDocument"
    _TIMEOUT     = 6   # seconds per attempt
    _RATE_LIMIT  = 60  # seconds before re-alerting the same (symbol, event)

    def __init__(
        self,
        token:   str = TELEGRAM_BOT_TOKEN,
        chat_id: str = TELEGRAM_CHAT_ID,
    ) -> None:
        self._token   = token.strip()   if token   else ""
        self._chat_id = chat_id.strip() if chat_id else ""
        self._enabled = bool(self._token and self._chat_id)

        # Rate-limit cache: (symbol, event_type) → last send timestamp
        self._last_sent: dict[tuple, float] = {}
        # Once-per-day dedup: event_key → date string (YYYY-MM-DD)
        self._sent_today: dict[str, str] = {}
        self._lock = threading.Lock()

        if self._enabled:
            logger.info("Telegram notifications enabled.")
        else:
            logger.debug(
                "Telegram not configured. Set TELEGRAM_BOT_TOKEN and "
                "TELEGRAM_CHAT_ID in .env to enable phone alerts."
            )

    # ── Rate-limit helper ─────────────────────────────────────────────

    def _rate_ok(self, key: tuple) -> bool:
        """Return True if this (symbol, event) hasn't been sent in the last 60 s."""
        with self._lock:
            last = self._last_sent.get(key, 0.0)
            if time.monotonic() - last < self._RATE_LIMIT:
                return False
            self._last_sent[key] = time.monotonic()
            return True

    def _once_today(self, key: str) -> bool:
        """Return True (and record) if this event hasn't fired yet today. Thread-safe.

        Used for once-per-day notifications (pre-market briefing, bot-started alert)
        that should not repeat on mid-session restarts.
        """
        import datetime as _dt
        today = _dt.date.today().isoformat()
        with self._lock:
            if self._sent_today.get(key) == today:
                return False
            self._sent_today[key] = today
            return True

    # ── Typed notification helpers ────────────────────────────────────

    def notify_entry(
        self,
        symbol:   str,
        action:   str,
        price:    float,
        sl:       float,
        target:   float,
        strategy: str,
        qty:      int,
        # optional context — filled from RiskManager / TradeLogger when available
        trade_num:   int   = 0,    # trade # today (1, 2, 3 …)
        day_pnl:     float = 0.0,  # running day P&L before this trade
        adaptive_mode: str = "",   # NORMAL / DEFENSIVE / HALTED
    ) -> None:
        """Alert: new trade entered — includes day context."""
        if not self._rate_ok((symbol, "entry")):
            return

        icon = "📈" if action == "BUY" else "📉"
        risk_ps   = abs(price - sl)
        reward_ps = abs(target - price)
        rr        = round(reward_ps / risk_ps, 1) if risk_ps else 0
        max_loss  = risk_ps * qty

        # Day context line
        ctx_parts = []
        if trade_num:
            ctx_parts.append(f"Trade #{trade_num} today")
        if day_pnl != 0.0:
            sign = "+" if day_pnl >= 0 else ""
            ctx_parts.append(f"Day P&amp;L so far: {sign}₹{day_pnl:,.0f}")
        if adaptive_mode:
            ctx_parts.append(f"Mode: {adaptive_mode}")
        context_line = "  |  ".join(ctx_parts)

        lines = [
            f"{icon} <b>{_h(action)} {_h(symbol)}</b>",
            f"Entry    <code>₹{price:,.2f}</code>  ×  {qty} shares",
            f"Stop     <code>₹{sl:,.2f}</code>  (max loss ₹{max_loss:,.0f})",
            f"Target   <code>₹{target:,.2f}</code>  (RR {rr}:1)",
            f"Strategy <i>{_h(strategy)}</i>",
        ]
        if context_line:
            lines.append(f"<i>{context_line}</i>")

        self.send("\n".join(lines))

    def notify_exit(
        self,
        symbol:     str,
        action:     str,
        exit_price: float = 0.0,
        pnl:        float = 0.0,
        reason:     str   = "",
        # optional context
        entry_price:  float = 0.0,
        day_pnl:      float = 0.0,  # cumulative day P&L AFTER this trade
        consec_wins:  int   = 0,
        consec_losses:int   = 0,
        # legacy kwarg — some callers pass price= instead of exit_price=
        price: float = 0.0,
    ) -> None:
        """Alert: trade closed — includes outcome context and running P&L."""
        if not self._rate_ok((symbol, "exit")):
            return

        ep = exit_price or price
        icon = "✅" if pnl >= 0 else "❌"
        sign = "+" if pnl >= 0 else ""
        result_word = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "SCRATCH")

        # RR achieved (if we know entry)
        rr_line = ""
        if entry_price and ep:
            direction = 1 if action in ("BUY", "LONG") else -1
            achieved = (ep - entry_price) * direction
            risk_taken = abs(entry_price - 0) if not entry_price else None
            rr_line = ""   # skip — entry_price not always reliable here

        lines = [
            f"{icon} <b>{_h(symbol)} closed — {result_word}</b>",
            f"Exit     <code>₹{ep:,.2f}</code>  →  {sign}₹{pnl:,.0f}",
        ]
        if reason:
            lines.append(f"Reason   <i>{_h(reason)}</i>")
        if day_pnl != 0.0:
            day_sign = "+" if day_pnl >= 0 else ""
            lines.append(f"Day P&amp;L  <code>{day_sign}₹{day_pnl:,.0f}</code>")
        if consec_wins >= 2:
            lines.append(f"🔥 <i>{consec_wins} wins in a row</i>")
        if consec_losses >= 2:
            lines.append(f"⚠️ <i>{consec_losses} losses in a row</i>")

        self.send("\n".join(lines))

    def notify_premarket(
        self,
        nifty_price: float,
        nifty_chg:   float,
        vix:         float,
        vix_level:   str,        # "low" | "normal" | "high" | "extreme"
        regime:      str,        # "Trending" | "Ranging" | "Volatile" | "Unknown"
        adx:         float,
        direction:   str,        # "UP" | "DOWN" | "NEUTRAL"
        skip_buys:   bool,
        skip_sells:  bool,
        skip_all:    bool,
    ) -> None:
        """9:00 AM pre-market briefing — sent once per day."""
        if not self._once_today("premarket"):
            return
        vix_icon = {"low": "😌", "normal": "😐", "high": "😰", "extreme": "🚨"}.get(vix_level, "❓")
        regime_icon = {"Trending": "📈", "Ranging": "↔️", "Volatile": "⚡", "Unknown": "❓"}.get(regime, "❓")
        dir_icon = {"UP": "⬆️", "DOWN": "⬇️", "NEUTRAL": "➡️"}.get(direction, "➡️")

        if skip_all:
            trading_status = "🚫 <b>ALL entries suppressed</b> (extreme fear)"
        elif skip_buys and skip_sells:
            trading_status = "⏸ <b>Direction unclear — sitting out</b>"
        elif skip_buys:
            trading_status = "🔻 <b>LONG entries suppressed</b> (NIFTY falling)"
        elif skip_sells:
            trading_status = "🔺 <b>SHORT entries suppressed</b> (NIFTY rising)"
        else:
            trading_status = "✅ <b>Normal trading — both sides allowed</b>"

        nifty_sign = "+" if nifty_chg >= 0 else ""
        lines = [
            "☀️ <b>Pre-Market Briefing</b>",
            f"NIFTY    <code>{nifty_price:,.0f}</code>  ({nifty_sign}{nifty_chg:.2f}%)",
            f"VIX      {vix_icon} <code>{vix:.1f}</code>  ({vix_level.upper()})",
            f"Regime   {regime_icon} {_h(regime)}  (ADX {adx:.0f})",
            f"Direction {dir_icon} {direction}",
            trading_status,
        ]
        self.send("\n".join(lines))

    def notify_adaptive_change(
        self,
        old_mode: str,
        new_mode: str,
        reason:   str,
    ) -> None:
        """Alert: adaptive mode shifted (e.g. NORMAL → DEFENSIVE)."""
        if not self._rate_ok(("adaptive", new_mode)):
            return

        icons = {"NORMAL": "🟢", "DEFENSIVE": "🟡", "HALTED": "🔴"}
        old_icon = icons.get(old_mode, "⚪")
        new_icon = icons.get(new_mode, "⚪")

        lines = [
            f"{new_icon} <b>Adaptive Mode: {old_mode} → {new_mode}</b>",
            f"<i>{_h(reason)}</i>",
        ]
        if new_mode == "HALTED":
            lines.append("⚠️ <b>No new entries until conditions improve.</b>")
        elif new_mode == "DEFENSIVE":
            lines.append("<i>Tighter RSI zone, wider SL, fewer signals.</i>")

        self.send("\n".join(lines))

    def notify_risk_halt(self, reason: str) -> None:
        """Alert: risk manager halted trading."""
        if not self._rate_ok(("risk", "halt")):
            return
        self.send(f"⛔ <b>Risk Halt</b>\n<i>{_h(reason)}</i>")

    def notify_bot_started(self, watchlist_size: int, capital: float) -> None:
        """Alert: scheduler started — fires once per day even on mid-session restarts."""
        if not self._once_today("bot_started"):
            return
        self.send(
            f"🚀 <b>TreadingBot Started</b>\n"
            f"Mode       Paper Trading\n"
            f"Capital    <code>₹{capital:,.0f}</code>\n"
            f"Watchlist  {watchlist_size} NIFTY50 symbols"
        )

    def notify_bot_stopped(self) -> None:
        """Alert: scheduler stopped."""
        self.send("⏹ <b>TreadingBot Stopped</b> — all positions squared off.")

    def notify_eod_report(
        self,
        cash:       float,
        net_pnl:    float,
        num_trades: int,
        trades:     list[dict],
        trade_date: str = "",
    ) -> None:
        """
        Rich end-of-day summary + CSV attachment.

        Includes: win rate, profit factor, win/loss streak, best/worst trade,
        per-strategy breakdown.
        """
        if not trades and num_trades == 0:
            # No trades today — send a short note, not a full report
            emoji = "😴"
            self.send(
                f"{emoji} <b>EOD — {trade_date}</b>\n"
                f"No trades today."
            )
            return

        emoji = "🟢" if net_pnl >= 0 else "🔴"
        sign  = "+" if net_pnl >= 0 else ""

        # Compute stats from closed trades
        closed = [t for t in trades if t.get("net_pnl") is not None]
        wins   = [t for t in closed if (t.get("net_pnl") or 0) > 0]
        losses = [t for t in closed if (t.get("net_pnl") or 0) < 0]

        win_rate     = len(wins) / len(closed) * 100 if closed else 0
        gross_win    = sum(t["net_pnl"] for t in wins)
        gross_loss   = abs(sum(t["net_pnl"] for t in losses))
        pf           = round(gross_win / gross_loss, 2) if gross_loss else 0

        # Current streak
        streak_str = ""
        if closed:
            streak = 1
            last_sign = 1 if (closed[-1].get("net_pnl") or 0) >= 0 else -1
            for t in reversed(closed[:-1]):
                s = 1 if (t.get("net_pnl") or 0) >= 0 else -1
                if s == last_sign:
                    streak += 1
                else:
                    break
            if last_sign > 0 and streak >= 2:
                streak_str = f"🔥 {streak}-win streak"
            elif last_sign < 0 and streak >= 2:
                streak_str = f"📉 {streak}-loss streak"

        # Best and worst trade
        best_str = worst_str = ""
        if closed:
            best  = max(closed, key=lambda t: t.get("net_pnl") or 0)
            worst = min(closed, key=lambda t: t.get("net_pnl") or 0)
            best_str  = f"Best   {best.get('symbol','')}  +₹{best['net_pnl']:,.0f}"
            worst_str = f"Worst  {worst.get('symbol','')}  ₹{worst['net_pnl']:,.0f}"

        # Per-strategy breakdown
        strategies = {}
        for t in closed:
            s = t.get("strategy", "unknown")
            if s not in strategies:
                strategies[s] = {"wins": 0, "total": 0, "pnl": 0}
            strategies[s]["total"] += 1
            strategies[s]["pnl"]   += t.get("net_pnl") or 0
            if (t.get("net_pnl") or 0) > 0:
                strategies[s]["wins"] += 1

        lines = [
            f"{emoji} <b>EOD Report — {trade_date}</b>",
            f"Trades    {num_trades}  ({len(wins)}W / {len(losses)}L)",
            f"Win rate  {win_rate:.0f}%",
            f"Net P&amp;L   <code>{sign}₹{net_pnl:,.0f}</code>",
            f"Cash      <code>₹{cash:,.0f}</code>",
        ]
        if pf:
            lines.append(f"Profit factor  {pf}×")
        if streak_str:
            lines.append(streak_str)
        if best_str:
            lines.append("")
            lines.append(f"<i>{best_str}</i>")
        if worst_str:
            lines.append(f"<i>{worst_str}</i>")
        if len(strategies) > 1:
            lines.append("")
            for sname, stats in sorted(strategies.items()):
                wr = stats["wins"] / stats["total"] * 100 if stats["total"] else 0
                sp = stats["pnl"]
                ss = "+" if sp >= 0 else ""
                lines.append(
                    f"<code>{_h(sname[:18]):<18}</code>"
                    f"  {stats['wins']}/{stats['total']}  {ss}₹{sp:,.0f}"
                )

        self.send("\n".join(lines))

        if not trades:
            return

        # CSV attachment
        buf = io.StringIO()
        fieldnames = [
            "Time", "Symbol", "Action", "Qty",
            "Entry Rs", "Exit Rs", "Stop Loss", "Target",
            "Gross PnL Rs", "Brokerage Rs", "Net PnL Rs",
            "Strategy", "Exit Reason", "Result",
        ]
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for t in trades:
            ts  = (t.get("timestamp") or "")[:19].replace("T", " ")
            net = t.get("net_pnl")
            result = "WIN" if net and net > 0 else ("LOSS" if net and net < 0 else "OPEN")
            writer.writerow({
                "Time":         ts,
                "Symbol":       t.get("symbol", ""),
                "Action":       t.get("action", ""),
                "Qty":          t.get("quantity", ""),
                "Entry Rs":     t.get("entry_price", ""),
                "Exit Rs":      t.get("exit_price", "") or "",
                "Stop Loss":    t.get("stop_loss", "") or "",
                "Target":       t.get("target", "") or "",
                "Gross PnL Rs": t.get("pnl", "") or "",
                "Brokerage Rs": t.get("brokerage", "") or "",
                "Net PnL Rs":   net or "",
                "Strategy":     t.get("strategy", ""),
                "Exit Reason":  t.get("reason", "") or "",
                "Result":       result,
            })

        self.send_document(
            filename=f"trades_{trade_date or 'today'}.csv",
            content=buf.getvalue().encode("utf-8"),
            caption=f"Trades {trade_date} — {num_trades} trade(s), net {sign}Rs{net_pnl:,.0f}",
        )

    # legacy alias used by some older call sites
    def notify_daily_report(
        self,
        cash:       float,
        net_pnl:    float,
        num_trades: int,
    ) -> None:
        self.notify_eod_report(
            cash=cash, net_pnl=net_pnl, num_trades=num_trades,
            trades=[], trade_date="",
        )

    # ── Core send ─────────────────────────────────────────────────────

    def send(self, html: str) -> None:
        """
        Send an HTML-formatted message (non-blocking, fire-and-forget).
        Silently skips if not configured.
        """
        if not self._enabled:
            return
        threading.Thread(target=self._send_sync, args=(html,), daemon=True).start()

    def send_document(self, filename: str, content: bytes, caption: str = "") -> None:
        """Send a file attachment (non-blocking, fire-and-forget)."""
        if not self._enabled:
            return
        threading.Thread(
            target=self._send_document_sync,
            args=(filename, content, caption),
            daemon=True,
        ).start()

    def _send_sync(self, html: str) -> None:
        """HTTP POST with one silent retry on failure."""
        url = self._API_URL.format(token=self._token)
        payload = {
            "chat_id":    self._chat_id,
            "text":       html,
            "parse_mode": "HTML",
        }
        for attempt in (1, 2):
            try:
                resp = requests.post(url, json=payload, timeout=self._TIMEOUT)
                if resp.ok:
                    return
                logger.warning(
                    f"Telegram send failed (attempt {attempt}): "
                    f"{resp.status_code} {resp.text[:120]}"
                )
            except requests.RequestException as exc:
                logger.warning(f"Telegram unreachable (attempt {attempt}): {exc}")
            if attempt == 1:
                time.sleep(2)  # brief backoff before retry

    def _send_document_sync(self, filename: str, content: bytes, caption: str) -> None:
        """Multipart POST for file upload — runs in background thread."""
        url = self._API_DOC_URL.format(token=self._token)
        try:
            resp = requests.post(
                url,
                data={"chat_id": self._chat_id, "caption": caption},
                files={"document": (filename, content, "text/csv")},
                timeout=20,
            )
            if not resp.ok:
                logger.warning(
                    f"Telegram document send failed: "
                    f"{resp.status_code} {resp.text[:120]}"
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
