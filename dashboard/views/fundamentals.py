"""
Fundamentals page — fundamental health analysis for all NIFTY50 stocks.

What is fundamental analysis?
  Fundamental analysis looks at a company's *financial health* — its profits,
  debt, and growth — rather than just its price chart (which is "technical"
  analysis). Think of it as asking: "Is this business in good shape?"

Why does this matter for intraday trading?
  Even though you're buying and selling within a single day, the company's
  fundamentals still affect your trade:

  1. Earnings blackout windows — companies are most volatile in the 3 days
     BEFORE and 1 day AFTER earnings results. We flag those stocks so you know
     to expect big unexpected moves.

  2. Earnings trend — if a company's profits have been shrinking for several
     quarters, institutions (big funds) may be quietly selling. That makes BUY
     signals in that stock riskier — the underlying current is against you.

  3. Valuation context — a stock with a very high P/E (price-to-earnings ratio)
     is priced for perfection. Any bad news can drop it 5–10% instantly. Knowing
     this helps you size your position more conservatively.

  This page scores each NIFTY50 stock across 5 checks (out of 5) using
  sector-relative comparisons (e.g., is TCS cheaper than other IT stocks?).
  It does NOT tell you which stocks to buy — only which ones have a stronger
  or weaker fundamental backdrop.

Data source: yfinance (free, no API key). Cached for 24 hours.
"""

from __future__ import annotations

import streamlit as st
import pandas as pd

from data.fundamentals import fundamentals_cache
from analysis.fundamental_filter import score_fundamentals, FundamentalScore
from data.instruments import NIFTY50_INSTRUMENTS, SYMBOL_TO_SECTOR


def render() -> None:
    st.title(":material/finance: Fundamentals")
    st.caption(
        "Sector-relative fundamental health for all NIFTY50 stocks. "
        "Data from yfinance — cached 24 hours."
    )

    refresh = st.button(":material/refresh: Refresh", type="primary")

    # ── Today's Catalysts ─────────────────────────────────────────────
    # Show corporate announcements and news catalysts from yesterday so
    # you can see at a glance which stocks have bullish or bearish events.
    st.markdown("---")
    st.subheader(":material/newspaper: Today's Pre-Market Catalysts")
    st.caption(
        "Corporate announcements and news from yesterday that may move "
        "individual stocks today. The bot automatically skips BUY signals on "
        "BEARISH catalyst stocks (and SELL signals on BULLISH ones) when "
        "confidence ≥ 70%."
    )

    if refresh and "catalyst_summary" in st.session_state:
        del st.session_state["catalyst_summary"]

    if "catalyst_summary" not in st.session_state:
        with st.spinner("Scanning news and NSE announcements..."):
            try:
                from analysis.catalyst_scanner import scan_all_catalysts
                _summary = scan_all_catalysts()
                st.session_state["catalyst_summary"] = _summary
            except Exception as _exc:
                st.warning(f"Catalyst scan unavailable: {_exc}")
                st.session_state["catalyst_summary"] = None

    _cat = st.session_state.get("catalyst_summary")
    if _cat is not None:
        bull_count = len(_cat.bullish)
        bear_count = len(_cat.bearish)
        c1, c2, c3 = st.columns(3)
        c1.metric("Bullish Catalysts", bull_count)
        c2.metric("Bearish Catalysts", bear_count)
        c3.metric("Scanned", _cat.total)

        if _cat.bullish or _cat.bearish:
            _rows = []
            for r in _cat.bullish:
                _rows.append({
                    "Symbol": r.symbol, "Direction": "BULLISH",
                    "Reason": r.reason, "Confidence": f"{r.confidence:.0%}",
                    "Source": r.source,
                })
            for r in _cat.bearish:
                _rows.append({
                    "Symbol": r.symbol, "Direction": "BEARISH",
                    "Reason": r.reason, "Confidence": f"{r.confidence:.0%}",
                    "Source": r.source,
                })
            st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No significant catalysts found for today's watchlist.")

    # ── Clear cache on Refresh ────────────────────────────────────────
    if refresh and "fundamentals_table" in st.session_state:
        del st.session_state["fundamentals_table"]

    # ── Build / retrieve the table ────────────────────────────────────
    if "fundamentals_table" not in st.session_state:
        rows = []
        with st.spinner("Loading fundamentals for 50 stocks — this takes ~30 seconds on first load..."):
            for inst in NIFTY50_INSTRUMENTS:
                try:
                    fs: FundamentalScore = score_fundamentals(inst.kite_symbol)
                    trend = fundamentals_cache.get_quarterly_earnings_trend(inst.kite_symbol)
                    earnings_date = fundamentals_cache.get_earnings_calendar(inst.kite_symbol)
                    blackout = fundamentals_cache.is_earnings_blackout(inst.kite_symbol)

                    checks = fs.checks
                    rows.append({
                        "Symbol": inst.kite_symbol,
                        "Sector": inst.sector,
                        "Fund. Score": f"{fs.score}/5",
                        "Rating": fs.label,
                        "P/E Check": "Pass" if checks.get("P/E vs sector", (False,))[0] else "Fail",
                        "Debt Check": "Pass" if checks.get("Debt vs sector", (False,))[0] else "Fail",
                        "Margin Check": "Pass" if checks.get("Profit margin vs sector", (False,))[0] else "Fail",
                        "Book Check": "Pass" if checks.get("Price/Book vs sector", (False,))[0] else "Fail",
                        "Earnings Trend": trend,
                        "Next Earnings": str(earnings_date) if earnings_date else "—",
                        "Blackout": "Yes" if blackout else "—",
                        "_score": fs.score,  # hidden sort key
                    })
                except Exception:
                    continue

        df = (
            pd.DataFrame(rows)
            .sort_values("_score", ascending=False)
            .drop(columns=["_score"])
            .reset_index(drop=True)
        )
        st.session_state["fundamentals_table"] = df
    else:
        df = st.session_state["fundamentals_table"]

    if df.empty:
        st.error("Could not load fundamental data. Check your internet connection and try Refresh.")
        return

    # ── Summary metrics row ───────────────────────────────────────────
    st.markdown("---")

    total_stocks   = len(df)
    avg_score      = pd.to_numeric(df["Fund. Score"].astype(str).str.split("/").str[0], errors="coerce").mean()
    improving_count = (df["Earnings Trend"] == "IMPROVING").sum()
    blackout_count  = (df["Blackout"] == "Yes").sum()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Stocks Analysed",          f"{total_stocks}")
    col2.metric("Avg Fundamental Score",    f"{avg_score:.1f} / 5")
    col3.metric("Improving Earnings",       f"{improving_count}")
    col4.metric("Earnings Blackout",     f"{blackout_count}")

    st.markdown("---")

    # ── Main table ────────────────────────────────────────────────────
    st.subheader("All NIFTY50 Stocks — Fundamental Scorecard")

    # Colour hint for beginners
    st.caption(
        "**Fund. Score** = checks passed out of 5. "
        "Higher score = stronger fundamentals vs sector peers. "
        "**Blackout** = earnings result in next 3 days or 1 day ago — expect high volatility."
    )

    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── AI Analysis expander ──────────────────────────────────────────
    with st.expander(":material/smart_toy: AI Fundamental Analysis (single stock)"):
        st.caption(
            "Select a stock and click **Get AI Analysis** to get a full breakdown. "
            "If ANTHROPIC_API_KEY is set in your .env, Claude AI will analyse it. "
            "Otherwise a rule-based summary is shown. Results are cached 24 hours."
        )

        selected = st.selectbox(
            "Select stock",
            [i.kite_symbol for i in NIFTY50_INSTRUMENTS],
            key="fundamentals_selectbox",
        )

        if st.button("Get AI Analysis", key="ai_btn"):
            from analysis.fundamental_analyst import analyst

            with st.spinner(f"Analysing {selected}..."):
                metrics = fundamentals_cache.get_fundamentals(selected)
                judgment = analyst.analyze(selected, metrics)

            col1, col2, col3 = st.columns(3)
            col1.metric("Bias",           judgment.bias)
            col2.metric("Confidence",     f"{judgment.confidence:.0%}")
            col3.metric("Position Scale", f"{judgment.position_scale:.0%} of normal")

            st.markdown("")  # breathing room

            col_l, col_r = st.columns(2)

            col_l.markdown("**Strengths**")
            for s in judgment.key_strengths:
                col_l.markdown(f"• {s}")

            col_r.markdown("**Risks**")
            for r in judgment.key_risks:
                col_r.markdown(f"• {r}")

            st.info(judgment.summary)
            st.caption(f"Source: {judgment.source}")
