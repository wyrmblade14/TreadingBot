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

from analysis.regime_detector import (
    get_current_regime, get_regime_details, regime_allows_strategy, MarketRegime
)
from analysis.stock_scanner import scan_nifty50, ScanResult
from data.historical import fetch_ohlcv
from data.instruments import KITE_TO_YF
from strategies.base_strategy import Action


def render() -> None:
    st.title("🔍 Signal Scanner")
    st.caption("Scans all NIFTY50 stocks for active BUY/SELL signals using your strategies.")

    # ── Market Regime Banner ──────────────────────────────────────────
    # Shows the current NIFTY50 market regime before running the scanner,
    # so you know upfront which strategies are active and which are suppressed.
    with st.spinner("Checking market regime..."):
        regime  = get_current_regime()
        details = get_regime_details()

    _REGIME_CONFIG = {
        MarketRegime.TRENDING:  ("🟢", "#1b5e20", "#4caf50", "Strong trend — all strategies active."),
        MarketRegime.RANGING:   ("🟡", "#4a3900", "#ffc107", "Sideways market — EMA + ORB suppressed. RSI+MACD still active."),
        MarketRegime.VOLATILE:  ("🔴", "#4e0000", "#ef5350", "Volatile market — all strategies suppressed. No signals today."),
        MarketRegime.UNKNOWN:   ("⚪", "#1e1e2e", "#9ca3af", "Regime unknown (data fetch failed) — all strategies running as fallback."),
    }
    icon, bg, border, caption_text = _REGIME_CONFIG[regime]

    adx_str   = f"ADX {details.get('adx', '—')}" if details else ""
    atr_str   = f"ATR ratio {details.get('atr_ratio', '—')}×" if details else ""
    metric_str = f"  ·  {adx_str}  ·  {atr_str}" if adx_str else ""

    st.markdown(
        f"<div style='background:{bg};border:1px solid {border};border-radius:10px;"
        f"padding:14px 18px;margin-bottom:16px'>"
        f"<span style='font-size:1.1rem;font-weight:700;color:{border}'>"
        f"{icon} Market Regime: {regime.value}</span>"
        f"<span style='font-size:0.82rem;color:#9ca3af'>{metric_str}</span><br>"
        f"<span style='font-size:0.85rem;color:#c0c0d0'>{caption_text}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Show which strategies are active
    strategy_names  = ["ema_crossover", "rsi_macd_combo", "opening_range_breakout", "gap_and_go"]
    strategy_labels = {
        "ema_crossover":          "EMA Crossover",
        "rsi_macd_combo":         "RSI+MACD",
        "opening_range_breakout": "ORB",
        "gap_and_go":             "Gap & Go",
    }
    active   = [strategy_labels[s] for s in strategy_names if regime_allows_strategy(regime, s)]
    inactive = [strategy_labels[s] for s in strategy_names if not regime_allows_strategy(regime, s)]

    r1, r2 = st.columns(2)
    with r1:
        if active:
            st.success(f"Active: {', '.join(active)}")
    with r2:
        if inactive:
            st.warning(f"Suppressed: {', '.join(inactive)}")

    st.markdown("---")

    # ── Controls ──────────────────────────────────────────────────────
    col1, col2 = st.columns([2, 1])
    with col1:
        selected_strategies = st.multiselect(
            "Strategies to scan",
            ["EMA Crossover", "RSI+MACD Combo", "ORB", "Gap & Go"],
            default=["EMA Crossover", "RSI+MACD Combo", "ORB", "Gap & Go"],
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

    # ── Results table with confidence score ───────────────────────────
    rows = []
    for r in results:
        score = r.confidence_score
        dots  = "●" * score + "○" * (5 - score)
        tier  = "High" if score >= 4 else "Moderate" if score == 3 else "Low"
        rows.append({
            "Symbol":      r.symbol,
            "Strategy":    r.strategy,
            "Signal":      "🟢 BUY" if r.action == Action.BUY else "🔴 SELL",
            "Confidence":  f"{dots}  {score}/5  {tier}",
            "Entry ₹":     r.entry_price,
            "Stop Loss ₹": r.stop_loss,
            "Target ₹":    r.target,
            "RR Ratio":    f"{r.rr_ratio:.1f}x",
        })

    df_results = pd.DataFrame(rows)
    st.dataframe(df_results, use_container_width=True, hide_index=True)

    # ── Confidence score legend ───────────────────────────────────────
    with st.expander("What does the Confidence score mean?"):
        st.markdown("""
Each signal is rated **0–5** based on how many independent checks agree with the trade direction.
A signal can pass all strategy rules and still score 2/5 — meaning only 2 of 5 quality checks agree.

| Check | Description |
|---|---|
| Trend aligned | Price is above EMA50 for BUY, below EMA50 for SELL |
| Volume confirmed | Signal candle volume ≥ 1.5× the 20-candle average |
| VWAP aligned | Price above VWAP for BUY, below VWAP for SELL |
| RSI not extreme | RSI is in the neutral zone (30–70), not already at an extreme |
| MACD momentum | MACD line is above/below its signal line in the right direction |

**5/5 = High** → all factors align, best quality.
**3–4/5 = Moderate** → well-supported but one or two factors missing.
**0–2/5 = Low** → strategy fired but conditions are weak — be cautious.
        """)


    st.markdown("---")

    # ── Per-signal confidence breakdown ───────────────────────────────
    st.subheader("Signal Detail")
    chosen_signal_label = st.selectbox(
        "Inspect signal:",
        [f"{r.symbol} — {r.strategy} ({'BUY' if r.action == Action.BUY else 'SELL'})" for r in results],
    )
    chosen_idx = [
        f"{r.symbol} — {r.strategy} ({'BUY' if r.action == Action.BUY else 'SELL'})"
        for r in results
    ].index(chosen_signal_label)
    chosen_r = results[chosen_idx]

    score  = chosen_r.confidence_score
    checks = chosen_r.confidence_checks or {}

    # Score badge
    _score_colour = "#4caf50" if score >= 4 else "#ffc107" if score == 3 else "#ef5350"
    _score_label  = "High conviction" if score >= 4 else "Moderate" if score == 3 else "Low conviction"
    st.markdown(
        f"<div style='display:flex;align-items:center;gap:16px;margin:10px 0'>"
        f"<div style='background:#1a1d27;border:2px solid {_score_colour};border-radius:50%;width:64px;height:64px;"
        f"display:flex;align-items:center;justify-content:center;flex-shrink:0'>"
        f"<span style='font-size:1.4rem;font-weight:700;color:{_score_colour}'>{score}/5</span></div>"
        f"<div><div style='font-size:1rem;font-weight:600;color:{_score_colour}'>{_score_label}</div>"
        f"<div style='font-size:1.5rem;letter-spacing:4px'>{'●' * score}{'○' * (5 - score)}</div></div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Individual check breakdown
    if checks:
        for check_name, (passed, detail) in checks.items():
            icon   = "✅" if passed else "❌"
            colour = "#4caf50" if passed else "#6b7280"
            st.markdown(
                f"<div style='display:flex;gap:10px;padding:6px 0;border-bottom:1px solid #2a2d3e'>"
                f"<span style='font-size:1rem;flex-shrink:0'>{icon}</span>"
                f"<div><span style='font-weight:600;color:{colour};font-size:0.88rem'>{check_name}</span>"
                f"<br><span style='font-size:0.81rem;color:#9ca3af'>{detail}</span></div>"
                f"</div>",
                unsafe_allow_html=True,
            )

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
