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
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS — minimalist dark theme ───────────────────────────────
st.markdown("""
<style>
/* ── Base ── */
html, body, [data-testid="stAppViewContainer"] {
    background-color: #0e1116;
    color: #e5e7eb;
}
[data-testid="stHeader"] {
    background: rgba(14, 17, 22, 0.72);
    border-bottom: 1px solid #1f2937;
}

/* ── Metric cards ── */
[data-testid="metric-container"] {
    background: #121722;
    border: 1px solid #1f2937;
    border-radius: 8px;
    padding: 14px 16px 12px 16px;
}
[data-testid="stMetricLabel"]  { color: #9ca3af !important; font-size: 0.78rem; text-transform: uppercase; }
[data-testid="stMetricValue"]  { color: #f3f4f6 !important; font-size: 1.45rem; font-weight: 650; }
[data-testid="stMetricDelta"]  { font-size: 0.82rem; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #0b0e14 !important;
    border-right: 1px solid #1f2937;
}
[data-testid="stSidebar"] .stRadio label {
    color: #cbd5e1;
    font-size: 0.9rem;
    padding: 4px 0;
    cursor: pointer;
}
[data-testid="stSidebar"] .stRadio label:hover { color: #f8fafc; }
[data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label {
    border: 1px solid transparent;
    border-radius: 8px;
    margin-bottom: 4px;
    padding: 8px 10px;
}
[data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label:has(input:checked) {
    background: #111827;
    border-color: #334155;
}

/* ── DataFrames ── */
[data-testid="stDataFrame"] { border-radius: 8px; overflow: hidden; }
[data-testid="stDataFrame"] th {
    background: #111827 !important;
    color: #94a3b8 !important;
    font-size: 0.75rem;
    text-transform: uppercase;
}
[data-testid="stDataFrame"] td { background: #0f172a !important; color: #e2e8f0 !important; }

/* ── Buttons ── */
[data-testid="baseButton-primary"] {
    background: #2563eb !important;
    border: none !important;
    border-radius: 8px !important;
    color: #fff !important;
    font-weight: 650;
}
[data-testid="baseButton-primary"]:hover { background: #1d4ed8 !important; }
[data-testid="baseButton-secondary"] {
    background: #111827 !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
    color: #e2e8f0 !important;
}

/* ── Tabs ── */
[data-testid="stTabs"] button {
    color: #94a3b8 !important;
    font-weight: 500;
    border-radius: 8px 8px 0 0;
}
[data-testid="stTabs"] button[aria-selected="true"] {
    color: #f8fafc !important;
    border-bottom: 2px solid #2563eb !important;
}

/* ── Section divider ── */
hr { border-color: #334155 !important; margin: 1.1rem 0 !important; }

/* ── Expander ── */
[data-testid="stExpander"] {
    background: #111827;
    border: 1px solid #334155;
    border-radius: 8px;
}

/* ── Info / success / warning / error boxes ── */
[data-testid="stAlert"] { border-radius: 8px; }

/* ── Remove default top padding ── */
.block-container { padding-top: 1.25rem !important; }

/* ── Page title ── */
h1 { font-size: 1.58rem !important; font-weight: 700; color: #f8fafc; margin-bottom: 0.15rem; }
h2 { font-size: 1.16rem !important; font-weight: 620; color: #e2e8f0; }
h3 { font-size: 1rem !important; font-weight: 600; color: #cbd5e1; }
</style>
""", unsafe_allow_html=True)

# ── Sidebar navigation ────────────────────────────────────────────────
st.sidebar.markdown("## :material/query_stats: TreadingBot")
st.sidebar.caption("Indian Market · NSE · Paper")
st.sidebar.markdown("---")

_PAGES = [
    ("Home", ":material/home: Home"),
    ("Journal", ":material/menu_book: Journal"),
    ("Compare", ":material/compare_arrows: Compare"),
    ("Signals", ":material/radar: Signals"),
    ("Backtest", ":material/analytics: Backtest"),
    ("Replay", ":material/history: Replay"),
    ("Analysis", ":material/language: Analysis"),
    ("Fundamentals", ":material/finance: Fundamentals"),
    ("Bot Monitor", ":material/smart_toy: Bot Monitor"),
    ("Settings", ":material/settings: Settings"),
]

selected_label = st.sidebar.radio(
    "Navigation",
    [label for _, label in _PAGES],
    label_visibility="collapsed"
)
page = next(key for key, label in _PAGES if label == selected_label)

st.sidebar.markdown("---")
st.sidebar.markdown(":material/token: **Paper Trading**")
st.sidebar.markdown(":material/location_on: NSE India")
st.sidebar.markdown(":material/neurology: EMA · RSI+MACD · ORB · Gap&Go")

# ── Route to page ─────────────────────────────────────────────────────
if page == "Home":
    from dashboard.views.home import render
    render()
elif page == "Journal":
    from dashboard.views.journal import render
    render()
elif page == "Compare":
    from dashboard.views.comparison import render
    render()
elif page == "Signals":
    from dashboard.views.signals import render
    render()
elif page == "Backtest":
    from dashboard.views.backtest import render
    render()
elif page == "Replay":
    from dashboard.views.replay import render
    render()
elif page == "Analysis":
    from dashboard.views.analysis import render
    render()
elif page == "Fundamentals":
    from dashboard.views.fundamentals import render
    render()
elif page == "Bot Monitor":
    from dashboard.views.bot_control import render
    render()
elif page == "Settings":
    from dashboard.views.settings import render
    render()
