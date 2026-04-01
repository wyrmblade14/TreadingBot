"""
Strategy configuration registry.

Each strategy is a dict of parameters that can be overridden without
touching the strategy code itself. The dashboard settings page reads
and writes these values at runtime.
"""

STRATEGY_CONFIGS: dict = {
    "ema_crossover": {
        "enabled": True,
        "name": "EMA Crossover",
        "description": (
            "Buys when the fast EMA (9-period) crosses above the slow EMA (21-period) "
            "while Supertrend confirms bullish trend. Volume filter applied. "
            "Simple and effective for trending intraday markets."
        ),
        "short_period": 9,
        "long_period": 21,
        "trend_period": 50,         # Still computed for reference; Supertrend is the active filter
        "volume_multiplier": 1.5,   # Volume on signal candle must be 1.5× the 20-bar avg
        "supertrend_period": 10,    # ATR lookback for Supertrend band calculation
        "supertrend_multiplier": 3.0,  # Band width = multiplier × ATR (wider = fewer signals)
        "use_first_candle_filter": True,  # Only BUY above 9:15 candle high, SELL below its low
    },
    "rsi_macd_combo": {
        "enabled": True,
        "name": "RSI + MACD Combo",
        "description": (
            "Buys when MACD crosses up AND RSI is in the neutral zone (35–65), "
            "avoiding entries into already-overbought stocks. Sells when MACD "
            "crosses back down or RSI reaches 80."
        ),
        "rsi_period": 6,      # RSI(6) for intraday — responds to last 30 min, not 70 min
        "rsi_buy_min": 35,    # RSI must be above this to enter (wider zone for faster RSI)
        "rsi_buy_max": 65,    # RSI must be below this to enter
        "rsi_exit": 80,       # Exit if RSI hits this level (RSI(6) can spike to 90+)
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
    },
    "opening_range_breakout": {
        "enabled": True,
        "name": "Opening Range Breakout (ORB)",
        "description": (
            "Captures the breakout from the first 30-minute price range (9:15–9:45 AM). "
            "Very popular strategy in Indian intraday markets. Supertrend filter ensures "
            "breakouts align with the day's underlying trend direction."
        ),
        "orb_duration_minutes": 30,   # Opening range window: 9:15–9:45 AM (30 min settles chaos)
        "volume_multiplier": 1.5,      # Breakout candle must have 1.5× avg volume
        "exit_time": "14:30",          # Exit all ORB positions by 2:30 PM
        "supertrend_period": 10,       # ATR lookback for Supertrend
        "supertrend_multiplier": 3.0,  # Band width multiplier
    },
    "gap_and_go": {
        "enabled": True,
        "name": "Gap & Go",
        "description": (
            "Trades stocks that open with a significant upward gap (≥0.5% above "
            "yesterday's close) and continue higher with a volume surge in the first "
            "15 minutes. Long-only, morning-only (before 11 AM). VWAP filter confirms "
            "institutional participation. Stop at yesterday's close — if the gap fills, "
            "the thesis is broken."
        ),
        "gap_min_pct": 0.5,           # Minimum gap size in % (0.5% = 50 basis points)
        "volume_multiplier": 1.5,      # Breakout candle must have 1.5× avg volume
        "exit_time": "11:00",          # No new Gap & Go entries after 11:00 AM
    },
    "bb_mean_reversion": {
        "enabled": True,
        "name": "Bollinger Band Mean Reversion",
        "description": (
            "Buys when price touches the lower Bollinger Band and RSI < 35 (oversold). "
            "Sells when price touches the upper band and RSI > 65 (overbought). "
            "Targets the middle band (20-period SMA). Counter-trend — works in ranging "
            "markets where momentum strategies struggle."
        ),
        "bb_period": 20,          # SMA window for the middle band
        "bb_std_dev": 2.0,        # Band width: middle ± (2.0 × std dev) covers ~95% of prices
        "rsi_period": 6,          # RSI(6) for intraday — faster signal
        "rsi_oversold": 25,       # Stricter: RSI(6) hits 35 often; 25 = genuinely oversold
        "rsi_overbought": 75,     # Stricter: RSI(6) hits 65 often; 75 = genuinely overbought
    },
}

# List of active strategies (used by the bot's strategy runner)
ACTIVE_STRATEGIES: list[str] = [
    name for name, cfg in STRATEGY_CONFIGS.items() if cfg.get("enabled", False)
]
