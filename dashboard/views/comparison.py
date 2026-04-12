"""
Strategy Head-to-Head Comparison — live performance from paper trade data.

Why this page matters:
  Backtests tell you how a strategy *would have* performed on historical data.
  This page tells you how it's *actually* performing in real paper trading
  with real market conditions, real timing, and real signal generation.

  The two numbers that matter most before going live:
    1. Win rate ≥ 45%  — you're right more than you're wrong
    2. Profit factor ≥ 1.5 — your wins are worth more than your losses

  If any strategy falls below these thresholds after 20+ trades, that's
  a signal to investigate before risking real money on it.

What you'll see:
  - KPI scorecards per strategy (win rate, total P&L, avg trade, profit factor)
  - Cumulative P&L chart — all strategies on one timeline
  - Rolling 10-trade win rate trend — shows whether a strategy is improving
  - Trade-by-trade comparison table
  - Head-to-head winner summary at the top (which strategy is winning today)
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from execution.trade_log import TradeLogger

# Module-level singleton — avoids re-opening the DB on every Streamlit rerun
_trade_log = TradeLogger()

# ── Strategy display config ───────────────────────────────────────────

_STRATEGIES = {
    "ema_crossover":          {"label": "EMA Crossover",  "colour": "#4f6ef7"},
    "rsi_macd_combo":         {"label": "RSI+MACD Combo", "colour": "#f7a84f"},
    "opening_range_breakout": {"label": "ORB",            "colour": "#4fc9f7"},
    "gap_and_go":             {"label": "Gap & Go",       "colour": "#a78bfa"},
}

_WIN_RATE_TARGET    = 45.0   # minimum acceptable win rate %
_PROFIT_FACTOR_MIN  = 1.5    # minimum acceptable profit factor


# ── Helpers ───────────────────────────────────────────────────────────

def _profit_factor(pnls: list[float]) -> float:
    """
    Profit factor = total gross profit / total gross loss.
    A value of 2.0 means you earn ₹2 for every ₹1 you lose.
    Anything above 1.5 is considered acceptable; above 2.0 is strong.
    Returns 0.0 if there are no losses (avoids division by zero).
    """
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss   = sum(abs(p) for p in pnls if p < 0)
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return round(gross_profit / gross_loss, 2)


def _rolling_win_rate(pnls: list[float], window: int = 10) -> list[float | None]:
    """
    Compute a rolling win-rate series for sparkline display.
    Each point is the win% of the last `window` trades up to that point.
    Returns None for early points where fewer than `window` trades exist.
    """
    result = []
    for i in range(len(pnls)):
        start = max(0, i - window + 1)
        chunk = pnls[start : i + 1]
        if len(chunk) < window:
            result.append(None)
        else:
            result.append(round(sum(1 for p in chunk if p > 0) / window * 100, 1))
    return result


def _build_stats(trades: list[dict]) -> dict:
    """Build the full stats dict from a list of closed trade dicts."""
    pnls       = [t["net_pnl"] for t in trades if t["net_pnl"] is not None]
    n          = len(pnls)
    if n == 0:
        return {
            "count": 0, "wins": 0, "losses": 0, "win_rate": None,
            "total_pnl": 0.0, "avg_pnl": 0.0, "best": 0.0, "worst": 0.0,
            "profit_factor": 0.0, "pnls": [],
        }
    wins   = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    return {
        "count":         n,
        "wins":          wins,
        "losses":        losses,
        "win_rate":      round(wins / n * 100, 1),
        "total_pnl":     round(sum(pnls), 2),
        "avg_pnl":       round(sum(pnls) / n, 2),
        "best":          round(max(pnls), 2),
        "worst":         round(min(pnls), 2),
        "profit_factor": _profit_factor(pnls),
        "pnls":          pnls,
    }


def _colour_metric(value: float, good_above: float = 0) -> str:
    """Return green/red colour string based on whether value is above threshold."""
    return "normal" if value > good_above else "inverse"


# ── Main render ───────────────────────────────────────────────────────

def render() -> None:
    st.title(":material/compare_arrows: Strategy Head-to-Head")
    st.caption(
        "Live performance from your paper trade data. "
        "This is how each strategy is *actually* doing, not how it did in backtests."
    )

    # ── Load data ─────────────────────────────────────────────────────
    all_trades = _trade_log.get_all_trades(limit=500)
    closed     = [t for t in all_trades if t.get("net_pnl") is not None]

    if not closed:
        st.info(
            "No closed trades in the database yet.\n\n"
            "Start the paper trading bot and let a few trades close (hit target or stop-loss). "
            "This page will populate automatically as trades complete."
        )
        _render_placeholder_explainer()
        return

    # Group trades by strategy
    by_strategy: dict[str, list[dict]] = {}
    for trade in closed:
        s = trade.get("strategy", "unknown")
        by_strategy.setdefault(s, []).append(trade)

    # Build stats for all known strategies (even those with 0 trades)
    stats: dict[str, dict] = {}
    for key in _STRATEGIES:
        trades_for_strat = sorted(
            by_strategy.get(key, []),
            key=lambda t: t.get("timestamp") or "",
        )
        stats[key] = _build_stats(trades_for_strat)

    # ── Winner banner ─────────────────────────────────────────────────
    _render_winner_banner(stats)

    st.markdown("---")

    # ── KPI scorecards (one column per strategy) ──────────────────────
    st.subheader(":material/analytics: Scorecard")
    st.caption(
        f"Win rate target: **≥{_WIN_RATE_TARGET:.0f}%** · "
        f"Profit factor target: **≥{_PROFIT_FACTOR_MIN:.1f}**"
    )

    cols = st.columns(len(_STRATEGIES))
    for col, (key, cfg) in zip(cols, _STRATEGIES.items()):
        s = stats[key]
        _render_strategy_card(col, cfg["label"], cfg["colour"], s)

    st.markdown("---")

    # ── Cumulative P&L chart ──────────────────────────────────────────
    st.subheader(":material/show_chart: Cumulative P&L by Strategy")
    st.caption("Each line is the running total of net P&L for that strategy over time.")
    _render_cumulative_pnl_chart(by_strategy, closed)

    st.markdown("---")

    # ── Rolling win rate trend ────────────────────────────────────────
    st.subheader(":material/track_changes: Rolling 10-Trade Win Rate")
    st.caption(
        "Shows whether each strategy is getting better or worse over time. "
        "A falling line means recent trades are underperforming."
    )
    _render_rolling_win_rate_chart(by_strategy)

    st.markdown("---")

    # ── Head-to-head table ────────────────────────────────────────────
    st.subheader(":material/table: Side-by-Side Summary Table")
    _render_summary_table(stats)

    st.markdown("---")

    # ── Per-strategy drilldown ────────────────────────────────────────
    st.subheader(":material/manage_search: Strategy Drilldown")
    selected = st.selectbox(
        "Select strategy to inspect trade-by-trade",
        [cfg["label"] for cfg in _STRATEGIES.values()],
    )
    key_for_selected = next(
        k for k, v in _STRATEGIES.items() if v["label"] == selected
    )
    _render_drilldown(by_strategy.get(key_for_selected, []), _STRATEGIES[key_for_selected])


# ── Sub-renderers ─────────────────────────────────────────────────────

def _render_winner_banner(stats: dict) -> None:
    """Banner showing which strategy is currently leading on P&L."""
    # Only compare strategies with at least 1 closed trade
    ranked = sorted(
        [(k, s) for k, s in stats.items() if s["count"] > 0],
        key=lambda x: x[1]["total_pnl"],
        reverse=True,
    )
    if not ranked:
        return

    leader_key, leader_stats = ranked[0]
    leader_cfg  = _STRATEGIES.get(leader_key, {"label": leader_key, "colour": "#4f6ef7"})
    colour      = leader_cfg["colour"]
    label       = leader_cfg["label"]
    total_pnl   = leader_stats["total_pnl"]
    win_rate    = leader_stats["win_rate"]
    pnl_sign    = "+" if total_pnl >= 0 else ""

    st.markdown(
        f"<div style='background:#1a1d27;border:1px solid {colour};"
        f"border-radius:12px;padding:16px 20px;margin-bottom:8px'>"
        f"<span style='font-size:0.8rem;color:#9ca3af;text-transform:uppercase;"
        f"letter-spacing:0.08em'>Currently Leading</span><br>"
        f"<span style='font-size:1.3rem;font-weight:700;color:{colour}'>{label}</span>"
        f"<span style='font-size:1rem;color:#e0e0e0;margin-left:16px'>"
        f"₹{pnl_sign}{total_pnl:,.2f} total  ·  {win_rate}% win rate  ·  "
        f"{leader_stats['count']} trades</span>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _render_strategy_card(col, label: str, colour: str, s: dict) -> None:
    """Render one strategy's KPI card in the given column."""
    with col:
        st.markdown(
            f"<div style='border-top:3px solid {colour};padding-top:8px;"
            f"margin-bottom:8px'>"
            f"<span style='font-weight:700;font-size:0.95rem;color:{colour}'>"
            f"{label}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        if s["count"] == 0:
            st.caption("No closed trades yet")
            return

        wr     = s["win_rate"]
        pf     = s["profit_factor"]
        total  = s["total_pnl"]
        avg    = s["avg_pnl"]

        # Win rate with colour
        wr_colour  = "#4caf50" if wr >= _WIN_RATE_TARGET else "#ef5350"
        pf_display = f"{pf:.2f}×" if pf != float("inf") else "∞"
        pf_colour  = "#4caf50" if pf >= _PROFIT_FACTOR_MIN else "#ef5350"
        ttl_colour = "#4caf50" if total >= 0 else "#ef5350"

        st.markdown(
            f"<table style='width:100%;font-size:0.85rem;border-collapse:collapse'>"
            f"<tr><td style='color:#9ca3af;padding:3px 0'>Trades</td>"
            f"<td style='color:#e0e0e0;text-align:right'>{s['count']}</td></tr>"
            f"<tr><td style='color:#9ca3af;padding:3px 0'>Win Rate</td>"
            f"<td style='color:{wr_colour};font-weight:700;text-align:right'>{wr}%</td></tr>"
            f"<tr><td style='color:#9ca3af;padding:3px 0'>Profit Factor</td>"
            f"<td style='color:{pf_colour};font-weight:700;text-align:right'>{pf_display}</td></tr>"
            f"<tr><td style='color:#9ca3af;padding:3px 0'>Total P&L</td>"
            f"<td style='color:{ttl_colour};font-weight:700;text-align:right'>"
            f"₹{total:+,.2f}</td></tr>"
            f"<tr><td style='color:#9ca3af;padding:3px 0'>Avg / Trade</td>"
            f"<td style='color:#e0e0e0;text-align:right'>₹{avg:+.2f}</td></tr>"
            f"<tr><td style='color:#9ca3af;padding:3px 0'>Best</td>"
            f"<td style='color:#4caf50;text-align:right'>₹{s['best']:+.2f}</td></tr>"
            f"<tr><td style='color:#9ca3af;padding:3px 0'>Worst</td>"
            f"<td style='color:#ef5350;text-align:right'>₹{s['worst']:+.2f}</td></tr>"
            f"</table>",
            unsafe_allow_html=True,
        )


def _render_cumulative_pnl_chart(
    by_strategy: dict[str, list[dict]],
    all_closed: list[dict],
) -> None:
    """Cumulative P&L line chart — one line per strategy, plotted on shared time axis."""
    fig = go.Figure()

    has_data = False
    for key, cfg in _STRATEGIES.items():
        trades = sorted(
            by_strategy.get(key, []),
            key=lambda t: t.get("exit_timestamp") or t.get("timestamp") or "",
        )
        if not trades:
            continue

        times   = []
        cum_pnl = []
        running = 0.0
        for t in trades:
            ts = t.get("exit_timestamp") or t.get("timestamp")
            if ts is None:
                continue
            # Timestamps stored as ISO strings in the dict
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts)
                except ValueError:
                    continue
            running += t.get("net_pnl") or 0.0
            times.append(ts)
            cum_pnl.append(round(running, 2))

        if not times:
            continue

        has_data = True
        # Add a zero anchor at the first trade's time so lines start at 0
        first_ts   = times[0]
        times_plot = [first_ts] + times
        pnl_plot   = [0.0] + cum_pnl

        fig.add_trace(go.Scatter(
            x=times_plot,
            y=pnl_plot,
            mode="lines+markers",
            name=cfg["label"],
            line=dict(color=cfg["colour"], width=2),
            marker=dict(size=5, color=cfg["colour"]),
            hovertemplate=(
                f"<b>{cfg['label']}</b><br>"
                "Date: %{x|%d %b %Y %H:%M}<br>"
                "Cum. P&L: ₹%{y:,.2f}<extra></extra>"
            ),
        ))

    if not has_data:
        st.caption("No closed trades yet to plot.")
        return

    fig.add_hline(y=0, line_dash="dot", line_color="#9ca3af", line_width=1)

    fig.update_layout(
        height=340,
        paper_bgcolor="#0f1117",
        plot_bgcolor="#0f1117",
        font=dict(color="#9ca3af", size=12),
        xaxis=dict(
            gridcolor="#1e2030",
            showgrid=True,
            title=None,
            tickformat="%d %b",
        ),
        yaxis=dict(
            gridcolor="#1e2030",
            showgrid=True,
            title="Cumulative Net P&L (₹)",
            tickprefix="₹",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            bgcolor="rgba(0,0,0,0)",
        ),
        margin=dict(l=60, r=20, t=40, b=40),
        hovermode="x unified",
    )

    st.plotly_chart(fig, use_container_width=True)


def _render_rolling_win_rate_chart(by_strategy: dict[str, list[dict]]) -> None:
    """
    Rolling 10-trade win rate per strategy.
    Helps spot if a strategy is consistently improving or declining.
    """
    fig = go.Figure()
    has_data = False

    for key, cfg in _STRATEGIES.items():
        trades = sorted(
            by_strategy.get(key, []),
            key=lambda t: t.get("timestamp") or "",
        )
        pnls = [t["net_pnl"] for t in trades if t.get("net_pnl") is not None]

        if len(pnls) < 3:
            continue

        rolling = _rolling_win_rate(pnls, window=min(10, len(pnls)))
        # Build trade index labels (Trade #1, #2, …)
        x_vals  = list(range(1, len(pnls) + 1))
        y_vals  = [r if r is not None else None for r in rolling]

        has_data = True
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=y_vals,
            mode="lines+markers",
            name=cfg["label"],
            line=dict(color=cfg["colour"], width=2),
            marker=dict(size=5),
            connectgaps=True,
            hovertemplate=(
                f"<b>{cfg['label']}</b><br>"
                "Trade #%{x}<br>"
                "Win Rate: %{y:.1f}%<extra></extra>"
            ),
        ))

    if not has_data:
        st.caption("Need at least 3 closed trades per strategy to show rolling win rate.")
        return

    # Target line
    fig.add_hline(
        y=_WIN_RATE_TARGET,
        line_dash="dash",
        line_color="#ffc107",
        line_width=1.5,
        annotation_text=f"Target {_WIN_RATE_TARGET:.0f}%",
        annotation_position="right",
        annotation_font_color="#ffc107",
    )

    fig.update_layout(
        height=300,
        paper_bgcolor="#0f1117",
        plot_bgcolor="#0f1117",
        font=dict(color="#9ca3af", size=12),
        xaxis=dict(
            gridcolor="#1e2030",
            title="Trade Number",
            showgrid=True,
            dtick=5,
        ),
        yaxis=dict(
            gridcolor="#1e2030",
            title="Win Rate (%)",
            showgrid=True,
            range=[0, 105],
            ticksuffix="%",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            bgcolor="rgba(0,0,0,0)",
        ),
        margin=dict(l=60, r=80, t=40, b=40),
        hovermode="x unified",
    )

    st.plotly_chart(fig, use_container_width=True)


def _render_summary_table(stats: dict) -> None:
    """Clean summary table comparing all strategies side by side."""
    rows = []
    for key, cfg in _STRATEGIES.items():
        s = stats[key]
        if s["count"] == 0:
            rows.append({
                "Strategy":      cfg["label"],
                "Trades":        0,
                "Win Rate":      "—",
                "Profit Factor": "—",
                "Total P&L (₹)": "—",
                "Avg / Trade":   "—",
                "Best Trade":    "—",
                "Worst Trade":   "—",
            })
        else:
            pf_str = f"{s['profit_factor']:.2f}×" if s["profit_factor"] != float("inf") else "∞"
            rows.append({
                "Strategy":      cfg["label"],
                "Trades":        s["count"],
                "Win Rate":      f"{s['win_rate']}%",
                "Profit Factor": pf_str,
                "Total P&L (₹)": f"₹{s['total_pnl']:+,.2f}",
                "Avg / Trade":   f"₹{s['avg_pnl']:+.2f}",
                "Best Trade":    f"₹{s['best']:+.2f}",
                "Worst Trade":   f"₹{s['worst']:+.2f}",
            })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


def _render_drilldown(trades: list[dict], cfg: dict) -> None:
    """Trade-by-trade table for one strategy."""
    if not trades:
        st.caption(f"No closed trades for {cfg['label']} yet.")
        return

    closed = [t for t in trades if t.get("net_pnl") is not None]
    if not closed:
        st.caption(f"No closed trades for {cfg['label']} yet.")
        return

    rows = []
    for t in sorted(closed, key=lambda x: x.get("timestamp") or "", reverse=True):
        pnl    = t["net_pnl"] or 0.0
        entry  = t.get("entry_price", 0.0) or 0.0
        exit_p = t.get("exit_price") or 0.0
        risk   = abs(entry - (t.get("stop_loss") or entry))
        rr     = round(abs(exit_p - entry) / risk, 2) if risk > 0 else 0.0
        rows.append({
            "Date":     (t.get("date") or "")[:10],
            "Symbol":   t.get("symbol", ""),
            "Action":   t.get("action", ""),
            "Entry":    f"₹{entry:.2f}",
            "Exit":     f"₹{exit_p:.2f}",
            "P&L":      f"₹{pnl:+.2f}",
            "R Earned": f"{rr:.2f}R",
            "Outcome":  "Win" if pnl > 0 else "Loss",
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


def _render_placeholder_explainer() -> None:
    """Shown when there's no data yet — explains what will appear."""
    st.markdown("""
    #### What this page will show once trades start closing:

    **Scorecard** — for each strategy:
    - Win rate (target ≥45%)
    - Profit factor (target ≥1.5×)
    - Total and average P&L

    **Cumulative P&L chart** — see which strategy compounds fastest over time.

    **Rolling win rate trend** — is a strategy improving or deteriorating recently?

    **Strategy drilldown** — every trade for a selected strategy, outcome by outcome.

    This is the key page to watch during your 30-day paper period to build
    confidence before switching to live mode.
    """)
