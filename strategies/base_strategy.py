"""
Base strategy class and Signal dataclass.

Every trading strategy produces a "Signal" — a structured decision that says:
  - What to do: BUY, SELL, or HOLD (do nothing)
  - For which stock
  - At what price to enter
  - Where to put the stop-loss (max loss if trade goes wrong)
  - What the profit target is

Think of a Signal like a trade ticket that gets handed to the Risk Manager
for approval before the Order Manager acts on it.

Workflow:
  Strategy → Signal → Risk Manager → (approved) → Order Manager → Broker
                                   → (rejected) → logged and discarded

Key concepts:
  Stop-loss: A price level where you exit a losing trade automatically.
             E.g. if you buy at ₹100 and set stop-loss at ₹95, the bot
             exits if price drops to ₹95 — limiting your loss to ₹5/share.

  Target:    The price level where you book profit.
             E.g. if stop-loss risk is ₹5, target should be ₹110 (₹10 profit)
             to maintain the 2:1 reward-to-risk ratio.

  ATR:       Average True Range — a measure of how much a stock typically
             moves in a given period. Used to set stop-losses at a "natural"
             distance that accounts for normal price noise.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import pandas as pd


class Action(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Signal:
    """
    Represents a trade decision produced by a strategy.

    Fields:
        symbol:      Stock symbol, e.g. "RELIANCE"
        action:      BUY, SELL, or HOLD
        entry_price: Suggested entry price (usually current market price)
        stop_loss:   Price at which to cut loss and exit
        target:      Price at which to book profit
        quantity:    Number of shares (filled in by PositionSizer)
        strategy:    Name of the strategy that generated this signal
        timestamp:   When the signal was generated
        reason:      Human-readable explanation (helpful for reviewing trades)
    """
    symbol:      str
    action:      Action
    entry_price: float
    stop_loss:   float
    target:      float
    quantity:    int            = 0      # Set by PositionSizer after Signal is created
    strategy:    str            = ""
    timestamp:   datetime       = field(default_factory=datetime.now)
    reason:      str            = ""
    # Phase A self-learning: indicator snapshot attached by job_runner before execute_signal()
    # Keys: rsi, ema_spread, vwap_dev, volume_ratio, macd_hist, atr_pct (see learning/feature_store.py)
    features:    Optional[dict] = field(default=None, repr=False, compare=False)

    @property
    def risk_per_share(self) -> float:
        """How much you lose per share if stop-loss is hit."""
        return abs(self.entry_price - self.stop_loss)

    @property
    def reward_per_share(self) -> float:
        """How much you gain per share if target is hit."""
        return abs(self.target - self.entry_price)

    @property
    def reward_risk_ratio(self) -> float:
        """
        Reward-to-risk ratio.
        A ratio of 2.0 means you stand to gain ₹2 for every ₹1 you risk.
        We require a minimum of 2.0 before taking any trade.
        """
        if self.risk_per_share == 0:
            return 0.0
        return self.reward_per_share / self.risk_per_share

    @property
    def total_risk(self) -> float:
        """Total money at risk on this trade = risk_per_share × quantity."""
        return self.risk_per_share * self.quantity

    def is_valid(self) -> bool:
        """Basic sanity checks on the signal values."""
        if self.action == Action.HOLD:
            return True
        if self.entry_price <= 0 or self.stop_loss <= 0 or self.target <= 0:
            return False
        if self.action == Action.BUY:
            return self.stop_loss < self.entry_price < self.target
        if self.action == Action.SELL:
            return self.target < self.entry_price < self.stop_loss
        return False

    def __str__(self) -> str:
        return (
            f"[{self.strategy}] {self.action.value} {self.symbol} "
            f"entry={self.entry_price:.2f} sl={self.stop_loss:.2f} "
            f"target={self.target:.2f} qty={self.quantity} "
            f"RR={self.reward_risk_ratio:.2f}x"
        )


class BaseStrategy(ABC):
    """
    Abstract base class that all trading strategies must inherit from.

    Subclasses implement generate_signal() to analyse the candle DataFrame
    and return a Signal. The base class provides helper utilities.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Signal:
        """
        Analyse the latest candle data and return a trading signal.

        Args:
            symbol: The stock symbol being analysed (e.g. "RELIANCE")
            df:     OHLCV DataFrame with all candles up to the current moment.
                    Must NOT include any future candles (no lookahead bias).

        Returns:
            A Signal object. If no trade should be taken, return a HOLD signal.
        """
        ...

    def hold_signal(self, symbol: str, price: float) -> Signal:
        """Convenience method to return a HOLD signal."""
        return Signal(
            symbol=symbol,
            action=Action.HOLD,
            entry_price=price,
            stop_loss=price,
            target=price,
            strategy=self.name,
            reason="No signal conditions met",
        )

    def _compute_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """
        Calculate ATR (Average True Range) for stop-loss placement.

        ATR measures the average price range of a stock over `period` candles.
        A stop-loss placed at entry - (1.5 × ATR) sits below normal price
        fluctuations, so minor pullbacks don't trigger it unnecessarily.

        Returns the latest ATR value, or 0.5% of close price as fallback.
        """
        if len(df) < period + 1:
            return df["close"].iloc[-1] * 0.005  # Fallback: 0.5% of price

        high  = df["high"]
        low   = df["low"]
        close = df["close"]

        prev_close = close.shift(1)
        true_range = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low  - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        atr = true_range.rolling(window=period).mean().iloc[-1]
        return float(atr) if not pd.isna(atr) else df["close"].iloc[-1] * 0.005
