"""
Walk-Forward Backtesting — validates strategy robustness across market regimes.

What is walk-forward testing?
  Regular backtesting runs your strategy on one big chunk of history and shows
  overall results. The problem: the strategy might be "curve-fitted" — it works
  on THAT specific period by luck, but fails on future data.

  Walk-forward testing splits the data into many train/test windows and checks
  if the strategy performs consistently across all of them.

  Example with train_months=6, test_months=2, step_months=2:

    Window 1: Train Jan–Jun 2024 │ Test Jul–Aug 2024
    Window 2: Train Mar–Aug 2024 │ Test Sep–Oct 2024
    Window 3: Train May–Oct 2024 │ Test Nov–Dec 2024
    ...

  If the strategy is profitable in 7 of 9 windows → robust.
  If only profitable in 2 of 9 → got lucky in the full backtest.

  For this bot, "training" doesn't optimise parameters (they're fixed in
  config/strategies.py). The value is purely consistency checking: does the
  strategy hold up across different market regimes (bull, bear, sideways)?

Why this matters before going live:
  A strategy that backtests at 60% win rate on 2023 data might only achieve
  35% in 2024 if market character changed. Walk-forward catches this — the
  test windows simulate "unseen" future data from the perspective of each
  training window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pandas as pd
from loguru import logger

from backtesting.engine import BacktestEngine, BacktestResult
from backtesting.performance import PerformanceMetrics, calculate
from strategies.base_strategy import BaseStrategy


@dataclass
class WindowResult:
    """Backtest result for one walk-forward window."""
    window_num:  int
    train_start: date
    train_end:   date
    test_start:  date
    test_end:    date
    result:      BacktestResult
    metrics:     PerformanceMetrics

    @property
    def is_profitable(self) -> bool:
        return self.metrics.total_net_pnl > 0

    @property
    def label(self) -> str:
        return f"W{self.window_num} ({self.test_start.strftime('%b %y')}–{self.test_end.strftime('%b %y')})"


@dataclass
class WalkForwardResult:
    """Aggregated results across all walk-forward windows."""
    symbol:        str
    strategy_name: str
    train_months:  int
    test_months:   int
    windows:       list[WindowResult] = field(default_factory=list)

    @property
    def num_windows(self) -> int:
        return len(self.windows)

    @property
    def profitable_windows(self) -> int:
        return sum(1 for w in self.windows if w.is_profitable)

    @property
    def consistency_pct(self) -> float:
        """% of test windows that were profitable."""
        if not self.windows:
            return 0.0
        return round(self.profitable_windows / self.num_windows * 100, 1)

    @property
    def avg_win_rate(self) -> float:
        """Average win rate across all test windows (only windows with trades)."""
        rates = [w.metrics.win_rate_pct for w in self.windows if w.metrics.num_trades > 0]
        return round(sum(rates) / len(rates), 1) if rates else 0.0

    @property
    def avg_profit_factor(self) -> float:
        pfs = [w.metrics.profit_factor for w in self.windows
               if w.metrics.num_trades > 0 and w.metrics.profit_factor != float("inf")]
        return round(sum(pfs) / len(pfs), 2) if pfs else 0.0

    @property
    def avg_return_pct(self) -> float:
        returns = [w.metrics.total_return_pct for w in self.windows if w.metrics.num_trades > 0]
        return round(sum(returns) / len(returns), 2) if returns else 0.0

    @property
    def total_trades(self) -> int:
        return sum(w.metrics.num_trades for w in self.windows)

    @property
    def is_robust(self) -> bool:
        """
        Strategy is considered robust if:
          - At least 3 windows tested
          - >60% of windows profitable
          - Average win rate across windows >= 45%
        """
        return (
            self.num_windows >= 3
            and self.consistency_pct >= 60.0
            and self.avg_win_rate >= 45.0
        )

    def verdict(self) -> str:
        """Plain-English assessment for beginners."""
        if self.num_windows == 0:
            return "No windows — date range too short. Use at least 8 months of data."
        if self.total_trades == 0:
            return "Zero trades across all windows. Strategy may be too selective for this symbol/period."
        lines = []
        lines.append(
            f"{self.profitable_windows} of {self.num_windows} test windows were profitable "
            f"({self.consistency_pct:.0f}% consistency)."
        )
        if self.consistency_pct >= 60:
            lines.append("That's a good consistency score (target: >60%).")
        else:
            lines.append("Below 60% consistency — strategy may be curve-fitted to specific periods.")
        lines.append(
            f"Average win rate across windows: {self.avg_win_rate:.1f}% "
            f"(target: >45%)."
        )
        if self.is_robust:
            lines.append("✅ Strategy appears ROBUST — safe to continue paper trading.")
        else:
            lines.append("⚠️ Strategy does NOT meet robustness criteria — do NOT go live yet.")
        return " ".join(lines)


class WalkForwardEngine:
    """
    Runs BacktestEngine on rolling train/test windows and aggregates results.

    Args:
        strategy:        Strategy instance to test.
        train_months:    Length of each training window in months (default 6).
        test_months:     Length of each out-of-sample test window in months (default 2).
        step_months:     How far to advance each window (default = test_months).
        initial_capital: Starting capital for each window's backtest.
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        train_months: int = 6,
        test_months:  int = 2,
        step_months:  Optional[int] = None,
        initial_capital: float = 1_00_000.0,
    ) -> None:
        self._strategy       = strategy
        self._train_months   = train_months
        self._test_months    = test_months
        self._step_months    = step_months if step_months is not None else test_months
        self._initial_capital = initial_capital

    def run(self, symbol: str, start: str, end: str) -> WalkForwardResult:
        """
        Run walk-forward analysis for one symbol over a date range.

        Args:
            symbol: Kite symbol e.g. "RELIANCE"
            start:  Start of the full range "YYYY-MM-DD"
            end:    End of the full range "YYYY-MM-DD"

        Returns:
            WalkForwardResult with per-window and aggregate metrics.
        """
        wf_result = WalkForwardResult(
            symbol=symbol,
            strategy_name=self._strategy.name,
            train_months=self._train_months,
            test_months=self._test_months,
        )

        windows = self._build_windows(start, end)
        if not windows:
            logger.warning(
                f"Walk-forward: no windows fit in {start}->{end} with "
                f"train={self._train_months}m test={self._test_months}m"
            )
            return wf_result

        logger.info(
            f"Walk-forward | {symbol} | {self._strategy.name} | "
            f"{len(windows)} windows | train={self._train_months}m test={self._test_months}m"
        )

        engine = BacktestEngine(self._strategy, initial_capital=self._initial_capital)

        for i, (train_start, train_end, test_start, test_end) in enumerate(windows, 1):
            logger.info(
                f"  Window {i}/{len(windows)}: "
                f"train {train_start}->{train_end} | test {test_start}->{test_end}"
            )
            try:
                bt_result = engine.run(
                    symbol=symbol,
                    start=str(test_start),
                    end=str(test_end),
                )
            except (ValueError, Exception) as exc:
                logger.warning(f"  Window {i} skipped — data fetch failed: {exc}")
                continue
            metrics = calculate(bt_result)
            wf_result.windows.append(WindowResult(
                window_num=i,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                result=bt_result,
                metrics=metrics,
            ))
            logger.info(f"    -> {metrics.summary()}")

        logger.info(
            f"Walk-forward complete | {symbol} | {self._strategy.name} | "
            f"consistency={wf_result.consistency_pct:.0f}% | "
            f"avg_win_rate={wf_result.avg_win_rate:.1f}% | "
            f"robust={wf_result.is_robust}"
        )
        return wf_result

    def _build_windows(
        self, start: str, end: str
    ) -> list[tuple[date, date, date, date]]:
        """
        Generate (train_start, train_end, test_start, test_end) tuples.

        The training window is kept for context/display only — we run the
        backtest on the test window. The training period visually shows
        what data the strategy "saw" before the out-of-sample test.
        """
        start_ts = pd.Timestamp(start)
        end_ts   = pd.Timestamp(end)
        windows  = []

        cursor = start_ts
        while True:
            train_start = cursor
            train_end   = cursor + pd.DateOffset(months=self._train_months) - pd.Timedelta(days=1)
            test_start  = train_end + pd.Timedelta(days=1)
            test_end    = test_start + pd.DateOffset(months=self._test_months) - pd.Timedelta(days=1)

            if test_end > end_ts:
                break

            windows.append((
                train_start.date(),
                train_end.date(),
                test_start.date(),
                test_end.date(),
            ))
            cursor += pd.DateOffset(months=self._step_months)

        return windows
