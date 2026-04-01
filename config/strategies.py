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
    },
    "rsi_macd_combo": {
        "enabled": True,
        "name": "RSI + MACD Combo",
        "description": (
            "Buys when MACD crosses up AND RSI is in the neutral zone (40–60), "
            "avoiding entries into already-overbought stocks. Sells when MACD "
            "crosses back down or RSI reaches 75."
        ),
        "rsi_period": 14,
        "rsi_buy_min": 40,    # RSI must be above this to enter (not oversold chase)
        "rsi_buy_max": 60,    # RSI must be below this to enter (not overbought)
        "rsi_exit": 75,       # Exit if RSI hits this level (overbought exit)
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
    },
    "opening_range_breakout": {
        "enabled": True,
        "name": "Opening Range Breakout (ORB)",
        "description": (
            "Captures the breakout from the first 15-minute price range (9:15–9:30 AM). "
            "Very popular strategy in Indian intraday markets. Supertrend filter ensures "
            "breakouts align with the day's underlying trend direction."
        ),
        "orb_duration_minutes": 15,   # Opening range window: 9:15–9:30 AM
        "volume_multiplier": 1.5,      # Breakout candle must have 1.5× avg volume
        "exit_time": "14:30",          # Exit all ORB positions by 2:30 PM
        "supertrend_period": 10,       # ATR lookback for Supertrend
        "supertrend_multiplier": 3.0,  # Band width multiplier
    },
}

# List of active strategies (used by the bot's strategy runner)
ACTIVE_STRATEGIES: list[str] = [
    name for name, cfg in STRATEGY_CONFIGS.items() if cfg.get("enabled", False)
]
