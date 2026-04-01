"""
Signals page — scan NIFTY50 for live strategy signals.

What this does:
  Runs all three strategies against recent daily data for each NIFTY50 stock.
  Surfaces any stock where a BUY or SELL signal is currently active.

  This is like a "radar" for your strategies — instead of watching 50 stocks
  manually, the scanner does it automatically and shows you what's interesting.

Note: The scanner uses end-of-day data from yfinance.
      In a live trading setup, it would use real-time tick data instead.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analysis.stock_scanner import scan_nifty50, ScanResult
from data.historical import fetch_ohlcv
from data.instruments import KITE_TO_YF
from strategies.base_strategy import Action


def render() -> None:
    st.title("🔍 Signal Scanner")
    st.caption("Scans all NIFTY50 stocks for active BUY/SELL signals using your strategies.")

    # ── Controls ──────────────────────────────────────────────────────
    col1, col2 = st.columns([2, 1])
    with col1:
        selected_strategies = st.multiselect(
            "Strategies to scan",
            ["EMA Crossover", "RSI+MACD Combo", "ORB"],
            default=["EMA Crossover", "RSI+MACD Combo", "ORB"],
        )
    with col2:
        max_syms = st.slider("Max symbols to scan", 10, 50, 50)

    run_scan = st.button("🔍 Run Scanner", type="primary")

    if not run_scan:
        st.info("Click **Run Scanner** to scan NIFTY50 for active signals. This takes ~30–60 seconds.")
        return

    # ── Run scan ──────────────────────────────────────────────────────
    with st.spinner("Scanning NIFTY50... (fetching data for each symbol)"):
        results: list[ScanResult] = scan_nifty50(
            strategies=selected_strategies if selected_strategies else None,
            max_symbols=max_syms,
        )

    if not results:
        st.warning("No signals found. Try a different date, or the market may be in a sideways phase.")
        return

    st.success(f"Found **{len(results)}** signal(s) across NIFTY50.")

    # ── Results table ─────────────────────────────────────────────────
    rows = []
    for r in results:
        rows.append({
            "Symbol":     r.symbol,
            "Strategy":   r.strategy,
            "Signal":     "🟢 BUY" if r.action == Action.BUY else "🔴 SELL",
            "Entry ₹":    r.entry_price,
            "Stop Loss ₹": r.stop_loss,
            "Target ₹":   r.target,
            "RR Ratio":   f"{r.rr_ratio:.1f}x",
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── Detail chart for selected symbol ──────────────────────────────
    st.subheader("📈 Price Chart")
    symbols = [r.symbol for r in results]
    chosen  = st.selectbox("View chart for:", symbols)

    if chosen:
        signal = next((r for r in results if r.symbol == chosen), None)
        yf_sym = KITE_TO_YF.get(chosen, chosen + ".NS")
        hist   = fetch_ohlcv(yf_sym, period="3mo", interval="1d")

        if hist is not None and not hist.empty:
            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=hist.index,
                open=hist["open"], high=hist["high"],
                low=hist["low"],   close=hist["close"],
                name=chosen,
            ))

            if signal:
                # Mark the signal level
                color = "green" if signal.action == Action.BUY else "red"
                fig.add_hline(y=signal.entry_price, line_dash="dot",
                              line_color=color, annotation_text=f"Entry {signal.entry_price}")
                fig.add_hline(y=signal.stop_loss,  line_dash="dash",
                              line_color="red",   annotation_text=f"SL {signal.stop_loss}")
                fig.add_hline(y=signal.target,     line_dash="dash",
                              line_color="green", annotation_text=f"Target {signal.target}")

            fig.update_layout(
                title=f"{chosen} — 3-Month Daily Chart",
                template="plotly_dark",
                height=500,
                xaxis_rangeslider_visible=False,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning(f"Could not load chart data for {chosen}.")
