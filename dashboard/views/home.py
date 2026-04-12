"""
Home page — Portfolio summary, today's trades, capital breakdown.

Reads from SQLite trade log and the paper broker's in-memory state.
In paper mode, nothing here involves real money.
"""

from __future__ import annotations

import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config.settings import VIRTUAL_CAPITAL as INITIAL_CAPITAL
from execution.trade_log import TradeLogger

# Module-level singleton — created once per process, not on every page render
_trade_log = TradeLogger()


def _get_live_ltp(symbol: str) -> float | None:
    """
    Try to get a live price for symbol from available sources:
      1. KiteTickerFeed WebSocket (fastest, < 1s lag)
      2. Returns None if neither is available (market closed / feed not running)
    """
    try:
        from data.kite_ticker import get_ticker_feed
        ltp = get_ticker_feed().get_ltp(symbol)
        if ltp:
            return ltp
    except Exception:
        pass
    return None


def _pnl_colour(val: float) -> str:
    return "#4caf50" if val >= 0 else "#ef5350"


def render() -> None:
    st.title("Portfolio Overview")

    db = _trade_log
    today_trades   = db.get_today_trades()
    daily_pnl_rows = db.get_daily_pnl()
    daily_pnl_map  = {row["date"]: (row["net_pnl"] or 0.0) for row in daily_pnl_rows}
    today_str      = str(pd.Timestamp.now().date())
    today_pnl      = daily_pnl_map.get(today_str, 0.0)
    total_pnl      = sum(daily_pnl_map.values())
    final_capital  = INITIAL_CAPITAL + total_pnl
    total_return   = total_pnl / INITIAL_CAPITAL * 100

    # ── KPI row ───────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Capital",        f"₹{final_capital:,.0f}",
              delta=f"{'+' if total_pnl >= 0 else '-'}₹{abs(total_pnl):,.0f} total")
    c2.metric("Today P&L",      f"₹{today_pnl:,.0f}",
              delta=f"{today_pnl / INITIAL_CAPITAL * 100:+.2f}%")
    c3.metric("Total Return",   f"{total_return:+.2f}%")
    c4.metric("Trading Days",   str(len(daily_pnl_map)))
    c5.metric("Trades Today",   str(len(today_trades)))

    st.markdown("---")

    # ── Equity curve + daily P&L  (side by side) ─────────────────────
    left, right = st.columns(2)

    with left:
        st.subheader("Equity Curve")
        if daily_pnl_map:
            dates  = sorted(daily_pnl_map.keys())
            equity = [INITIAL_CAPITAL]
            for d in dates:
                equity.append(equity[-1] + daily_pnl_map[d])
            x_pts = ["Start"] + dates

            fig_eq = go.Figure()
            fig_eq.add_trace(go.Scatter(
                x=x_pts, y=equity,
                mode="lines",
                line=dict(color="#4f6ef7", width=2.5),
                fill="tozeroy",
                fillcolor="rgba(79,110,247,0.08)",
                name="Portfolio",
            ))
            fig_eq.add_hline(y=INITIAL_CAPITAL, line_dash="dot",
                             line_color="#444", opacity=0.7)
            fig_eq.update_layout(
                template="plotly_dark",
                paper_bgcolor="#1a1d27",
                plot_bgcolor="#1a1d27",
                height=260,
                margin=dict(l=0, r=0, t=10, b=0),
                yaxis=dict(gridcolor="#2a2d3e", tickprefix="₹"),
                xaxis=dict(gridcolor="#2a2d3e"),
                showlegend=False,
            )
            st.plotly_chart(fig_eq, use_container_width=True)
        else:
            st.info("No trade history yet.")

    with right:
        st.subheader("Daily P&L")
        if daily_pnl_map:
            dates = sorted(daily_pnl_map.keys())
            pnls  = [daily_pnl_map[d] for d in dates]
            colours = [_pnl_colour(p) for p in pnls]

            fig_bar = go.Figure(go.Bar(
                x=dates, y=pnls,
                marker_color=colours,
                text=[f"₹{p:+,.0f}" for p in pnls],
                textposition="outside",
                textfont=dict(size=10),
            ))
            fig_bar.add_hline(y=0, line_color="#555", line_width=1)
            fig_bar.update_layout(
                template="plotly_dark",
                paper_bgcolor="#1a1d27",
                plot_bgcolor="#1a1d27",
                height=260,
                margin=dict(l=0, r=0, t=10, b=0),
                yaxis=dict(gridcolor="#2a2d3e", tickprefix="₹"),
                xaxis=dict(gridcolor="#2a2d3e"),
                showlegend=False,
            )
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info("No trade history yet.")

    st.markdown("---")

    # ── Today's trades ────────────────────────────────────────────────
    hdr_col, refresh_col, auto_col = st.columns([5, 1, 2])
    hdr_col.subheader("Today's Trades")
    refresh_clicked = refresh_col.button(":material/refresh: Refresh", use_container_width=True)
    auto_refresh    = auto_col.toggle("Auto-refresh (5s)", value=False)

    if not today_trades:
        st.info("No trades today. Market may be closed or no signals fired yet.")
    else:
        open_count = sum(1 for t in today_trades if t["exit_price"] is None)
        if open_count:
            st.caption(f":material/schedule: {open_count} open position(s) — live prices from KiteTickerFeed")

        rows = []
        for t in today_trades:
            pnl        = t["net_pnl"]
            is_open    = t["exit_price"] is None
            in_time    = t["timestamp"][11:16]  if t.get("timestamp")       else "—"
            exit_ts    = t.get("exit_timestamp")
            out_time   = exit_ts[11:16]          if exit_ts                  else "OPEN"
            entry      = float(t["entry_price"]) if t["entry_price"]         else 0.0
            sl         = float(t["stop_loss"])   if t.get("stop_loss")       else 0.0
            target     = float(t["target"])      if t.get("target")          else 0.0
            is_buy     = t["action"] == "BUY"
            qty        = int(t["quantity"])

            if is_open:
                ltp = _get_live_ltp(t["symbol"])
            else:
                ltp = None

            # Unrealised P&L
            if is_open and ltp:
                unreal = (ltp - entry) * qty if is_buy else (entry - ltp) * qty
                unreal_str = f"₹{unreal:+.0f}"
                ltp_str    = f"₹{ltp:.2f}"
                # Distance to SL / target as %
                sl_dist    = abs(ltp - sl) / entry * 100 if sl else None
                tgt_dist   = abs(target - ltp) / entry * 100 if target else None
                sl_str     = f"{sl_dist:.1f}% away" if sl_dist is not None else "—"
                tgt_str    = f"{tgt_dist:.1f}% away" if tgt_dist is not None else "—"
                result     = ":material/pending: Live"
            else:
                unreal_str = "—"
                ltp_str    = "—" if is_open else "—"
                sl_str     = "—"
                tgt_str    = "—"
                result     = (
                    ":material/check_circle: Win"
                    if pnl and pnl > 0
                    else ":material/cancel: Loss"
                    if pnl and pnl < 0
                    else ":material/schedule: Open"
                )

            rows.append({
                "Symbol":       t["symbol"],
                "Strategy":     t["strategy"],
                "Side":         t["action"],
                "In":           in_time,
                "Out":          out_time,
                "Entry ₹":      f"{entry:.2f}" if entry else "—",
                "LTP ₹":        ltp_str,
                "Exit ₹":       f"{t['exit_price']:.2f}" if t["exit_price"] else "—",
                "Qty":          qty,
                "SL dist.":     sl_str,
                "Target dist.": tgt_str,
                "Unreal. P&L":  unreal_str,
                "Net P&L ₹":    f"{pnl:+.0f}" if pnl is not None else "—",
                "Result":       result,
            })

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption(f"Last updated: {time.strftime('%H:%M:%S')} IST")

    # Auto-refresh: sleep then rerun — only activates when toggled on
    if auto_refresh:
        time.sleep(5)
        st.rerun()

    st.markdown("---")

    # ── Strategy summary ──────────────────────────────────────────────
    st.subheader("Strategy Performance")
    summary = db.get_strategy_summary()

    if not summary:
        st.info("No closed trades recorded yet.")
    else:
        rows = []
        for s in summary:
            total = s["total_net_pnl"] or 0
            rows.append({
                "Strategy":  s["strategy"],
                "Trades":    s["num_trades"],
                "Wins":      s["wins"],
                "Win %":     f"{s['win_rate_pct'] or 0:.1f}%",
                "Total P&L": f"₹{total:+,.0f}",
                "Avg P&L":   f"₹{s['avg_net_pnl'] or 0:+,.0f}",
                "Status":    ":material/check_circle: Positive" if total > 0 else ":material/cancel: Negative",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.caption("Source: logs/trades.db · Paper mode · No real money")
