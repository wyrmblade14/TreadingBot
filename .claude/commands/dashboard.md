Launch the TreadingBot Streamlit dashboard.

Steps:
1. Check if `dashboard/app.py` exists. If not, let the user know Phase 5 (Dashboard) has not been built yet and offer to build it.
2. If it exists:
   - Activate venv: `source venv/bin/activate`
   - Run: `streamlit run dashboard/app.py`
3. Tell the user to open http://localhost:8501 in their browser.
4. Explain briefly what each page shows:
   - Home: current P&L, open positions, recent trades
   - Signals: live signal scanner for all NIFTY50 stocks
   - Backtest: run and view backtests interactively
   - Analysis: NIFTY market overview, sector heatmap
   - Settings: switch between paper/live mode, adjust risk parameters
