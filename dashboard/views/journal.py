"""
Trade Journal — every paper trade as a readable logbook entry.

Why this page exists:
  Numbers alone don't build conviction. Reading each trade as a story —
  what the bot saw, what risk it took, how it played out — is the fastest
  way to understand whether you can trust the bot before going live.

What you can do here:
  - Filter by strategy, date range, or outcome (win / loss / open)
  - See each trade's full setup: entry, SL, target, R:R, hold time
  - Understand *why* the signal fired (the reason field from the strategy)
  - Spot patterns: which strategies win in the morning vs afternoon?
  - Review the time-of-day and strategy breakdown charts at the bottom
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from execution.trade_log import TradeLogger

# Module-level singleton — avoids repeated DB init on every Streamlit rerun
_trade_log = TradeLogger()

# ── Helpers ───────────────────────────────────────────────────────────

_STRATEGY_LABELS = {
    "ema_crossover":          "EMA Crossover",
    "rsi_macd_combo":         "RSI+MACD",
    "opening_range_breakout": "ORB",
    "gap_and_go":             "Gap & Go",
}

_STRATEGY_COLOURS = {
    "ema_crossover":          "#4f6ef7",
    "rsi_macd_combo":         "#f7a84f",
    "opening_range_breakout": "#4fc9f7",
    "gap_and_go":             "#a78bfa",
}


def _friendly_strategy(raw: str) -> str:
    return _STRATEGY_LABELS.get(raw, raw)


def _exit_type(trade: dict) -> str:
    """Classify how a trade exited based on exit price vs SL / target."""
    ep   = trade.get("exit_price")
    sl   = trade.get("stop_loss")
    tgt  = trade.get("target")
    side = trade.get("action", "BUY")

    if ep is None:
        return "Open"
    if sl is None or tgt is None:
        return "Closed"

    if side == "BUY":
        if ep >= tgt * 0.995:   # within 0.5% of target = hit target
            return "Target ✅"
        if ep <= sl * 1.005:    # within 0.5% above SL = stopped out
            return "Stop-Loss ❌"
        return "Manual Exit"
    else:  # SELL / short
        if ep <= tgt * 1.005:
            return "Target ✅"
        if ep >= sl * 0.995:
            return "Stop-Loss ❌"
        return "Manual Exit"


def _hold_duration(trade: dict) -> str:
    """Return human-readable hold time, e.g. '1h 23m'."""
    ts_in  = trade.get("timestamp")
    ts_out = trade.get("exit_timestamp")
    if not ts_in or not ts_out:
        return "—"
    try:
        t_in  = datetime.fromisoformat(ts_in)
        t_out = datetime.fromisoformat(ts_out)
        delta = t_out - t_in
        mins  = int(delta.total_seconds() // 60)
        if mins < 60:
            return f"{mins}m"
        return f"{mins // 60}h {mins % 60}m"
    except Exception:
        return "—"


def _rr_achieved(trade: dict) -> str:
    """Return the reward:risk ratio actually captured at exit."""
    ep  = trade.get("exit_price")
    sl  = trade.get("stop_loss")
    ent = trade.get("entry_price")
    if not all([ep, sl, ent]):
        return "—"
    risk = abs(ent - sl)
    if risk == 0:
        return "—"
    reward = (ep - ent) if trade.get("action") == "BUY" else (ent - ep)
    rr = reward / risk
    return f"{rr:+.2f}R"


def _pnl_colour(val: float | None) -> str:
    if val is None:
        return "#9ca3af"
    return "#4caf50" if val >= 0 else "#ef5350"


def _entry_hour(trade: dict) -> int | None:
    ts = trade.get("timestamp")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts).hour
    except Exception:
        return None


# ── Calendar heatmap helper ───────────────────────────────────────────

def _render_calendar_heatmap(daily_rows: list[dict]) -> None:
    """
    GitHub-style calendar heatmap of daily P&L.

    Each square is one trading day. Green = profit, red = loss, grey = no trade.
    X-axis = week columns, Y-axis = day of week (Mon–Fri).

    The chart automatically spans from the first trade date to today,
    so you get a clear sense of how long you've been paper trading and
    how the results are distributed across time.
    """
    # Build a {date_str: pnl} map from the DB rows
    pnl_by_date: dict[date, float] = {}
    for row in daily_rows:
        try:
            d   = date.fromisoformat(row["date"])
            pnl = float(row["net_pnl"] or 0.0)
            pnl_by_date[d] = pnl
        except (ValueError, KeyError, TypeError):
            continue

    if not pnl_by_date:
        return

    # Date range: first trade date → today, clamped to 90 days max for readability
    today      = date.today()
    first_date = min(pnl_by_date.keys())
    span_days  = (today - first_date).days
    if span_days > 90:
        first_date = today - timedelta(days=90)

    # Align to the Monday of the first_date's week so the calendar grid is tidy
    first_date = first_date - timedelta(days=first_date.weekday())

    # Build a calendar grid: weeks (columns) × weekdays Mon–Fri (rows 0–4)
    # We skip Sat (5) and Sun (6) since NSE doesn't trade then.
    total_days = (today - first_date).days + 1
    num_weeks  = (total_days + 6) // 7 + 1   # number of week columns needed

    # z[weekday][week] = P&L value (None = no-trade / weekend)
    z         = [[None] * num_weeks for _ in range(5)]
    hover     = [["" ]  * num_weeks for _ in range(5)]
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri"]

    for week_idx in range(num_weeks):
        for wd in range(5):   # Monday=0 … Friday=4
            d = first_date + timedelta(weeks=week_idx, days=wd)
            if d > today:
                continue
            if d in pnl_by_date:
                pnl       = pnl_by_date[d]
                z[wd][week_idx]     = pnl
                hover[wd][week_idx] = (
                    f"{d.strftime('%a %d %b %Y')}<br>"
                    f"P&L: ₹{pnl:+,.2f}"
                )
            else:
                # Trading day with no trades — show as neutral grey
                z[wd][week_idx]     = 0.0
                hover[wd][week_idx] = f"{d.strftime('%a %d %b %Y')}<br>No trades"

    # Build week-start labels for x-axis tick marks (show month when it changes)
    x_labels = []
    prev_month = None
    for week_idx in range(num_weeks):
        d = first_date + timedelta(weeks=week_idx)
        if d.month != prev_month:
            x_labels.append(d.strftime("%b"))
            prev_month = d.month
        else:
            x_labels.append("")

    # Symmetric colour scale: diverging red → white → green centred on 0
    # We need the absolute max P&L to know where to anchor the scale.
    flat_vals = [v for row in z for v in row if v is not None and v != 0.0]
    abs_max   = max(abs(v) for v in flat_vals) if flat_vals else 1.0

    colorscale = [
        [0.0,  "#c62828"],   # deep red   (max loss)
        [0.35, "#ef9a9a"],   # light red
        [0.5,  "#2a2d3e"],   # neutral dark (zero / no-trade)
        [0.65, "#a5d6a7"],   # light green
        [1.0,  "#1b5e20"],   # deep green (max profit)
    ]

    fig = go.Figure(go.Heatmap(
        z=z,
        x=x_labels,
        y=day_names,
        zmin=-abs_max,
        zmax=abs_max,
        colorscale=colorscale,
        showscale=True,
        hoverongaps=False,
        hovertemplate="%{customdata}<extra></extra>",
        customdata=hover,
        xgap=3,   # gap between week columns
        ygap=3,   # gap between day rows
        colorbar=dict(
            title="P&L (₹)",
            titleside="right",
            thickness=12,
            len=0.8,
            tickprefix="₹",
            tickfont=dict(color="#9ca3af", size=10),
            titlefont=dict(color="#9ca3af", size=11),
        ),
    ))

    fig.update_layout(
        height=200,
        paper_bgcolor="#0f1117",
        plot_bgcolor="#0f1117",
        font=dict(color="#9ca3af", size=11),
        margin=dict(l=40, r=60, t=10, b=30),
        xaxis=dict(
            side="top",
            showgrid=False,
            zeroline=False,
            tickfont=dict(color="#6b7280", size=10),
        ),
        yaxis=dict(
            autorange="reversed",   # Mon at top, Fri at bottom
            showgrid=False,
            zeroline=False,
            tickfont=dict(color="#6b7280", size=10),
        ),
    )

    st.plotly_chart(fig, use_container_width=True)

    # Quick summary below the chart
    profitable_days = sum(1 for v in pnl_by_date.values() if v > 0)
    losing_days     = sum(1 for v in pnl_by_date.values() if v < 0)
    total_days_with_trades = len(pnl_by_date)
    if total_days_with_trades > 0:
        day_win_pct = profitable_days / total_days_with_trades * 100
        st.caption(
            f"📅 {total_days_with_trades} trading days  ·  "
            f"🟢 {profitable_days} green  ·  "
            f"🔴 {losing_days} red  ·  "
            f"Day win rate: **{day_win_pct:.0f}%**"
        )


# ── Main render ───────────────────────────────────────────────────────

def render() -> None:
    st.title("📓 Trade Journal")
    st.caption("Every paper trade — read like a logbook. Review these to build conviction before going live.")

    all_trades = _trade_log.get_all_trades(limit=500)

    if not all_trades:
        st.info("No trades recorded yet. Start the bot in paper mode to populate the journal.")
        st.caption("Run: `python scripts/run_bot.py`")
        return

    # ── Filters ───────────────────────────────────────────────────────
    with st.container():
        f1, f2, f3, f4 = st.columns([2, 2, 2, 2])

        with f1:
            strategies = sorted({t["strategy"] for t in all_trades})
            strategy_options = ["All Strategies"] + [_friendly_strategy(s) for s in strategies]
            selected_strategy_label = st.selectbox("Strategy", strategy_options)
            selected_strategy = None
            if selected_strategy_label != "All Strategies":
                # Reverse map friendly label → raw key
                rev = {v: k for k, v in _STRATEGY_LABELS.items()}
                selected_strategy = rev.get(selected_strategy_label, selected_strategy_label)

        with f2:
            result_filter = st.selectbox("Result", ["All", "Winners", "Losers", "Open"])

        with f3:
            dates = sorted({t["date"] for t in all_trades if t.get("date")}, reverse=True)
            date_options = ["All Dates"] + dates
            selected_date = st.selectbox("Date", date_options)

        with f4:
            sort_by = st.selectbox("Sort by", ["Newest first", "Oldest first", "Best P&L", "Worst P&L"])

    # ── Apply filters ─────────────────────────────────────────────────
    trades = all_trades

    if selected_strategy:
        trades = [t for t in trades if t["strategy"] == selected_strategy]

    if selected_date != "All Dates":
        trades = [t for t in trades if t.get("date") == selected_date]

    if result_filter == "Winners":
        trades = [t for t in trades if (t.get("net_pnl") or 0) > 0]
    elif result_filter == "Losers":
        trades = [t for t in trades if (t.get("net_pnl") or 0) < 0]
    elif result_filter == "Open":
        trades = [t for t in trades if t.get("exit_price") is None]

    if sort_by == "Newest first":
        trades = sorted(trades, key=lambda t: t.get("timestamp") or "", reverse=True)
    elif sort_by == "Oldest first":
        trades = sorted(trades, key=lambda t: t.get("timestamp") or "")
    elif sort_by == "Best P&L":
        trades = sorted(trades, key=lambda t: t.get("net_pnl") or 0, reverse=True)
    elif sort_by == "Worst P&L":
        trades = sorted(trades, key=lambda t: t.get("net_pnl") or 0)

    # ── Summary KPIs ──────────────────────────────────────────────────
    st.markdown("---")
    closed = [t for t in trades if t.get("net_pnl") is not None]
    wins   = [t for t in closed if (t.get("net_pnl") or 0) > 0]
    losses = [t for t in closed if (t.get("net_pnl") or 0) < 0]
    open_t = [t for t in trades if t.get("exit_price") is None]

    total_pnl = sum((t.get("net_pnl") or 0) for t in closed)
    win_rate  = len(wins) / len(closed) * 100 if closed else 0
    avg_pnl   = total_pnl / len(closed) if closed else 0
    best      = max((t.get("net_pnl") or 0) for t in closed) if closed else 0
    worst     = min((t.get("net_pnl") or 0) for t in closed) if closed else 0

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Trades Shown",  str(len(trades)))
    k2.metric("Closed",        str(len(closed)))
    k3.metric("Win Rate",      f"{win_rate:.1f}%" if closed else "—",
              delta=f"{len(wins)}W / {len(losses)}L")
    k4.metric("Total P&L",     f"₹{total_pnl:+,.0f}" if closed else "—")
    k5.metric("Best Trade",    f"₹{best:+,.0f}" if closed else "—")
    k6.metric("Worst Trade",   f"₹{worst:+,.0f}" if closed else "—")

    st.markdown("---")

    # ── Trade entries (expandable cards) ─────────────────────────────
    if not trades:
        st.warning("No trades match your filters.")
        return

    st.subheader(f"Trade Entries ({len(trades)})")

    for trade in trades:
        pnl      = trade.get("net_pnl")
        symbol   = trade["symbol"]
        strategy = _friendly_strategy(trade["strategy"])
        side     = trade.get("action", "BUY")
        date_str = trade.get("date", "")
        in_time  = trade.get("timestamp", "")[:16].replace("T", " ") if trade.get("timestamp") else "—"
        exit_typ = _exit_type(trade)
        hold     = _hold_duration(trade)
        rr       = _rr_achieved(trade)

        # ── Card header label ─────────────────────────────────────────
        result_icon = "✅" if pnl and pnl > 0 else "❌" if pnl and pnl < 0 else "⏳"
        pnl_str     = f"₹{pnl:+,.0f}" if pnl is not None else "Open"
        header      = (
            f"{result_icon}  **{symbol}** · {side} · {strategy} · "
            f"{date_str} {in_time[-5:]}  →  **{pnl_str}**  ·  {exit_typ}  ·  held {hold}"
        )

        with st.expander(header, expanded=False):
            col_left, col_right = st.columns([3, 2])

            with col_left:
                # ── Setup ─────────────────────────────────────────────
                st.markdown("**Setup**")
                entry  = trade.get("entry_price")
                sl     = trade.get("stop_loss")
                tgt    = trade.get("target")
                qty    = trade.get("quantity", 0)
                ep     = trade.get("exit_price")

                planned_risk   = abs(entry - sl) * qty if entry and sl else None
                planned_reward = abs(tgt - entry) * qty if tgt and entry else None
                planned_rr     = abs(tgt - entry) / abs(entry - sl) if tgt and entry and sl and abs(entry - sl) > 0 else None

                setup_rows = {
                    "Symbol":         symbol,
                    "Side":           side,
                    "Strategy":       strategy,
                    "Entry price":    f"₹{entry:.2f}" if entry else "—",
                    "Stop-loss":      f"₹{sl:.2f}" if sl else "—",
                    "Target":         f"₹{tgt:.2f}" if tgt else "—",
                    "Quantity":       str(qty),
                    "Planned risk":   f"₹{planned_risk:,.0f}" if planned_risk else "—",
                    "Planned reward": f"₹{planned_reward:,.0f}" if planned_reward else "—",
                    "Planned R:R":    f"{planned_rr:.2f}:1" if planned_rr else "—",
                }
                for label, val in setup_rows.items():
                    st.markdown(
                        f"<div style='display:flex;justify-content:space-between;"
                        f"padding:3px 0;border-bottom:1px solid #2a2d3e'>"
                        f"<span style='color:#8b8fa8;font-size:0.85rem'>{label}</span>"
                        f"<span style='font-size:0.85rem'>{val}</span></div>",
                        unsafe_allow_html=True,
                    )

                # ── Signal reason ─────────────────────────────────────
                reason = trade.get("reason", "")
                if reason:
                    st.markdown("")
                    st.markdown("**Why the bot entered**")
                    st.markdown(
                        f"<div style='background:#1a1d27;border-left:3px solid #4f6ef7;"
                        f"padding:10px 14px;border-radius:0 6px 6px 0;"
                        f"font-size:0.84rem;color:#c0c0d0;line-height:1.6'>{reason}</div>",
                        unsafe_allow_html=True,
                    )

            with col_right:
                # ── Outcome ───────────────────────────────────────────
                st.markdown("**Outcome**")

                exit_time = trade.get("exit_timestamp", "")
                if exit_time:
                    exit_time = exit_time[:16].replace("T", " ")
                else:
                    exit_time = "Still open"

                outcome_colour = _pnl_colour(pnl)
                outcome_rows = {
                    "Exit price":     f"₹{ep:.2f}" if ep else "—",
                    "Exit time":      exit_time,
                    "Hold time":      hold,
                    "Exit type":      exit_typ,
                    "R captured":     rr,
                    "Gross P&L":      f"₹{trade.get('pnl') or 0:+,.0f}",
                    "Brokerage":      f"₹{trade.get('brokerage') or 0:.2f}",
                }
                for label, val in outcome_rows.items():
                    st.markdown(
                        f"<div style='display:flex;justify-content:space-between;"
                        f"padding:3px 0;border-bottom:1px solid #2a2d3e'>"
                        f"<span style='color:#8b8fa8;font-size:0.85rem'>{label}</span>"
                        f"<span style='font-size:0.85rem'>{val}</span></div>",
                        unsafe_allow_html=True,
                    )

                # ── Net P&L badge ─────────────────────────────────────
                st.markdown("")
                st.markdown(
                    f"<div style='text-align:center;background:#1a1d27;"
                    f"border:1px solid {outcome_colour};border-radius:10px;"
                    f"padding:14px;margin-top:8px'>"
                    f"<div style='font-size:0.75rem;color:#8b8fa8;text-transform:uppercase;"
                    f"letter-spacing:0.08em'>Net P&L</div>"
                    f"<div style='font-size:1.8rem;font-weight:700;color:{outcome_colour}'>"
                    f"{'₹' + f'{pnl:+,.0f}' if pnl is not None else 'Open'}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                # ── Mini price bar (entry / SL / target / exit) ───────
                if entry and sl and tgt:
                    lo = min(sl, entry, tgt, ep or entry) * 0.999
                    hi = max(sl, entry, tgt, ep or entry) * 1.001
                    fig_mini = go.Figure()

                    def _hline(y, colour, label):
                        fig_mini.add_hline(
                            y=y, line_color=colour, line_width=1.5,
                            annotation_text=label,
                            annotation_position="right",
                            annotation_font_size=9,
                            annotation_font_color=colour,
                        )

                    _hline(tgt, "#4caf50", f"Target ₹{tgt:.0f}")
                    _hline(entry, "#4f6ef7", f"Entry ₹{entry:.0f}")
                    if ep:
                        _hline(ep, "#f7a84f", f"Exit ₹{ep:.0f}")
                    _hline(sl, "#ef5350", f"SL ₹{sl:.0f}")

                    fig_mini.update_layout(
                        template="plotly_dark",
                        paper_bgcolor="#13151f",
                        plot_bgcolor="#13151f",
                        height=160,
                        margin=dict(l=10, r=80, t=10, b=10),
                        yaxis=dict(range=[lo, hi], gridcolor="#2a2d3e",
                                   tickprefix="₹", showticklabels=False),
                        xaxis=dict(visible=False),
                        showlegend=False,
                    )
                    st.plotly_chart(fig_mini, use_container_width=True)

    # ── Analytics charts ──────────────────────────────────────────────
    if len(closed) >= 3:
        st.markdown("---")
        st.subheader("Patterns in this filter")

        ch1, ch2 = st.columns(2)

        # ── Chart 1: Wins/losses by hour of day ───────────────────────
        with ch1:
            st.markdown("**Entry time of day**")
            hour_wins   = {}
            hour_losses = {}
            for t in closed:
                h = _entry_hour(t)
                if h is None:
                    continue
                if (t.get("net_pnl") or 0) > 0:
                    hour_wins[h]   = hour_wins.get(h, 0) + 1
                else:
                    hour_losses[h] = hour_losses.get(h, 0) + 1

            all_hours = sorted(set(list(hour_wins.keys()) + list(hour_losses.keys())))
            if all_hours:
                fig_hrs = go.Figure()
                fig_hrs.add_trace(go.Bar(
                    x=[f"{h}:00" for h in all_hours],
                    y=[hour_wins.get(h, 0) for h in all_hours],
                    name="Wins", marker_color="#4caf50",
                ))
                fig_hrs.add_trace(go.Bar(
                    x=[f"{h}:00" for h in all_hours],
                    y=[-hour_losses.get(h, 0) for h in all_hours],
                    name="Losses", marker_color="#ef5350",
                ))
                fig_hrs.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="#1a1d27",
                    plot_bgcolor="#1a1d27",
                    height=220,
                    margin=dict(l=0, r=0, t=10, b=0),
                    barmode="relative",
                    yaxis=dict(gridcolor="#2a2d3e", title=""),
                    xaxis=dict(gridcolor="#2a2d3e"),
                    legend=dict(orientation="h", y=1.1),
                )
                st.plotly_chart(fig_hrs, use_container_width=True)
                st.caption("Bars above zero = wins. Below = losses. Look for hours where you consistently win.")

        # ── Chart 2: Strategy breakdown ───────────────────────────────
        with ch2:
            st.markdown("**Strategy breakdown**")
            strat_data: dict[str, dict] = {}
            for t in closed:
                s = _friendly_strategy(t["strategy"])
                if s not in strat_data:
                    strat_data[s] = {"wins": 0, "losses": 0, "pnl": 0.0}
                strat_data[s]["pnl"] += (t.get("net_pnl") or 0)
                if (t.get("net_pnl") or 0) > 0:
                    strat_data[s]["wins"] += 1
                else:
                    strat_data[s]["losses"] += 1

            if strat_data:
                strats = list(strat_data.keys())
                win_rates_pct = [
                    strat_data[s]["wins"] / (strat_data[s]["wins"] + strat_data[s]["losses"]) * 100
                    if (strat_data[s]["wins"] + strat_data[s]["losses"]) > 0 else 0
                    for s in strats
                ]
                pnls = [strat_data[s]["pnl"] for s in strats]

                fig_strat = go.Figure()
                fig_strat.add_trace(go.Bar(
                    x=strats,
                    y=win_rates_pct,
                    name="Win Rate %",
                    marker_color=[
                        _STRATEGY_COLOURS.get(
                            {v: k for k, v in _STRATEGY_LABELS.items()}.get(s, s), "#4f6ef7"
                        ) for s in strats
                    ],
                    text=[f"{v:.0f}%" for v in win_rates_pct],
                    textposition="outside",
                ))
                fig_strat.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="#1a1d27",
                    plot_bgcolor="#1a1d27",
                    height=220,
                    margin=dict(l=0, r=0, t=10, b=0),
                    yaxis=dict(gridcolor="#2a2d3e", range=[0, 110], title="Win Rate %"),
                    xaxis=dict(gridcolor="#2a2d3e"),
                    showlegend=False,
                )
                st.plotly_chart(fig_strat, use_container_width=True)
                st.caption("Target: >45% win rate per strategy before going live.")

    # ── Daily P&L Calendar heatmap ────────────────────────────────────
    # Uses the full trade history (ignores filters) so the calendar always
    # shows the complete picture, not just the currently-filtered subset.
    daily_rows = _trade_log.get_daily_pnl()
    if len(daily_rows) >= 2:
        st.markdown("---")
        st.subheader("📅 Daily P&L Calendar")
        st.caption(
            "Green = profitable day · Red = losing day · Grey = no trades. "
            "Look for patterns: do losses cluster on specific days or weeks?"
        )
        _render_calendar_heatmap(daily_rows)

    st.caption("Source: logs/trades.db · Paper mode · No real money at risk")
