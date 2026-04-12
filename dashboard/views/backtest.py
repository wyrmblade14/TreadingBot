"""
Backtest page — run a strategy on historical data interactively.

What is backtesting? (beginner explanation)
  Backtesting means running your strategy on PAST price data to see how it
  WOULD HAVE performed. It answers: "If I had used this strategy from 2023
  to 2024, what would my P&L be?"

  Important: Past performance does NOT guarantee future results.
  But it does tell you if a strategy has ANY historical edge at all.

Controls:
  - Choose any NIFTY50 stock
  - Choose a strategy
  - Set date range and starting capital
  - Click Run — see equity curve and all metrics
"""

from __future__ import annotations

import streamlit as st

import pandas as pd
import plotly.graph_objects as go

from backtesting.engine import BacktestEngine
from backtesting.performance import calculate
from backtesting.portfolio_sim import PortfolioSimulator
from backtesting.report import generate_report
from backtesting.walk_forward import WalkForwardEngine
from data.instruments import NIFTY50_INSTRUMENTS
NIFTY50_SYMBOLS = [i.kite_symbol for i in NIFTY50_INSTRUMENTS]
from strategies.ema_crossover import EMACrossoverStrategy
from strategies.rsi_macd_combo import RSIMACDStrategy
from strategies.opening_range_breakout import ORBStrategy

_STRATEGY_MAP = {
    "EMA Crossover":  EMACrossoverStrategy,
    "RSI+MACD Combo": RSIMACDStrategy,
    "Opening Range Breakout (ORB)": ORBStrategy,
}


def render() -> None:
    st.title(":material/analytics: Backtest Runner")
    st.caption("Test any strategy on historical NIFTY50 data. No real money involved.")

    tab_single, tab_wf, tab_sim = st.tabs(
        ["Single Backtest", "Walk-Forward Analysis", "30-Day Simulation"]
    )

    with tab_single:
        _render_single_backtest()

    with tab_wf:
        _render_walk_forward()

    with tab_sim:
        _render_portfolio_sim()


def _render_single_backtest() -> None:
    # ── Controls ──────────────────────────────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        symbol   = st.selectbox("Stock symbol", NIFTY50_SYMBOLS, index=0)
        strategy = st.selectbox("Strategy",     list(_STRATEGY_MAP.keys()))
        capital  = st.number_input("Starting capital (₹)", value=100_000, step=10_000, min_value=10_000)
    with col2:
        start_date = st.date_input("Start date", value=st.session_state.get("bt_start", None) or
                                   __import__("datetime").date(2023, 1, 1))
        end_date   = st.date_input("End date",   value=st.session_state.get("bt_end", None) or
                                   __import__("datetime").date(2024, 12, 31))
        all_strats = st.checkbox("Run all strategies (compare)")

    run_btn = st.button(":material/play_arrow: Run Backtest", type="primary")

    if not run_btn:
        days = (end_date - start_date).days
        if days <= 55:
            interval_note = "5-minute candles (true intraday)"
        elif days <= 700:
            interval_note = "1-hour candles (intraday, yfinance 2-year limit)"
        else:
            interval_note = "daily candles (yfinance limit for very long ranges)"
        st.info(f"Configure the options above and click **Run Backtest**.\n\n"
                f"Selected range: **{days} days** → will use **{interval_note}**.")
        return

    if start_date >= end_date:
        st.error("Start date must be before end date.")
        return

    start_str = str(start_date)
    end_str   = str(end_date)

    strategies_to_run = list(_STRATEGY_MAP.items()) if all_strats else [(strategy, _STRATEGY_MAP[strategy])]

    for strat_name, StratClass in strategies_to_run:
        st.markdown(f"---\n### {strat_name} on {symbol}")

        with st.spinner(f"Running {strat_name} backtest..."):
            engine  = BacktestEngine(StratClass(), initial_capital=float(capital))
            result  = engine.run(symbol, start=start_str, end=end_str)
            metrics = calculate(result)

        if metrics.num_trades == 0:
            st.warning(f"No trades generated for {strat_name}. Try a longer date range.")
            continue

        # ── Metrics grid ──────────────────────────────────────────────
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Trades",  str(metrics.num_trades))
        c2.metric("Win Rate",      f"{metrics.win_rate_pct:.1f}%")
        c3.metric("Profit Factor", f"{metrics.profit_factor:.2f}")
        c4.metric("Net P&L",       f"₹{metrics.total_net_pnl:,.0f}")

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Sharpe Ratio",  f"{metrics.sharpe_ratio:.2f}")
        c6.metric("Max Drawdown",  f"{metrics.max_drawdown_pct:.1f}%")
        c7.metric("Total Return",  f"{metrics.total_return_pct:.1f}%")
        c8.metric("Final Capital", f"₹{metrics.final_capital:,.0f}")

        # ── Verdict ───────────────────────────────────────────────────
        verdict = metrics.verdict()
        if "Too few" in verdict:
            st.warning(f"**Verdict:** {verdict}")
        elif metrics.total_net_pnl > 0:
            st.success(f"**Verdict:** {verdict}")
        else:
            st.error(f"**Verdict:** {verdict}")

        # ── Equity curve with drawdown shading (inline) ───────────────
        if result.trades:
            equity = [float(capital)]
            times  = [result.trades[0].entry_time]
            for t in result.trades:
                equity.append(equity[-1] + t.net_pnl)
                times.append(t.exit_time)

            eq_series   = pd.Series(equity, index=times)
            peak_series = eq_series.cummax()

            fig = go.Figure()

            # Red shading between peak and equity (drawdown region)
            fig.add_trace(go.Scatter(
                x=list(times) + list(reversed(times)),
                y=list(peak_series) + list(reversed(equity)),
                fill="toself",
                fillcolor="rgba(220,50,50,0.15)",
                line=dict(width=0),
                name="Drawdown",
                showlegend=True,
            ))

            # Equity line on top
            fig.add_trace(go.Scatter(
                x=times, y=equity,
                mode="lines",
                line=dict(color="#2196F3", width=2),
                name="Portfolio Value",
            ))

            fig.update_layout(
                title=f"Equity Curve — {symbol} / {strat_name}",
                template="plotly_dark",
                height=380,
                yaxis_title="Portfolio Value (₹)",
                xaxis_title="Time",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig, use_container_width=True)

        # ── Full HTML report link ─────────────────────────────────────
        with st.spinner("Generating HTML report..."):
            report_path = generate_report(result, metrics)

        st.success(f"Full report saved → `{report_path}`")
        st.caption("Open the file in your browser for interactive charts with zoom, hover, and drawdown shading.")

        # ── Trade log table ───────────────────────────────────────────
        with st.expander(f"View all {metrics.num_trades} trades"):
            rows = []
            for t in result.trades:
                rows.append({
                    "Entry Time":  str(t.entry_time)[:16],
                    "Exit Time":   str(t.exit_time)[:16],
                    "Action":      t.action.value,
                    "Entry ₹":     t.entry_price,
                    "Exit ₹":      t.exit_price,
                    "Qty":         t.quantity,
                    "Net P&L ₹":   round(t.net_pnl, 2),
                    "Exit Reason": t.exit_reason,
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_walk_forward() -> None:
    st.subheader("Walk-Forward Analysis")
    st.caption(
        "Splits history into rolling train/test windows to check if the strategy "
        "is consistent across different market periods — not just lucky on one stretch."
    )

    with st.expander(":material/info: How to read this (beginner guide)", expanded=False):
        st.markdown("""
**Why walk-forward?**
A regular backtest might show great results on 2023 data — but that could be luck.
Walk-forward splits the full period into many smaller windows and tests each one separately.

**Example** with 6-month train + 2-month test:
- Window 1: "learns" Jan–Jun 2023, tested on Jul–Aug 2023
- Window 2: "learns" Mar–Aug 2023, tested on Sep–Oct 2023
- ...and so on.

**What to look for:**
- **Consistency ≥ 60%** — more than half the windows should be profitable
- **Avg win rate ≥ 45%** — average across all test windows
- If both pass → strategy is **robust** → safe to continue paper trading
- If both fail → strategy may be **curve-fitted** → do NOT go live
""")

    col1, col2 = st.columns(2)
    with col1:
        wf_symbol   = st.selectbox("Stock", NIFTY50_SYMBOLS, key="wf_symbol")
        wf_strategy = st.selectbox("Strategy", list(_STRATEGY_MAP.keys()), key="wf_strategy")
        wf_capital  = st.number_input("Capital (₹)", value=100_000, step=10_000,
                                      min_value=10_000, key="wf_capital")
    with col2:
        import datetime
        wf_start = st.date_input("Start date", value=datetime.date(2023, 1, 1), key="wf_start")
        wf_end   = st.date_input("End date",   value=datetime.date(2024, 12, 31), key="wf_end")
        wf_train = st.slider("Train window (months)", min_value=3, max_value=12, value=6, key="wf_train")
        wf_test  = st.slider("Test window (months)",  min_value=1, max_value=6,  value=2, key="wf_test")

    total_months = (wf_end.year - wf_start.year) * 12 + (wf_end.month - wf_start.month)
    est_windows  = max(0, (total_months - wf_train - wf_test) // wf_test + 1)
    st.caption(f"Estimated windows: **{est_windows}** | Total range: {total_months} months")

    if st.button(":material/play_arrow: Run Walk-Forward", type="primary"):
        if wf_start >= wf_end:
            st.error("Start date must be before end date.")
            return
        if total_months < wf_train + wf_test:
            st.error(f"Date range too short. Need at least {wf_train + wf_test} months.")
            return

        StratClass = _STRATEGY_MAP[wf_strategy]
        engine = WalkForwardEngine(
            StratClass(),
            train_months=wf_train,
            test_months=wf_test,
            initial_capital=float(wf_capital),
        )

        with st.spinner(f"Running {est_windows} windows..."):
            wf = engine.run(wf_symbol, start=str(wf_start), end=str(wf_end))

        if wf.num_windows == 0:
            st.warning("No windows generated. Try a wider date range.")
            return

        # ── Summary metrics ───────────────────────────────────────────
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Windows",      f"{wf.profitable_windows}/{wf.num_windows} profitable")
        c2.metric("Consistency",  f"{wf.consistency_pct:.0f}%",
                  delta="Pass" if wf.consistency_pct >= 60 else "Fail")
        c3.metric("Avg Win Rate", f"{wf.avg_win_rate:.1f}%",
                  delta="Pass" if wf.avg_win_rate >= 45 else "Fail")
        c4.metric("Total Trades", str(wf.total_trades))

        if wf.is_robust:
            st.success(f"**{wf.verdict()}**")
        else:
            st.warning(f"**{wf.verdict()}**")

        # ── Per-window bar chart ──────────────────────────────────────
        labels  = [w.label for w in wf.windows]
        returns = [w.metrics.total_return_pct for w in wf.windows]
        colours = ["#4CAF50" if r >= 0 else "#F44336" for r in returns]

        fig = go.Figure(go.Bar(
            x=labels, y=returns,
            marker_color=colours,
            text=[f"{r:+.1f}%" for r in returns],
            textposition="outside",
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.4)
        fig.update_layout(
            title="Return % per Test Window",
            template="plotly_dark",
            height=350,
            yaxis_title="Return %",
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

        # ── Per-window detail table ───────────────────────────────────
        with st.expander("Window-by-window detail"):
            rows = []
            for w in wf.windows:
                pf = w.metrics.profit_factor
                rows.append({
                    "Window":      w.label,
                    "Test Start":  str(w.test_start),
                    "Test End":    str(w.test_end),
                    "Trades":      w.metrics.num_trades,
                    "Win %":       f"{w.metrics.win_rate_pct:.1f}%",
                    "Profit Factor": f"{pf:.2f}" if pf != float("inf") else "∞",
                    "Return %":    f"{w.metrics.total_return_pct:+.1f}%",
                    "Net P&L ₹":   f"₹{w.metrics.total_net_pnl:,.0f}",
                    "Result":      "Profitable" if w.is_profitable else "Loss",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_portfolio_sim() -> None:
    """
    30-Day Portfolio Simulation tab.

    Runs ALL strategies across ALL selected symbols for the last N trading days,
    with shared capital and all risk rules. No DB writes — results are in-memory.
    """
    st.subheader("30-Day Portfolio Simulation")
    st.caption(
        "Replays the last N trading days through all strategies simultaneously, "
        "with shared capital (max 3 positions) and all 10 risk rules enforced. "
        "Capital carries forward each day. No real money involved."
    )

    col1, col2 = st.columns(2)

    with col1:
        trading_days = st.slider(
            "Trading days to simulate",
            min_value=5, max_value=40, value=30,
            help="yfinance provides ~55 days of 5-min data. 30 days = ~6 weeks.",
        )
        symbols = st.multiselect(
            "Symbols (NIFTY50)",
            options=NIFTY50_SYMBOLS,
            default=NIFTY50_SYMBOLS[:10],
            help="More symbols = slower but more realistic. Start with 10.",
        )
        strategy_opt = st.radio(
            "Strategies",
            ["All three", "EMA Crossover only", "RSI+MACD only", "ORB only"],
            horizontal=True,
        )

    with col2:
        capital = st.number_input(
            "Starting capital (₹)",
            value=100_000, step=10_000, min_value=10_000,
        )
        st.info(
            "**What this simulates**\n\n"
            "The bot runs candle-by-candle on each of the last N market days. "
            "All 3 strategies compete for the same 3 position slots. "
            "If the daily loss limit (-3%) fires, no new trades that day. "
            "All positions are squared off at 3:15 PM.\n\n"
            "This answers: *'Would this bot have made money recently?'*"
        )

    run_btn = st.button(":material/play_arrow: Run Simulation", type="primary", key="sim_run")
    if not run_btn:
        return

    if not symbols:
        st.error("Select at least one symbol.")
        return

    strat_key = {
        "All three":         None,
        "EMA Crossover only": "ema",
        "RSI+MACD only":      "rsi",
        "ORB only":           "orb",
    }[strategy_opt]

    with st.spinner(f"Simulating {trading_days} days × {len(symbols)} symbols…"):
        sim = PortfolioSimulator(
            capital=float(capital),
            trading_days=trading_days,
            strategies=strat_key,
        )
        result = sim.run(symbols=symbols)

    if not result.days:
        st.error("No trading days found. Try a different symbol set.")
        return

    # ── KPI row ───────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Net P&L",       f"₹{result.total_net_pnl:+,.0f}",
              delta=f"{result.total_return_pct:+.2f}%")
    c2.metric("Win Rate",      f"{result.win_rate_pct:.1f}%",
              delta="target >45%")
    c3.metric("Total Trades",  str(result.total_trades))
    c4.metric("Profitable Days", f"{result.profitable_days}/{len(result.days)}")
    c5.metric("Halted Days",   str(result.halted_days),
              delta="0 is ideal", delta_color="inverse")

    st.markdown("---")

    # ── Equity curve ──────────────────────────────────────────────────
    left, right = st.columns(2)

    with left:
        st.subheader("Equity Curve")
        equity = result.equity_curve
        day_labels = ["Start"] + [str(d.date) for d in result.days]

        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(
            x=day_labels, y=equity,
            mode="lines+markers",
            line=dict(color="#4f6ef7", width=2),
            fill="tozeroy",
            fillcolor="rgba(79,110,247,0.08)",
        ))
        fig_eq.add_hline(y=capital, line_dash="dot", line_color="#555")
        fig_eq.update_layout(
            template="plotly_dark", paper_bgcolor="#1a1d27", plot_bgcolor="#1a1d27",
            height=260, margin=dict(l=0, r=0, t=10, b=0),
            yaxis=dict(gridcolor="#2a2d3e", tickprefix="₹"),
            xaxis=dict(gridcolor="#2a2d3e", tickangle=-45),
            showlegend=False,
        )
        st.plotly_chart(fig_eq, use_container_width=True)

    with right:
        st.subheader("Daily P&L")
        days_with_trades = [d for d in result.days if d.num_trades > 0]
        if days_with_trades:
            dates  = [str(d.date) for d in days_with_trades]
            pnls   = [d.net_pnl for d in days_with_trades]
            colors = ["#4caf50" if p >= 0 else "#ef5350" for p in pnls]

            fig_bar = go.Figure(go.Bar(
                x=dates, y=pnls, marker_color=colors,
                text=[f"₹{p:+,.0f}" for p in pnls],
                textposition="outside", textfont=dict(size=9),
            ))
            fig_bar.add_hline(y=0, line_color="#555", line_width=1)
            fig_bar.update_layout(
                template="plotly_dark", paper_bgcolor="#1a1d27", plot_bgcolor="#1a1d27",
                height=260, margin=dict(l=0, r=0, t=10, b=0),
                yaxis=dict(gridcolor="#2a2d3e", tickprefix="₹"),
                xaxis=dict(gridcolor="#2a2d3e", tickangle=-45),
                showlegend=False,
            )
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info("No trading days with completed trades.")

    st.markdown("---")

    # ── Strategy breakdown ────────────────────────────────────────────
    breakdown = result.strategy_breakdown()
    if breakdown:
        st.subheader("Strategy Breakdown")
        rows = []
        for name, stats in sorted(breakdown.items(), key=lambda x: -x[1]["net_pnl"]):
            wr = round(100 * stats["wins"] / stats["trades"], 1) if stats["trades"] else 0
            rows.append({
                "Strategy": name,
                "Trades":   stats["trades"],
                "Wins":     stats["wins"],
                "Win %":    f"{wr:.1f}%",
                "Net P&L":  f"₹{stats['net_pnl']:+,.0f}",
                "Result":   "Positive" if stats["net_pnl"] > 0 else "Negative",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── Per-day table ─────────────────────────────────────────────────
    st.subheader("Day-by-Day Results")
    rows = []
    for day in result.days:
        rows.append({
            "Date":    str(day.date),
            "Trades":  day.num_trades,
            "Win %":   f"{day.win_rate_pct:.0f}%" if day.num_trades else "—",
            "Net P&L": f"₹{day.net_pnl:+,.0f}",
            "Capital": f"₹{day.capital_end:,.0f}",
            "Note":    "Halted" if day.halted else ("Profit" if day.net_pnl > 0 else ("Loss" if day.net_pnl < 0 else "Flat")),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
