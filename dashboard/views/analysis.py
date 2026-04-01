"""
Analysis page — NIFTY50 market overview, breadth, top movers.

What you see here:
  - NIFTY50 index level and today's change
  - Advance/Decline ratio: how many of the 50 stocks are up vs down
  - Top 5 gainers and losers from NIFTY50 today
  - A heatmap-style view of all NIFTY50 sectors

This helps you understand the MARKET MOOD before trading:
  - If 40+ stocks are advancing → broad bull day → favour BUY signals
  - If 40+ stocks are declining → broad bear day → be cautious
  - If it's mixed → choppy/sideways → avoid ORB and favour RSI+MACD

Data is fetched live from yfinance (free, no API key).
"""

from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from analysis.market_overview import get_nifty_overview, MarketOverview


def render() -> None:
    st.title("🌐 Market Analysis")
    st.caption("NIFTY50 breadth, top movers, and sector view. Data from yfinance.")

    refresh = st.button("🔄 Refresh Data", type="primary")

    # Cache overview in session state
    if refresh or "market_overview" not in st.session_state:
        with st.spinner("Fetching market data..."):
            overview: MarketOverview | None = get_nifty_overview(top_n=5)
        st.session_state["market_overview"] = overview
    else:
        overview = st.session_state["market_overview"]

    if overview is None:
        st.error("Could not fetch market data. Check your internet connection and try again.")
        return

    # ── NIFTY50 index ─────────────────────────────────────────────────
    st.subheader("NIFTY50 Index")
    col1, col2, col3 = st.columns(3)
    col1.metric("NIFTY50 Price", f"{overview.nifty_price:,.2f}")
    col2.metric("Day Change",    f"{overview.nifty_change:+.2f}",
                delta=f"{overview.nifty_change_pct:+.2f}%")
    col3.metric("Direction",     "🟢 UP" if overview.nifty_change >= 0 else "🔴 DOWN")

    st.markdown("---")

    # ── Advance/Decline ───────────────────────────────────────────────
    st.subheader("Market Breadth (Advance / Decline)")
    col4, col5, col6 = st.columns(3)
    col4.metric("Advancing",  overview.advances, delta="stocks up")
    col5.metric("Declining",  overview.declines, delta="stocks down")
    col6.metric("Unchanged",  overview.unchanged)

    # Simple donut chart
    fig_pie = go.Figure(go.Pie(
        labels=["Advancing", "Declining", "Unchanged"],
        values=[overview.advances, overview.declines, overview.unchanged],
        hole=0.5,
        marker_colors=["#4CAF50", "#F44336", "#9E9E9E"],
    ))
    fig_pie.update_layout(
        title="NIFTY50 Breadth",
        template="plotly_dark",
        height=300,
        showlegend=True,
    )
    st.plotly_chart(fig_pie, use_container_width=True)

    # ── What this means (beginner tip) ───────────────────────────────
    adv_ratio = overview.advances / max(overview.total_symbols, 1) * 100
    if adv_ratio >= 60:
        st.success(f"**Market Mood: Broadly Bullish** — {overview.advances} of {overview.total_symbols} stocks are advancing. Favour BUY signals today.")
    elif adv_ratio <= 40:
        st.error(f"**Market Mood: Broadly Bearish** — Only {overview.advances} of {overview.total_symbols} stocks are up. Be cautious with new positions.")
    else:
        st.warning(f"**Market Mood: Mixed** — {overview.advances} advancing, {overview.declines} declining. Avoid low-conviction trades.")

    st.markdown("---")

    # ── Top gainers / losers ──────────────────────────────────────────
    col_g, col_l = st.columns(2)

    with col_g:
        st.subheader("🟢 Top Gainers")
        if overview.top_gainers:
            gainers_df = pd.DataFrame(overview.top_gainers)
            gainers_df.columns = ["Symbol", "Change %", "Price ₹"]
            st.dataframe(gainers_df, use_container_width=True, hide_index=True)
        else:
            st.info("No gainer data available.")

    with col_l:
        st.subheader("🔴 Top Losers")
        if overview.top_losers:
            losers_df = pd.DataFrame(overview.top_losers)
            losers_df.columns = ["Symbol", "Change %", "Price ₹"]
            st.dataframe(losers_df, use_container_width=True, hide_index=True)
        else:
            st.info("No loser data available.")

    st.caption(f"Data covers {overview.total_symbols} of 50 NIFTY symbols. Some may be unavailable.")
