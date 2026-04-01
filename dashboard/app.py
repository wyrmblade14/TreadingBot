"""
TreadingBot Dashboard — Streamlit multi-page app.

Run with:
    streamlit run dashboard/app.py
    # or:
    python scripts/run_dashboard.py

Pages:
    Home        — Portfolio P&L, today's trades, capital summary
    Signals     — Live signal scanner across NIFTY50
    Backtest    — Run backtests interactively, view HTML report
    Analysis    — Market overview, NIFTY breadth, top movers
    Settings    — Paper/live mode toggle, risk parameter viewer
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on path when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

st.set_page_config(
    page_title="TreadingBot",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS — dark modern theme ───────────────────────────────────
st.markdown("""
<style>
/* ── Base ── */
html, body, [data-testid="stAppViewContainer"] {
    background-color: #0f1117;
    color: #e0e0e0;
}

/* ── Metric cards ── */
[data-testid="metric-container"] {
    background: #1a1d27;
    border: 1px solid #2a2d3e;
    border-radius: 12px;
    padding: 18px 20px 14px 20px;
}
[data-testid="stMetricLabel"]  { color: #8b8fa8 !important; font-size: 0.78rem; letter-spacing: 0.05em; text-transform: uppercase; }
[data-testid="stMetricValue"]  { color: #ffffff !important; font-size: 1.5rem; font-weight: 700; }
[data-testid="stMetricDelta"]  { font-size: 0.82rem; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #0d0f18 !important;
    border-right: 1px solid #1e2030;
}
[data-testid="stSidebar"] .stRadio label {
    color: #9ca3af;
    font-size: 0.92rem;
    padding: 6px 0;
    cursor: pointer;
}
[data-testid="stSidebar"] .stRadio label:hover { color: #ffffff; }

/* ── DataFrames ── */
[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
[data-testid="stDataFrame"] th {
    background: #1a1d27 !important;
    color: #8b8fa8 !important;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
[data-testid="stDataFrame"] td { background: #13151f !important; color: #e0e0e0 !important; }

/* ── Buttons ── */
[data-testid="baseButton-primary"] {
    background: #4f6ef7 !important;
    border: none !important;
    border-radius: 8px !important;
    color: #fff !important;
    font-weight: 600;
}
[data-testid="baseButton-primary"]:hover { background: #3d5ae5 !important; }
[data-testid="baseButton-secondary"] {
    background: #1a1d27 !important;
    border: 1px solid #2a2d3e !important;
    border-radius: 8px !important;
    color: #e0e0e0 !important;
}

/* ── Tabs ── */
[data-testid="stTabs"] button {
    color: #8b8fa8 !important;
    font-weight: 500;
    border-radius: 6px 6px 0 0;
}
[data-testid="stTabs"] button[aria-selected="true"] {
    color: #ffffff !important;
    border-bottom: 2px solid #4f6ef7 !important;
}

/* ── Section divider ── */
hr { border-color: #2a2d3e !important; margin: 1.2rem 0 !important; }

/* ── Expander ── */
[data-testid="stExpander"] {
    background: #1a1d27;
    border: 1px solid #2a2d3e;
    border-radius: 10px;
}

/* ── Info / success / warning / error boxes ── */
[data-testid="stAlert"] { border-radius: 8px; }

/* ── Remove default top padding ── */
.block-container { padding-top: 1.5rem !important; }

/* ── Page title ── */
h1 { font-size: 1.6rem !important; font-weight: 700; color: #ffffff; margin-bottom: 0.2rem; }
h2 { font-size: 1.2rem !important; font-weight: 600; color: #e0e0e0; }
h3 { font-size: 1rem !important; font-weight: 600; color: #c0c0d0; }
</style>
""", unsafe_allow_html=True)

# ── Sidebar navigation ────────────────────────────────────────────────
st.sidebar.markdown("## 📈 TreadingBot")
st.sidebar.caption("Indian Market · NSE · Paper")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigate",
    ["🏠 Home", "📓 Journal", "⚔️ Compare", "🔍 Signals", "📊 Backtest", "⏮ Replay", "🌐 Analysis", "🤖 Bot Monitor", "⚙️ Settings"],
    label_visibility="collapsed",
)

st.sidebar.markdown("---")
st.sidebar.markdown("""
<div style='font-size:0.78rem;color:#6b7280;line-height:1.8'>
🟡 &nbsp;<b style='color:#e0e0e0'>Paper Trading</b><br>
📍 &nbsp;NSE India<br>
🧠 &nbsp;EMA · RSI+MACD · ORB · Gap&Go
</div>
""", unsafe_allow_html=True)

# ── Route to page ─────────────────────────────────────────────────────
if page == "🏠 Home":
    from dashboard.views.home import render
    render()
elif page == "📓 Journal":
    from dashboard.views.journal import render
    render()
elif page == "⚔️ Compare":
    from dashboard.views.comparison import render
    render()
elif page == "🔍 Signals":
    from dashboard.views.signals import render
    render()
elif page == "📊 Backtest":
    from dashboard.views.backtest import render
    render()
elif page == "⏮ Replay":
    from dashboard.views.replay import render
    render()
elif page == "🌐 Analysis":
    from dashboard.views.analysis import render
    render()
elif page == "🤖 Bot Monitor":
    from dashboard.views.bot_control import render
    render()
elif page == "⚙️ Settings":
    from dashboard.views.settings import render
    render()
