"""
Bot Monitor — observe the running bot and browse past run logs.

Start/stop controls are removed. The bot is intended to be scheduled
via cron (or run manually from the terminal). This page only monitors.

What this page does:
  - Shows RUNNING / STOPPED status (reads shared state file)
  - Live log viewer — reads the active log file and refreshes on demand
  - Run History — browse every past run's log, colour-coded by level

To start the bot:
    python scripts/run_bot.py
    # or schedule via cron at 09:00 IST on weekdays
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from monitoring.degradation import check_all_strategies
from scheduler.bot_controller import get_controller

_RUNS_DIR = Path(__file__).parent.parent.parent / "logs" / "runs"


def _render_log_content(log_file: Path, tail: int = 0) -> None:
    """
    Render a log file as colour-coded HTML inside a scrollable box.

    Args:
        log_file: Path to the log file.
        tail:     If > 0, show only the last N lines (newest at top).
                  If 0, show all lines in order (for Run History).
    """
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        st.error(f"Could not read log: {e}")
        return

    total = len(lines)
    if tail > 0:
        lines = lines[-tail:]   # last N lines
        lines = list(reversed(lines))  # newest at top — true tail -f feel

    coloured = []
    for line in lines:
        if   "| ERROR   |" in line: c = "#EF5350"
        elif "| WARNING |" in line: c = "#FFB74D"
        elif "| DEBUG   |" in line: c = "#888888"
        else:                        c = "#90CAF9"
        safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        coloured.append(
            f'<span style="color:{c};font-family:monospace;font-size:12px">{safe}</span>'
        )

    st.markdown(
        '<div style="background:#0e1117;border:1px solid #333;border-radius:6px;'
        'padding:12px 16px;max-height:500px;overflow-y:auto;">'
        + "<br>".join(coloured)
        + "</div>",
        unsafe_allow_html=True,
    )
    shown = min(tail, total) if tail > 0 else total
    st.caption(
        f"Showing last {shown} of {total} lines · {log_file.name}"
        if tail > 0 else
        f"{total} lines · {log_file}"
    )


@st.fragment(run_every=5)
def _live_log_fragment() -> None:
    """Auto-refreshes every 5 seconds — only this section reruns, not the whole page."""
    try:
        ctrl   = get_controller()
        status = ctrl.get_status()
    except Exception as exc:
        st.error(f"Could not read bot state: {exc}")
        st.info("Try restarting the dashboard: `streamlit run dashboard/app.py`")
        return
    is_running = status["status"] == "running"

    # ── Status banner ─────────────────────────────────────────────────
    if is_running:
        pid = status.get("pid")
        st.success(
            f"**BOT RUNNING**  "
            f"| PID: {pid}  "
            f"| Since: {status['started_at']}  "
            f"| Watchlist: {status['watchlist_size']} symbols  "
            f"| Capital: ₹{status['capital']:,.0f}"
        )
    else:
        st.warning(
            "**BOT STOPPED**  |  "
            "Run `python scripts/run_bot.py` in the terminal to start."
        )

    st.markdown("---")

    # ── Adaptive Mode Panel ───────────────────────────────────────────
    try:
        from config.adaptive import get_state, AdaptiveMode
        adp = get_state()
        mode = adp.get("mode", AdaptiveMode.NORMAL)

        if mode == AdaptiveMode.HALTED:
            mode_colour = "#EF5350"
            mode_label  = "HALTED"
        elif mode == AdaptiveMode.DEFENSIVE:
            mode_colour = "#FFB74D"
            mode_label  = "DEFENSIVE"
        else:
            mode_colour = "#4CAF50"
            mode_label  = "NORMAL"

        st.markdown(
            f'<div style="background:#1e1e2e;border:1px solid {mode_colour};'
            f'border-radius:8px;padding:12px 16px;margin-bottom:8px">'
            f'<span style="color:{mode_colour};font-size:16px;font-weight:600">'
            f'Adaptive Mode: {mode_label}</span><br>'
            f'<span style="color:#aaa;font-size:12px">{adp.get("reason","—")}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )

        vix_val   = adp.get("vix")
        regime    = adp.get("regime", "Unknown")
        direction = adp.get("direction", "NEUTRAL")
        losses    = adp.get("consecutive_losses", 0)
        pnl_pct   = adp.get("day_pnl_pct", 0.0)

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("India VIX",      f"{vix_val:.1f}" if vix_val else "—")
        c2.metric("Regime",         regime)
        c3.metric("NIFTY Direction", direction)
        c4.metric("Consec. Losses", str(losses))
        c5.metric("Day P&L",        f"{pnl_pct:+.1%}" if pnl_pct else "0.0%",
                  delta_color="inverse")
    except Exception:
        pass  # non-fatal — don't break the page if adaptive module not loaded yet

    st.markdown("---")

    # ── Live log (auto-refreshing tail -f style) ──────────────────────
    active_log_path = status.get("log_path") if is_running else None

    hdr_col, refresh_col = st.columns([5, 1])
    with hdr_col:
        st.subheader(
            ":material/description: Live Log"
            if is_running
            else ":material/description: Log"
        )
    with refresh_col:
        st.write("")
        if st.button("Refresh", icon=":material/refresh:", use_container_width=True):
            st.rerun()

    if is_running:
        # Prefer the path from state; fall back to newest file in runs dir
        log_file = None
        if active_log_path and Path(active_log_path).exists():
            log_file = Path(active_log_path)
        elif _RUNS_DIR.exists():
            candidates = sorted(_RUNS_DIR.glob("*.log"), reverse=True)
            log_file = candidates[0] if candidates else None

        if log_file:
            _render_log_content(log_file, tail=150)
        else:
            st.info("Log file not found yet — refresh in a moment.")
    else:
        st.info("Bot is not running. Live log will appear here once it starts.")


def _render_strategy_health() -> None:
    """
    Strategy Degradation Health Panel.

    Compares each strategy's rolling live win rate against its backtest
    baseline. Flags strategies that have dropped more than 15pp — this
    often means the market regime has changed and the strategy needs review.
    """
    st.subheader("Strategy Health")
    st.caption(
        "Rolling win rate of last 20 paper trades vs backtest baseline. "
        "Alert fires when live win rate drops >15pp below baseline."
    )

    try:
        healths = check_all_strategies()
    except Exception as exc:
        st.warning(f"Could not load strategy health: {exc}")
        return

    any_degraded = any(h.is_degraded for h in healths)
    if any_degraded:
        st.error(
            "One or more strategies are degraded. "
            "Consider pausing them and reviewing recent market conditions.",
            icon=":material/warning:",
        )

    cols = st.columns(len(healths))
    for col, h in zip(cols, healths):
        if h.is_degraded:
            status = "Critical"
        elif not h.has_enough_trades:
            status = "Insufficient Data"
        elif h.drop_pct and h.drop_pct > 0:
            status = "Watch"
        else:
            status = "Healthy"

        with col:
            live_str = (
                f"{h.rolling_win_rate:.1f}%"
                if h.rolling_win_rate is not None
                else "—"
            )
            delta_str = (
                f"{-h.drop_pct:+.1f}pp vs baseline"
                if h.drop_pct is not None
                else f"{h.trade_count}/{h.min_trades} trades"
            )
            st.metric(
                label=f"{h.strategy.replace('_', ' ').title()} ({status})",
                value=live_str,
                delta=delta_str,
                delta_color="inverse" if h.is_degraded else "normal",
            )
            st.caption(
                f"Baseline: {h.baseline_win_rate:.0f}% | "
                f"Trades: {h.trade_count}"
            )


def render() -> None:
    st.title("Bot Monitor")
    st.caption("Read-only view — auto-refreshes every 5 s while bot is running.")

    _render_strategy_health()

    st.markdown("---")
    _live_log_fragment()

    # ── Run History (static — reload page to refresh) ─────────────────
    st.markdown("---")
    st.subheader(":material/folder_open: Run History")
    st.caption("One log file is created per bot run. Click any run to read its full log.")

    log_files = sorted(_RUNS_DIR.glob("*.log"), reverse=True) if _RUNS_DIR.exists() else []

    if not log_files:
        st.info("No past runs yet.")
        return

    # Read active log path here (separate from the fragment's read) for ACTIVE tag
    status_now      = get_controller().get_status()
    active_log_path = status_now.get("log_path") if status_now["status"] == "running" else None

    for log_file in log_files:
        size_kb   = log_file.stat().st_size / 1024
        label     = log_file.stem.replace("_", "  ", 1)   # 2026-03-27  09-00-00
        is_active = active_log_path and Path(active_log_path) == log_file
        tag       = "  ACTIVE" if is_active else ""

        with st.expander(f"Log File {label}   ({size_kb:.1f} KB){tag}"):
            _render_log_content(log_file)

    # ── Commented-out start/stop controls (kept for future re-enabling) ──
    # Uncomment this block if you want UI-based start/stop back.
    #
    # from config.settings import VIRTUAL_CAPITAL
    # from data.instruments import NIFTY50_INSTRUMENTS
    # col_start, col_stop = st.columns(2)
    # with col_start:
    #     st.subheader("Start Bot")
    #     max_symbols = len(NIFTY50_INSTRUMENTS)
    #     watchlist_size = st.slider("Watchlist size", 1, max_symbols,
    #                                value=status.get("watchlist_size", 10),
    #                                disabled=is_running)
    #     capital = st.number_input("Starting capital (₹)",
    #                               value=int(status.get("capital", VIRTUAL_CAPITAL)),
    #                               step=10_000, min_value=10_000, disabled=is_running)
    #     if st.button("Start Bot", type="primary", disabled=is_running,
    #                  use_container_width=True):
    #         with st.spinner("Starting scheduler…"):
    #             ok, msg = ctrl.start(watchlist_size=watchlist_size, capital=float(capital))
    #         if ok:
    #             st.success(msg)
    #             st.rerun()
    #         else:
    #             st.warning(msg)
    #
    # with col_stop:
    #     st.subheader("Stop Bot")
    #     st.markdown("Stopping squares off all open positions and shuts the scheduler.")
    #     st.write("")
    #     if st.button("Stop Bot", type="secondary", disabled=not is_running,
    #                  use_container_width=True):
    #         with st.spinner("Stopping…"):
    #             ok, msg = ctrl.stop()
    #         if ok:
    #             st.success(msg)
    #             st.rerun()
    #         else:
    #             st.warning(msg)
