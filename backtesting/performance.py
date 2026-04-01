"""
Performance metrics calculator for backtest results.

These metrics tell you HOW GOOD (or bad) a strategy actually is.
Just knowing "I made ₹10,000" is not enough — you need to know:
  - Was that luck or skill? (Sharpe ratio)
  - What was the worst losing streak? (max drawdown)
  - How often did it win? (win rate)
  - Were wins bigger than losses? (profit factor)

Key metrics explained for beginners:
─────────────────────────────────────────────────────────────
Win Rate:       % of trades that were profitable
                50% win rate with 2:1 RR = profitable strategy
                Even 40% win rate with 3:1 RR can be profitable

Profit Factor:  Gross profit ÷ Gross loss
                > 1.0 = profitable overall
                > 1.5 = good
                > 2.0 = excellent

Max Drawdown:   Largest peak-to-trough decline in portfolio value
                e.g. portfolio went from ₹1,10,000 → ₹97,000 = -11.8% drawdown
                Tells you the worst case you'd have to stomach

Sharpe Ratio:   (Average return per trade) ÷ (Std dev of returns) × √(trades/year)
                > 1.0 = acceptable
                > 1.5 = good
                > 2.0 = excellent
                Measures return per unit of risk taken

Expectancy:     Average net P&L per trade = (win_rate × avg_win) - (loss_rate × avg_loss)
                If positive, the strategy makes money on average per trade
─────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from backtesting.engine import BacktestResult, BacktestTrade


@dataclass
class PerformanceMetrics:
    """All calculated performance metrics for a backtest."""
    # Core counts
    num_trades:    int
    num_winners:   int
    num_losers:    int

    # P&L
    total_net_pnl:    float
    total_return_pct: float
    avg_win:          float   # average P&L of winning trades
    avg_loss:         float   # average P&L of losing trades (positive number)

    # Ratios
    win_rate_pct:  float   # e.g. 55.0 means 55%
    profit_factor: float   # gross_profit / gross_loss
    expectancy:    float   # expected P&L per trade
    sharpe_ratio:  float
    max_drawdown_pct: float  # e.g. -12.5 means 12.5% drawdown

    # Context
    initial_capital: float
    final_capital:   float

    def summary(self) -> str:
        """One-line human-readable summary."""
        return (
            f"Trades={self.num_trades} | "
            f"WinRate={self.win_rate_pct:.1f}% | "
            f"PF={self.profit_factor:.2f} | "
            f"Sharpe={self.sharpe_ratio:.2f} | "
            f"MaxDD={self.max_drawdown_pct:.1f}% | "
            f"Return={self.total_return_pct:.1f}%"
        )

    def verdict(self) -> str:
        """Plain-English verdict for beginners."""
        if self.num_trades < 10:
            return "Too few trades to draw conclusions. Run on more data."
        lines = []
        if self.win_rate_pct >= 50:
            lines.append(f"Win rate {self.win_rate_pct:.0f}% is good (above 50%).")
        else:
            lines.append(
                f"Win rate {self.win_rate_pct:.0f}% is below 50%, but can still be "
                f"profitable if avg win > avg loss."
            )
        if self.profit_factor >= 1.5:
            lines.append(f"Profit factor {self.profit_factor:.2f} is strong (target >1.5).")
        elif self.profit_factor >= 1.0:
            lines.append(f"Profit factor {self.profit_factor:.2f} is marginal (target >1.5).")
        else:
            lines.append(f"Profit factor {self.profit_factor:.2f} means strategy loses money overall.")
        if abs(self.max_drawdown_pct) <= 10:
            lines.append(f"Max drawdown {self.max_drawdown_pct:.1f}% is acceptable.")
        else:
            lines.append(
                f"Max drawdown {self.max_drawdown_pct:.1f}% is large — you'd need "
                f"to stomach this loss before recovery."
            )
        if self.sharpe_ratio >= 1.0:
            lines.append(f"Sharpe {self.sharpe_ratio:.2f} means decent risk-adjusted returns.")
        else:
            lines.append(f"Sharpe {self.sharpe_ratio:.2f} is low — returns don't justify the risk taken.")
        return " ".join(lines)


def calculate(result: BacktestResult) -> PerformanceMetrics:
    """
    Calculate all performance metrics from a BacktestResult.

    Args:
        result: Output of BacktestEngine.run()

    Returns:
        PerformanceMetrics dataclass with all metrics populated.
    """
    trades = result.trades

    if not trades:
        return PerformanceMetrics(
            num_trades=0, num_winners=0, num_losers=0,
            total_net_pnl=0, total_return_pct=0,
            avg_win=0, avg_loss=0, win_rate_pct=0,
            profit_factor=0, expectancy=0, sharpe_ratio=0,
            max_drawdown_pct=0,
            initial_capital=result.initial_capital,
            final_capital=result.initial_capital,
        )

    pnls       = [t.net_pnl for t in trades]
    winners    = [p for p in pnls if p > 0]
    losers     = [p for p in pnls if p <= 0]

    num_trades  = len(pnls)
    num_winners = len(winners)
    num_losers  = len(losers)

    gross_profit = sum(winners) if winners else 0.0
    gross_loss   = abs(sum(losers)) if losers else 0.0

    avg_win  = gross_profit / num_winners if num_winners else 0.0
    avg_loss = gross_loss   / num_losers  if num_losers  else 0.0

    win_rate     = num_winners / num_trades * 100
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    expectancy   = sum(pnls) / num_trades

    # ── Sharpe ratio ──────────────────────────────────────────────────
    # Simplified: (mean return / std dev) × sqrt(252) for daily-equivalent
    mean_pnl = expectancy
    if num_trades > 1:
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / (num_trades - 1)
        std_dev  = math.sqrt(variance)
        sharpe   = (mean_pnl / std_dev * math.sqrt(num_trades)) if std_dev > 0 else 0.0
    else:
        sharpe = 0.0

    # ── Max drawdown ──────────────────────────────────────────────────
    capital   = result.initial_capital
    peak      = capital
    max_dd    = 0.0
    equity_curve = [capital]

    for pnl in pnls:
        capital += pnl
        equity_curve.append(capital)
        if capital > peak:
            peak = capital
        dd = (capital - peak) / peak * 100  # negative value
        if dd < max_dd:
            max_dd = dd

    return PerformanceMetrics(
        num_trades=num_trades,
        num_winners=num_winners,
        num_losers=num_losers,
        total_net_pnl=result.total_net_pnl,
        total_return_pct=result.total_return_pct,
        avg_win=round(avg_win, 2),
        avg_loss=round(avg_loss, 2),
        win_rate_pct=round(win_rate, 1),
        profit_factor=round(profit_factor, 2),
        expectancy=round(expectancy, 2),
        sharpe_ratio=round(sharpe, 2),
        max_drawdown_pct=round(max_dd, 1),
        initial_capital=result.initial_capital,
        final_capital=result.final_capital,
    )
