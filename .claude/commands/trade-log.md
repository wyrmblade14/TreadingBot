Show a summary of the TreadingBot's trade history from the SQLite database.

Steps:
1. Check if `logs/trades.db` exists. If not, tell the user no trades have been logged yet (the bot needs to run first).
2. If it exists, run a Python one-liner to print:
   - Today's trades (symbol, action, entry/exit price, P&L)
   - Today's total P&L and win rate
   - Per-strategy summary (total trades, win rate, net P&L)
3. Use this command to query:
   ```
   source venv/bin/activate && python -c "
   from execution.trade_log import TradeLogger
   log = TradeLogger()
   print('=== TODAY\\'S TRADES ===')
   for t in log.get_today_trades(): print(t)
   print()
   print('=== STRATEGY SUMMARY ===')
   for s in log.get_strategy_summary(): print(s)
   print()
   print('=== DAILY P&L ===')
   for d in log.get_daily_pnl()[:7]: print(d)
   "
   ```
4. Format the output cleanly and explain any notable patterns (e.g. "EMA Crossover has a higher win rate but fewer trades than ORB").
5. For a beginner, explain what the numbers mean — e.g. what win rate is good, what Sharpe ratio means.
