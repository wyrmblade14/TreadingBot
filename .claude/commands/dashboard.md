Launch the TreadingBot Next.js dashboard.

Steps:
1. Check that `web/package.json` exists and `web/node_modules/` is present.
   - If `node_modules` is missing, run: `cd web && npm install`
2. Start the dashboard:
   - Run: `cd web && npm run dev`
3. Tell the user to open http://localhost:3000 in their browser.
4. Explain briefly what each page shows:
   - Overview (/): Portfolio KPIs, equity curve, daily P&L, open positions panel
   - Trades (/trades): Today's open/closed trades + recent journal entries
   - History (/history): Complete trade history table
   - Strategies (/strategies): Win rate and net P&L per strategy
   - Market (/market): NIFTY 50 price, breadth, top gainers/losers
   - Bot Monitor (/monitor): Bot process status, mode, uptime
   - Logs (/logs): Last 200 lines of the bot session log

Note: The Python API server must be running for live data.
Start it with: `python dashboard/api/server.py`
