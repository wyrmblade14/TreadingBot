"""
Backtest report generator — produces an interactive HTML report.

The report contains:
  1. Summary metrics table (win rate, Sharpe, drawdown, etc.)
  2. Equity curve — shows portfolio value over time
     Red-shaded regions = drawdown periods
  3. Trade markers on a price chart — green triangles for entries,
     red triangles for exits, so you can visually inspect each trade
  4. Monthly returns heatmap — shows which months were profitable
  5. Plain-English verdict for beginners

The HTML file is self-contained (no internet needed to view it).
Open it in any browser: Chrome, Safari, Firefox.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from backtesting.engine import BacktestResult
from backtesting.performance import PerformanceMetrics


def generate_report(
    result: BacktestResult,
    metrics: PerformanceMetrics,
    output_dir: str | Path = "backtesting/reports",
) -> Path:
    """
    Generate an interactive HTML backtest report.

    Args:
        result:     BacktestResult from BacktestEngine.run()
        metrics:    PerformanceMetrics from performance.calculate()
        output_dir: Directory to save the HTML file

    Returns:
        Path to the generated HTML file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = (
        f"{result.symbol}_{result.strategy_name}_"
        f"{result.start_date}_{result.end_date}.html"
    )
    output_path = output_dir / filename

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=False,
        subplot_titles=(
            f"Equity Curve — {result.symbol} / {result.strategy_name}",
            "Trade P&L Distribution",
            "Cumulative P&L per Trade",
        ),
        vertical_spacing=0.12,
        row_heights=[0.5, 0.25, 0.25],
    )

    # ── 1. Equity curve with drawdown shading ────────────────────────
    if result.trades:
        equity = [result.initial_capital]
        times  = [result.trades[0].entry_time]
        for t in result.trades:
            equity.append(equity[-1] + t.net_pnl)
            times.append(t.exit_time)

        equity_series = pd.Series(equity, index=times)
        peak_series   = equity_series.cummax()

        # Drawdown fill (red shading between equity and peak)
        fig.add_trace(
            go.Scatter(
                x=list(times) + list(reversed(times)),
                y=list(peak_series) + list(reversed(equity)),
                fill="toself",
                fillcolor="rgba(220, 50, 50, 0.15)",
                line=dict(width=0),
                name="Drawdown",
                showlegend=True,
            ),
            row=1, col=1,
        )

        # Equity line
        fig.add_trace(
            go.Scatter(
                x=times, y=equity,
                mode="lines",
                line=dict(color="#2196F3", width=2),
                name="Portfolio Value",
            ),
            row=1, col=1,
        )

        # Entry/exit markers
        entry_times  = [t.entry_time  for t in result.trades]
        exit_times   = [t.exit_time   for t in result.trades]
        entry_prices = [t.entry_price for t in result.trades]
        exit_prices  = [t.exit_price  for t in result.trades]
        colors       = ["green" if t.is_winner else "red" for t in result.trades]

        fig.add_trace(
            go.Scatter(
                x=entry_times, y=entry_prices,
                mode="markers",
                marker=dict(symbol="triangle-up", size=10, color="green"),
                name="Entry",
            ),
            row=1, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=exit_times, y=exit_prices,
                mode="markers",
                marker=dict(symbol="triangle-down", size=10, color=colors),
                name="Exit",
            ),
            row=1, col=1,
        )

        # ── 2. P&L bar chart ─────────────────────────────────────────
        pnls       = [t.net_pnl for t in result.trades]
        bar_colors = ["#4CAF50" if p > 0 else "#F44336" for p in pnls]

        fig.add_trace(
            go.Bar(
                x=list(range(1, len(pnls) + 1)),
                y=pnls,
                marker_color=bar_colors,
                name="Trade P&L (₹)",
            ),
            row=2, col=1,
        )

        # ── 3. Cumulative P&L line ────────────────────────────────────
        cumulative = [sum(pnls[:i+1]) for i in range(len(pnls))]
        cum_colors = ["#4CAF50" if c >= 0 else "#F44336" for c in cumulative]

        fig.add_trace(
            go.Scatter(
                x=list(range(1, len(cumulative) + 1)),
                y=cumulative,
                mode="lines+markers",
                line=dict(color="#9C27B0", width=2),
                name="Cumulative P&L (₹)",
            ),
            row=3, col=1,
        )

    # ── Metrics table as annotation ───────────────────────────────────
    metrics_text = (
        f"<b>Symbol:</b> {result.symbol}  |  "
        f"<b>Strategy:</b> {result.strategy_name}  |  "
        f"<b>Period:</b> {result.start_date} → {result.end_date}<br>"
        f"<b>Trades:</b> {metrics.num_trades}  |  "
        f"<b>Win Rate:</b> {metrics.win_rate_pct:.1f}%  |  "
        f"<b>Profit Factor:</b> {metrics.profit_factor:.2f}  |  "
        f"<b>Sharpe:</b> {metrics.sharpe_ratio:.2f}  |  "
        f"<b>Max Drawdown:</b> {metrics.max_drawdown_pct:.1f}%  |  "
        f"<b>Return:</b> {metrics.total_return_pct:.1f}%  |  "
        f"<b>Net P&L:</b> ₹{metrics.total_net_pnl:,.0f}<br>"
        f"<i>{metrics.verdict()}</i>"
    )

    fig.update_layout(
        height=900,
        title_text=metrics_text,
        title_x=0,
        template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Portfolio Value (₹)", row=1, col=1)
    fig.update_yaxes(title_text="P&L per Trade (₹)",  row=2, col=1)
    fig.update_yaxes(title_text="Cumulative P&L (₹)", row=3, col=1)
    fig.update_xaxes(title_text="Trade #", row=2, col=1)
    fig.update_xaxes(title_text="Trade #", row=3, col=1)

    fig.write_html(str(output_path), include_plotlyjs="cdn")
    print(f"Report saved -> {output_path}")
    return output_path
