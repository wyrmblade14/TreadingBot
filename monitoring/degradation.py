"""
Strategy Degradation Detection — catches when a strategy stops working.

What is "degradation"?
  Your backtest shows EMA Crossover wins 50% of the time. But after 3 weeks
  of paper trading, it's only winning 30% of the time. That's an 20-point
  drop — the strategy is "degraded."

  This happens because market regimes change:
    - Backtest covered a strong bull market; now we're in a sideways chop.
    - A catalyst (RBI policy, global events) changed how stocks move.
    - The strategy was slightly over-fitted to backtested history.

How we detect it:
  For each strategy, we:
    1. Take the last 20 closed trades from the live trade log.
    2. Calculate the win rate of those 20 trades.
    3. Compare to the backtest baseline win rate (stored in config/settings.py).
    4. If the live win rate is more than 15% below the baseline → DEGRADED.

  Example:
    Baseline:      50% win rate (from backtesting)
    Live (last 20): 32% win rate
    Drop:          50 - 32 = 18 percentage points → exceeds 15% threshold
    Result:        DEGRADED — review before continuing

What to do if degraded:
  - Don't panic. Don't disable it immediately.
  - Check: is NIFTY50 in an unusually choppy / low-volatility phase?
  - Run a fresh backtest on the last 60 days. Compare to degraded period.
  - If the strategy fails even in backtesting on recent data → disable it.
  - If the backtest is still OK → wait for 10 more trades before re-assessing.
"""

from __future__ import annotations

from dataclasses import dataclass

from config.settings import (
    DEGRADATION_MIN_TRADES,
    DEGRADATION_THRESHOLD_PCT,
    STRATEGY_BASELINES,
)
from execution.trade_log import TradeLogger


@dataclass
class StrategyHealth:
    """Health snapshot for one strategy."""
    strategy:          str
    baseline_win_rate: float          # from backtest baseline in config
    rolling_win_rate:  float | None   # last N trades; None if too few trades
    trade_count:       int            # how many trades were used for rolling calc
    min_trades:        int            # minimum trades required before alerting
    threshold_pct:     float          # drop threshold used

    @property
    def has_enough_trades(self) -> bool:
        return self.trade_count >= self.min_trades

    @property
    def is_degraded(self) -> bool:
        """
        True when we have enough trades AND win rate has dropped
        more than threshold below baseline.
        """
        if not self.has_enough_trades or self.rolling_win_rate is None:
            return False
        return (self.baseline_win_rate - self.rolling_win_rate) > self.threshold_pct

    @property
    def drop_pct(self) -> float | None:
        """Percentage-point drop from baseline. Positive = worse than baseline."""
        if self.rolling_win_rate is None:
            return None
        return round(self.baseline_win_rate - self.rolling_win_rate, 1)

    @property
    def status_label(self) -> str:
        if not self.has_enough_trades:
            return f"WATCHING ({self.trade_count}/{self.min_trades} trades)"
        if self.is_degraded:
            return f"DEGRADED (-{self.drop_pct}pp below baseline)"
        drop = self.drop_pct or 0.0
        if drop > 0:
            return f"CAUTION (-{drop}pp below baseline)"
        return f"HEALTHY (+{abs(drop):.1f}pp above baseline)"

    @property
    def alert_message(self) -> str | None:
        """Non-None only when the strategy is truly degraded and needs action."""
        if not self.is_degraded:
            return None
        return (
            f"{self.strategy} win rate has dropped {self.drop_pct}pp "
            f"(live: {self.rolling_win_rate:.1f}% vs baseline: {self.baseline_win_rate:.1f}%) "
            f"over last {self.trade_count} trades. "
            f"Consider pausing this strategy and reviewing recent market conditions."
        )


def check_strategy(
    strategy: str,
    logger: TradeLogger,
    n: int = 20,
) -> StrategyHealth:
    """
    Check degradation for a single strategy.

    Args:
        strategy: Strategy name matching STRATEGY_BASELINES key.
        logger:   TradeLogger instance.
        n:        Number of recent trades to use for rolling win rate.

    Returns:
        StrategyHealth snapshot.
    """
    baseline = STRATEGY_BASELINES.get(strategy, 50.0)
    rolling_win_rate, trade_count = logger.get_rolling_win_rate(strategy, n=n)

    return StrategyHealth(
        strategy=strategy,
        baseline_win_rate=baseline,
        rolling_win_rate=rolling_win_rate,
        trade_count=trade_count,
        min_trades=DEGRADATION_MIN_TRADES,
        threshold_pct=DEGRADATION_THRESHOLD_PCT,
    )


def check_all_strategies(logger: TradeLogger | None = None, n: int = 20) -> list[StrategyHealth]:
    """
    Check degradation for all strategies defined in STRATEGY_BASELINES.

    Args:
        logger: TradeLogger instance (creates one if not provided).
        n:      Number of recent trades per strategy to assess.

    Returns:
        List of StrategyHealth, one per strategy. Degraded ones come first.
    """
    if logger is None:
        logger = TradeLogger()

    results = [check_strategy(name, logger, n=n) for name in STRATEGY_BASELINES]

    # Degraded first, then caution, then healthy/watching
    def _sort_key(h: StrategyHealth) -> int:
        if h.is_degraded:
            return 0
        if h.has_enough_trades and h.drop_pct and h.drop_pct > 0:
            return 1
        return 2

    return sorted(results, key=_sort_key)
