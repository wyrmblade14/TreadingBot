"""
Walk-Forward Analysis CLI — validate strategy robustness across market regimes.

Usage examples:
    python scripts/run_walk_forward.py
    python scripts/run_walk_forward.py --symbol RELIANCE --strategy ema_crossover
    python scripts/run_walk_forward.py --train-months 6 --test-months 2
    python scripts/run_walk_forward.py --symbol TCS --start 2023-01-01 --end 2024-12-31

What is walk-forward testing?
    Splits history into rolling train/test windows (e.g., train 6m, test 2m).
    If the strategy is consistently profitable across most test windows, it
    is considered "robust" and less likely to be curve-fitted.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

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
        description="TreadingBot Walk-Forward Analysis Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--symbol",   default="RELIANCE",       help="NSE symbol (default: RELIANCE)")
    parser.add_argument("--strategy", default="ema_crossover",  help="Strategy name", choices=list(STRATEGY_MAP))
    parser.add_argument("--start",    default="2023-01-01",     help="Start date YYYY-MM-DD")
    parser.add_argument("--end",      default="2024-12-31",     help="End date YYYY-MM-DD")
    parser.add_argument("--capital",  default=100_000, type=float, help="Starting capital in INR")
    parser.add_argument("--train-months",  default=6,  type=int, help="Training window in months (default: 6)")
    parser.add_argument("--test-months",   default=2,  type=int, help="Test window in months (default: 2)")
    parser.add_argument("--all-strategies", action="store_true", help="Run all strategies on this symbol")

    args = parser.parse_args()

    if args.all_strategies:
        for name in STRATEGY_MAP:
            run_walk_forward(args.symbol, name, args.start, args.end, args.capital,
                             args.train_months, args.test_months)
    else:
        run_walk_forward(args.symbol, args.strategy, args.start, args.end, args.capital,
                         args.train_months, args.test_months)


if __name__ == "__main__":
    main()
