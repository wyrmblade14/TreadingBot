"""
Global configuration for the TradingBot.

All market hours, risk rules, and brokerage cost constants live here.
Change TRADING_MODE from "paper" to "live" when you're ready to trade
with real money (only after 30+ days of successful paper trading).

Indian market context:
  - NSE (National Stock Exchange) is the primary exchange
  - Market hours: 9:15 AM – 3:30 PM IST, Monday–Friday
  - We trade only NIFTY50 stocks (most liquid, hardest to manipulate)
  - We trade only the cash (equity) segment — NOT futures or options
"""

import os
from datetime import time

import pytz
from dotenv import load_dotenv

load_dotenv()

# ── Timezone ──────────────────────────────────────────────────────────
IST = pytz.timezone("Asia/Kolkata")

# ── Market Hours (IST) ────────────────────────────────────────────────
# These are enforced by both the scheduler and the paper/live brokers.
PRE_MARKET_START    = time(9, 0)    # Pre-market session starts
MARKET_OPEN         = time(9, 15)   # Regular session opens
ORB_END_TIME        = time(9, 30)   # End of Opening Range (first 15 min)
NO_NEW_ENTRIES_TIME = time(14, 30)  # Stop opening new positions after this
SQUAREOFF_TIME      = time(15, 15)  # Force-close ALL positions by this time
MARKET_CLOSE        = time(15, 30)  # Market closes

# No trading in the first 5 minutes (9:15–9:20) — opening auction is chaotic
FIRST_CANDLE_BLACKOUT = time(9, 20)

# ── Broker / API ──────────────────────────────────────────────────────
KITE_API_KEY      = os.getenv("KITE_API_KEY", "")
KITE_API_SECRET   = os.getenv("KITE_API_SECRET", "")
KITE_ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN", "")

# ── Telegram Notifications ────────────────────────────────────────────
# Optional: get trade alerts on your phone.
# Setup: create a bot via @BotFather in Telegram, then add to .env:
#   TELEGRAM_BOT_TOKEN=123456:ABC-yourtoken
#   TELEGRAM_CHAT_ID=987654321
# Leave blank to disable (bot still works, just no phone alerts).
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Trading Mode ──────────────────────────────────────────────────────
# "paper" = simulated trading (safe, no real money at risk)
# "live"  = real orders sent to Zerodha (use with extreme caution)
TRADING_MODE = os.getenv("TRADING_MODE", "paper")

# ── Capital ───────────────────────────────────────────────────────────
VIRTUAL_CAPITAL = float(os.getenv("VIRTUAL_CAPITAL", "100000"))  # ₹1,00,000

# ── Risk Management Rules ─────────────────────────────────────────────
# These values are HARDCODED safety limits.
# Do NOT increase them until you have at least 3 months of profitable trading.
RISK_PER_TRADE_PCT   = 0.01   # Max 1% of capital at risk per trade
MAX_DAILY_LOSS_PCT   = 0.03   # Halt all trading if day's loss exceeds 3%
MAX_OPEN_POSITIONS   = 3      # Never hold more than 3 stocks at once
MIN_REWARD_RISK_RATIO = 2.0   # Target must be at least 2× the stop-loss distance
MAX_CONSECUTIVE_LOSSES = 3    # Pause for 1 hour after 3 losses in a row
MAX_POSITION_PCT       = 0.30 # Max 30% of capital margin in any single trade
INTRADAY_LEVERAGE      = 5    # Zerodha MIS 5x leverage: only 20% margin needed
SHORT_SELLING_ENABLED  = True  # NSE MIS intraday short selling is legal; False = long-only

# ── Strategy Parameters ───────────────────────────────────────────────
# EMA (Exponential Moving Average)
# Think of EMA as a smoothed price trend line.
# When the short EMA (fast) crosses above the long EMA (slow), it signals upward momentum.
EMA_SHORT_PERIOD  = 9    # Fast EMA — reacts quickly to price changes
EMA_LONG_PERIOD   = 21   # Slow EMA — smoother, filters out noise
EMA_TREND_PERIOD  = 50   # Trend filter — price above this = uptrend

# RSI (Relative Strength Index) — measures how overbought or oversold a stock is
# Scale: 0–100. Below 30 = oversold (potentially cheap). Above 70 = overbought (potentially expensive).
RSI_PERIOD     = 14
RSI_OVERSOLD   = 30   # Buy signal zone
RSI_OVERBOUGHT = 70   # Sell signal zone

# MACD (Moving Average Convergence Divergence) — measures momentum and trend direction
MACD_FAST   = 12   # Fast EMA period
MACD_SLOW   = 26   # Slow EMA period
MACD_SIGNAL = 9    # Signal line period

# Volume confirmation: signal candle volume must be this many times the average
VOLUME_CONFIRMATION_MULTIPLIER = 1.5

# ── Candle Timeframe ──────────────────────────────────────────────────
# We use 5-minute candles as our primary trading timeframe.
# Each "candle" represents the open, high, low, close, volume for a 5-min window.
CANDLE_INTERVAL = "5minute"   # Used with Kite Connect API
YFINANCE_INTERVAL = "5m"      # Same thing, yfinance format

# ── Exchange ──────────────────────────────────────────────────────────
PRIMARY_EXCHANGE = "NSE"

# ── Zerodha Brokerage Costs (for paper trading simulation) ───────────
# These are the actual charges Zerodha applies on intraday equity trades.
# The paper broker deducts these so your paper P&L reflects real costs.
BROKERAGE_PER_ORDER        = 20.0       # ₹20 flat per executed order
STT_INTRADAY_SELL          = 0.00025    # 0.025% on sell-side turnover
EXCHANGE_TRANSACTION_CHARGE = 0.0000325 # 0.00325% on total turnover
GST_RATE                   = 0.18       # 18% GST on (brokerage + exchange charges)
SEBI_CHARGES_PER_CRORE     = 10.0       # ₹10 per ₹1 crore traded
STAMP_DUTY_BUY             = 0.00003    # 0.003% on buy-side turnover

# ── Slippage Simulation ───────────────────────────────────────────────
# In real markets, you never get the exact last-traded price when placing orders.
# Market orders fill slightly worse than the displayed price.
SLIPPAGE_PCT = 0.001  # 0.1% slippage on market orders (both buy and sell)

# ── Partial Fill Simulation ───────────────────────────────────────────
# In real markets, large orders "sweep" through multiple price levels in the
# order book before fully filling — each successive lot fills at a slightly
# worse price. This is called a partial fill or market impact.
#
# For NIFTY50 stocks at ₹1 lakh capital, most orders are small (< 50 shares)
# and will always fill completely. This simulation only kicks in for larger
# orders where market impact is realistic.
PARTIAL_FILL_ENABLED     = True    # Set False to revert to single-price fill
PARTIAL_FILL_THRESHOLD   = 50      # Orders above this share count may sweep 2 lots
PARTIAL_FILL_PROBABILITY = 0.25    # 25% chance of 2-lot fill when above threshold

# ── Strategy Degradation Detection ───────────────────────────────────
# Expected win rates based on backtesting (used as baseline for health checks).
# If the rolling 20-trade win rate drops more than DEGRADATION_THRESHOLD_PCT
# below the baseline, the strategy is flagged as degraded.
STRATEGY_BASELINES: dict[str, float] = {
    "ema_crossover":          50.0,   # % expected win rate
    "rsi_macd_combo":         45.0,
    "opening_range_breakout": 50.0,
}
DEGRADATION_THRESHOLD_PCT = 15.0   # alert if win rate drops >15% below baseline
DEGRADATION_MIN_TRADES    = 10     # skip alert until at least this many trades logged
