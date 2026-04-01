"""
Day Replay page — replay any past trading day candle-by-candle.

What is day replay?
  Backtesting runs months of data silently. Day replay runs a SINGLE past
  day through the exact same bot components — PaperBroker, RiskManager,
  OrderManager — candle by candle, so you can see every signal, rejection,
  and trade decision in detail.

  Use this to:
    - Understand why the bot did or didn't trade on a specific date
    - Test strategy parameter changes on a recent real market day
    - Verify a bug fix before the next live session

Results are saved to trades.db with trading_mode="replay" so they don't
appear on the Home page's live paper-trading dashboard.
"""

from __future__ import annotations

import datetime

import pandas as pd
import streamlit as st

from backtesting.day_replay import DayReplayEngine, NIFTY50_SYMBOLS
from config.settings import VIRTUAL_CAPITAL
from data.instruments import NIFTY50_INSTRUMENTS

_STRATEGY_OPTIONS = {
    "All strategies": None,
    "EMA Crossover":  "ema",
    "RSI+MACD Combo": "rsi",
    "Opening Range Breakout (ORB)": "orb",
}

# TradeLogger initialised once at module level (not inside render) to avoid
# repeated DB init on every Streamlit rerun.
from execution.trade_log import TradeLogger
_trade_log = TradeLogger()


def render() -> None:
    st.title("⏮ Day Replay")
    st.caption(
        "Replay any past trading day candle-by-candle through all strategies. "
        "Uses real historical 5-min candles from yfinance."
    )

    # ── Controls ──────────────────────────────────────────────────────
    today     = datetime.date.today()
    min_date  = today - datetime.timedelta(days=55)  # yfinance 5m limit
    yesterday = today - datetime.timedelta(days=1)

    col1, col2 = st.columns(2)

    with col1:
        replay_date = st.date_input(
            "Date to replay",
            value=yesterday,
            min_value=min_date,
            max_value=today,
            help="yfinance provides 5-minute data for the last ~55 days only.",
        )
        symbols = st.multiselect(
            "Symbols (NIFTY50)",
            options=NIFTY50_SYMBOLS,
            default=NIFTY50_SYMBOLS[:5],
            help="Select one or more NIFTY50 stocks.",
        )
        strategy_label = st.radio(
            "Strategy",
            options=list(_STRATEGY_OPTIONS.keys()),
            horizontal=True,
        )

    with col2:
        capital = st.number_input(
            "Starting capital (₹)",
            value=int(VIRTUAL_CAPITAL),
            step=10_000,
            min_value=10_000,
            help="Virtual capital used for position sizing during replay.",
        )
        st.info(
            "**How day replay works**\n\n"
            "The engine pre-fetches 5 days of 5-minute candles from yfinance. "
            "Prior-day candles are used as indicator warmup (MACD needs 35+ candles). "
            "Only the selected date's candles are replayed — no lookahead.\n\n"
            "Trades are saved with `trading_mode=replay` and won't appear "
            "on the Home page's live paper-trading dashboard."
        )

    run_btn = st.button("▶ Run Replay", type="primary")

    if not run_btn:
        return

    if not symbols:
        st.error("Please select at least one symbol.")
        return

    strategy_key = _STRATEGY_OPTIONS[strategy_label]
    date_str     = str(replay_date)

    # ── Run ───────────────────────────────────────────────────────────
    with st.spinner(f"Replaying {date_str} for {len(symbols)} symbol(s)…"):
        try:
            engine = DayReplayEngine(
                capital=float(capital),
                strategies=strategy_key,
                live_delay=0.0,
            )
            result = engine.run(symbols=symbols, replay_date=date_str)
        except ValueError as exc:
            st.error(f"Replay failed: {exc}")
            return

    st.session_state["replay_result"] = result

    # ── Metrics row ───────────────────────────────────────────────────
    net_pnl = result.net_pnl
    pnl_delta = f"{'▲' if net_pnl >= 0 else '▼'} ₹{abs(net_pnl):,.0f}"

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Starting Capital", f"₹{result.starting_capital:,.0f}")
    c2.metric("Final Cash",       f"₹{result.final_cash:,.0f}")
    c3.metric("Net P&L",          f"₹{net_pnl:+,.0f}",
              delta=pnl_delta,
              delta_color="normal" if net_pnl >= 0 else "inverse")
    c4.metric("Trades",           str(result.num_trades))
    c5.metric("Win Rate",         f"{result.win_rate_pct:.0f}%")

    # ── Trade log ─────────────────────────────────────────────────────
    st.subheader("📋 Trade Log")

    closed = [t for t in result.trades if t.get("exit_price")]
    if closed:
        rows = []
        for t in closed:
            rows.append({
                "Time In":   (t.get("timestamp") or "")[:16],
                "Symbol":    t.get("symbol", ""),
                "Strategy":  t.get("strategy", ""),
                "Action":    t.get("action", ""),
                "Entry ₹":   t.get("entry_price"),
                "Exit ₹":    t.get("exit_price"),
                "Time Out":  (t.get("exit_timestamp") or "")[:16],
                "P&L ₹":     round(t.get("net_pnl") or 0, 2),
                "Reason":    (t.get("reason") or "")[:60],
            })
        df_trades = pd.DataFrame(rows)
        st.dataframe(df_trades, use_container_width=True, hide_index=True)
    else:
        st.info("No completed trades on this replay day.")

    # ── Candle activity log ───────────────────────────────────────────
    st.subheader("📡 Candle Activity")
    st.caption(
        "Every signal evaluated, candle by candle. "
        "Filter to just the highlights using the event filter below."
    )

    if result.candle_log:
        all_events = sorted({e["event"] for e in result.candle_log})
        show_events = st.multiselect(
            "Show events",
            options=all_events,
            default=[e for e in all_events if e not in ("HOLD", "SKIP")],
            help="HOLD and SKIP are very frequent — hide them to focus on trades.",
        )

        filtered = [e for e in result.candle_log if e["event"] in show_events]

        if filtered:
            df_log = pd.DataFrame(filtered)

            # Colour-code rows
            def _row_colour(row: pd.Series) -> list[str]:
                ev = row["event"]
                if ev == "BUY":
                    bg = "background-color: rgba(0, 200, 100, 0.15)"
                elif ev in ("EXIT", "EXIT EOD"):
                    bg = "background-color: rgba(255, 100, 100, 0.15)"
                elif ev == "REJECTED":
                    bg = "background-color: rgba(255, 180, 0, 0.12)"
                elif ev in ("ERROR", "NO DATA"):
                    bg = "background-color: rgba(200, 0, 0, 0.20)"
                else:
                    bg = ""
                return [bg] * len(row)

            styled = df_log.style.apply(_row_colour, axis=1)
            st.dataframe(styled, use_container_width=True, hide_index=True)
        else:
            st.info("No events match the selected filter.")
    else:
        st.info("No candle activity recorded.")
