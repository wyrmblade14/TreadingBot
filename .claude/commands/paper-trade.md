Start or explain the TreadingBot paper trading session.

Paper trading = running the bot with simulated (virtual) money on real market data.
This is the safe way to test before using real money.

Steps:
1. Check `config/settings.py` to confirm `TRADING_MODE` is set to `"paper"`.
2. Check if `scripts/run_bot.py` exists. If not, Phase 6 (Live Kite Integration) has not been built yet — explain this and describe what the bot will do when it is built.
3. If `run_bot.py` exists:
   - Remind the user: paper trading uses ₹1,00,000 virtual capital by default (set in `.env`)
   - Run: `source venv/bin/activate && python scripts/run_bot.py`
4. Explain what happens during a paper trading session:
   - 9:00 AM: Bot starts, downloads overnight data
   - 9:15 AM: Market opens, bot begins scanning NIFTY50 for signals
   - 9:20 AM: First trades may be placed (blackout period ends)
   - Every 5 min: New candles processed, signals generated, exits checked
   - 2:30 PM: No new positions opened
   - 3:15 PM: All positions force-closed
   - 3:30 PM: Daily P&L report generated
5. Tell the user to use `/trade-log` to review results after the session.
