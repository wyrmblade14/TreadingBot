"""
Backtest CLI — run any strategy on any NIFTY50 stock from the command line.

Usage examples:
    python scripts/run_backtest.py
    python scripts/run_backtest.py --symbol RELIANCE --strategy ema_crossover
    python scripts/run_backtest.py --symbol TCS --strategy rsi_macd_combo --start 2023-01-01 --end 2024-06-30
    python scripts/run_backtest.py --all-strategies --symbol INFY
    python scripts/run_backtest.py --walk-forward --symbol HDFCBANK --strategy ema_crossover --start 2023-01-01 --end 2024-12-31
    python scripts/run_backtest.py --walk-forward --train-months 6 --test-months 2

Available strategies:
    ema_crossover          EMA 9/21/50 crossover with volume filter
    rsi_macd_combo         RSI neutral zone + MACD crossover
    opening_range_breakout Opening range breakout (9:15–9:30 AM)
    bb_mean_reversion      Bollinger Band mean reversion (counter-trend)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtesting.engine import BacktestEngine
from backtesting.performance import calculate
from backtesting.report import generate_report
from backtesting.walk_forward import WalkForwardEngine
from strategies.bb_mean_reversion import BBMeanReversionStrategy
from strategies.ema_crossover import EMACrossoverStrategy
from strategies.opening_range_breakout import ORBStrategy
from strategies.rsi_macd_combo import RSIMACDStrategy
from strategies.vwap_bounce import VWAPBounceStrategy

STRATEGY_MAP = {
    "ema_crossover":          EMACrossoverStrategy,
    "rsi_macd_combo":         RSIMACDStrategy,
    "opening_range_breakout": ORBStrategy,
    "bb_mean_reversion":      BBMeanReversionStrategy,
    "vwap_bounce":            VWAPBounceStrategy,
}


def run_single(
    symbol: str,
    strategy_name: str,
    start: str,
    end: str,
    capital: float,
    open_report: bool,
) -> None:
    StrategyClass = STRATEGY_MAP[strategy_name]
    strategy = StrategyClass()
    engine   = BacktestEngine(strategy, initial_capital=capital)

    print(f"\n{'='*60}")
    print(f"  Backtest: {symbol} | {strategy_name}")
    print(f"  Period  : {start} -> {end}")
    print(f"  Capital : ₹{capital:,.0f}")
    print(f"{'='*60}\n")

    result  = engine.run(symbol, start=start, end=end)
    metrics = calculate(result)

    if metrics.num_trades == 0:
        print("No trades generated. Try a longer date range or different symbol.")
        return

    # Print metrics table
    rows = [
        ("Total trades",    str(metrics.num_trades)),
        ("Winners",         f"{metrics.num_winners} ({metrics.win_rate_pct:.1f}%)"),
        ("Losers",          str(metrics.num_losers)),
        ("Avg win",         f"₹{metrics.avg_win:,.0f}"),
        ("Avg loss",        f"₹{metrics.avg_loss:,.0f}"),
        ("Profit factor",   f"{metrics.profit_factor:.2f}"),
        ("Expectancy/trade",f"₹{metrics.expectancy:,.0f}"),
        ("Sharpe ratio",    f"{metrics.sharpe_ratio:.2f}"),
        ("Max drawdown",    f"{metrics.max_drawdown_pct:.1f}%"),
        ("Net P&L",         f"₹{metrics.total_net_pnl:,.0f}"),
        ("Total return",    f"{metrics.total_return_pct:.1f}%"),
        ("Final capital",   f"₹{metrics.final_capital:,.0f}"),
    ]
    col_w = max(len(r[0]) for r in rows) + 2
    for label, value in rows:
        print(f"  {label:<{col_w}}{value}")

    print(f"\n  Verdict: {metrics.verdict()}\n")

    # Generate HTML report
    report_path = generate_report(result, metrics)

    if open_report:
        import webbrowser
        webbrowser.open(f"file://{report_path.resolve()}")


def run_walk_forward(
    symbol: str,
    strategy_name: str,
    start: str,
    end: str,
    capital: float,
    train_months: int,
    test_months: int,
) -> None:
    StrategyClass = STRATEGY_MAP[strategy_name]
    strategy = StrategyClass()
    engine   = WalkForwardEngine(
        strategy,
        train_months=train_months,
        test_months=test_months,
        initial_capital=capital,
    )

    print(f"\n{'='*60}")
    print(f"  Walk-Forward: {symbol} | {strategy_name}")
    print(f"  Period      : {start} → {end}")
    print(f"  Train/Test  : {train_months}m train / {test_months}m test")
    print(f"  Capital     : ₹{capital:,.0f}")
    print(f"{'='*60}\n")

    wf = engine.run(symbol, start=start, end=end)

    if wf.num_windows == 0:
        print("  No windows generated — date range too short.")
        print(f"  Need at least {train_months + test_months} months of data.")
        return

    # Per-window table
    header = f"  {'Window':<10} {'Test Period':<20} {'Trades':>6} {'Win%':>6} {'PF':>6} {'Return%':>8} {'P&L':>10}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for w in wf.windows:
        period = f"{w.test_start.strftime('%d%b%y')}–{w.test_end.strftime('%d%b%y')}"
        pf_str = f"{w.metrics.profit_factor:.2f}" if w.metrics.profit_factor != float("inf") else "∞"
        profit_marker = "✅" if w.is_profitable else "❌"
        print(
            f"  {w.label:<10} {period:<20} "
            f"{w.metrics.num_trades:>6} "
            f"{w.metrics.win_rate_pct:>5.1f}% "
            f"{pf_str:>6} "
            f"{w.metrics.total_return_pct:>7.1f}% "
            f"  ₹{w.metrics.total_net_pnl:>8,.0f} {profit_marker}"
        )

    # Summary
    print(f"\n  {'─'*50}")
    print(f"  Windows      : {wf.num_windows}  (profitable: {wf.profitable_windows})")
    print(f"  Consistency  : {wf.consistency_pct:.0f}%  (target: >60%)")
    print(f"  Avg win rate : {wf.avg_win_rate:.1f}%  (target: >45%)")
    print(f"  Avg PF       : {wf.avg_profit_factor:.2f}  (target: >1.0)")
    print(f"  Avg return   : {wf.avg_return_pct:.1f}% per test window")
    print(f"  Total trades : {wf.total_trades}")
    print(f"\n  Verdict: {wf.verdict()}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TreadingBot Backtest Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--symbol",   default="RELIANCE",       help="NSE symbol (default: RELIANCE)")
    parser.add_argument("--strategy", default="ema_crossover",  help="Strategy name", choices=list(STRATEGY_MAP))
    parser.add_argument("--start",    default="2023-01-01",     help="Start date YYYY-MM-DD")
    parser.add_argument("--end",      default="2024-12-31",     help="End date YYYY-MM-DD")
    parser.add_argument("--capital",  default=100_000, type=float, help="Starting capital in INR")
    parser.add_argument("--all-strategies", action="store_true", help="Run all strategies on this symbol")
    parser.add_argument("--open",          action="store_true", help="Open HTML report in browser")
    parser.add_argument("--walk-forward",  action="store_true", help="Run walk-forward analysis instead of single backtest")
    parser.add_argument("--train-months",  default=6,  type=int, help="Walk-forward: training window in months (default: 6)")
    parser.add_argument("--test-months",   default=2,  type=int, help="Walk-forward: test window in months (default: 2)")

    args = parser.parse_args()

    if args.walk_forward:
        if args.all_strategies:
            for name in STRATEGY_MAP:
                run_walk_forward(args.symbol, name, args.start, args.end, args.capital,
                                 args.train_months, args.test_months)
        else:
            run_walk_forward(args.symbol, args.strategy, args.start, args.end, args.capital,
                             args.train_months, args.test_months)
    elif args.all_strategies:
        for name in STRATEGY_MAP:
            run_single(args.symbol, name, args.start, args.end, args.capital, open_report=False)
    else:
        if args.strategy not in STRATEGY_MAP:
            print(f"Unknown strategy '{args.strategy}'. Choose from: {list(STRATEGY_MAP)}")
            sys.exit(1)
        run_single(args.symbol, args.strategy, args.start, args.end, args.capital, args.open)


if __name__ == "__main__":
    main()
