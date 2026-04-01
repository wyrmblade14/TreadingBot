"""
Portfolio Simulation CLI — run the full bot against the last N trading days.

This replays the last 30 trading days through all strategies simultaneously,
with shared capital and all 10 risk rules enforced. No real money involved.

Usage examples:
    python scripts/run_simulation.py
    python scripts/run_simulation.py --days 20
    python scripts/run_simulation.py --symbols RELIANCE TCS INFY HDFCBANK ICICIBANK
    python scripts/run_simulation.py --strategy ema_crossover
    python scripts/run_simulation.py --days 30 --capital 200000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtesting.portfolio_sim import PortfolioSimulator
from data.instruments import NIFTY50_INSTRUMENTS

# Default: top 10 NIFTY50 by liquidity (a balanced sample for quick runs)
DEFAULT_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "SBIN", "BHARTIARTL", "KOTAKBANK", "ITC",
]

STRATEGY_MAP = {
    "ema_crossover":          "ema",
    "rsi_macd_combo":         "rsi",
    "opening_range_breakout": "orb",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TreadingBot Portfolio Simulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--days", default=30, type=int,
        help="Number of recent trading days to simulate (default: 30)",
    )
    parser.add_argument(
        "--symbols", nargs="+", default=DEFAULT_SYMBOLS,
        help="NSE symbols to include (default: top 10 NIFTY50)",
    )
    parser.add_argument(
        "--all-symbols", action="store_true",
        help="Use all 50 NIFTY50 symbols (slow, ~5 min)",
    )
    parser.add_argument(
        "--strategy", default=None,
        choices=list(STRATEGY_MAP.keys()),
        help="Run only one strategy (default: all three)",
    )
    parser.add_argument(
        "--capital", default=100_000, type=float,
        help="Starting virtual capital in INR (default: 100000)",
    )
    args = parser.parse_args()

    symbols = (
        [i.kite_symbol for i in NIFTY50_INSTRUMENTS]
        if args.all_symbols
        else args.symbols
    )
    strategy_key = STRATEGY_MAP.get(args.strategy) if args.strategy else None

    print(f"\n{'='*62}")
    print(f"  Portfolio Simulation")
    print(f"  Symbols   : {len(symbols)} ({', '.join(symbols[:5])}{'...' if len(symbols) > 5 else ''})")
    print(f"  Days      : last {args.days} trading days")
    print(f"  Strategy  : {args.strategy or 'all three'}")
    print(f"  Capital   : Rs{args.capital:,.0f}")
    print(f"{'='*62}\n")

    sim = PortfolioSimulator(
        capital=args.capital,
        trading_days=args.days,
        strategies=strategy_key,
    )
    result = sim.run(symbols=symbols)

    if not result.days:
        print("No trading days found. Check symbol names or date range.")
        return

    # ── Per-day table ─────────────────────────────────────────────────
    print(f"  {'Date':<12} {'Trades':>6} {'Win%':>6} {'P&L':>10} {'Capital':>12} {'Note'}")
    print(f"  {'-'*60}")
    for day in result.days:
        note = "HALTED" if day.halted else ""
        pnl_str = f"Rs{day.net_pnl:+,.0f}"
        cap_str = f"Rs{day.capital_end:,.0f}"
        wr_str  = f"{day.win_rate_pct:.0f}%" if day.num_trades else "N/A"
        print(
            f"  {str(day.date):<12} {day.num_trades:>6} {wr_str:>6} "
            f"{pnl_str:>10} {cap_str:>12} {note}"
        )

    # ── Summary ───────────────────────────────────────────────────────
    print(f"\n  {'-'*50}")
    print(f"  Days simulated : {len(result.days)}")
    print(f"  Profitable days: {result.profitable_days} / {len(result.days)}")
    print(f"  Halted days    : {result.halted_days} (daily loss limit hit)")
    print(f"  Total trades   : {result.total_trades}")
    print(f"  Win rate       : {result.win_rate_pct:.1f}%")
    print(f"  Net P&L        : Rs{result.total_net_pnl:+,.0f}")
    print(f"  Total return   : {result.total_return_pct:+.2f}%")
    print(f"  Final capital  : Rs{result.final_capital:,.0f}")

    # ── Strategy breakdown ────────────────────────────────────────────
    breakdown = result.strategy_breakdown()
    if breakdown:
        print(f"\n  Strategy Breakdown:")
        print(f"  {'Strategy':<28} {'Trades':>6} {'Wins':>6} {'Win%':>6} {'P&L':>10}")
        print(f"  {'-'*58}")
        for name, stats in sorted(breakdown.items(), key=lambda x: -x[1]["net_pnl"]):
            wr = round(100 * stats["wins"] / stats["trades"], 1) if stats["trades"] else 0
            print(
                f"  {name:<28} {stats['trades']:>6} {stats['wins']:>6} "
                f"{wr:>5.1f}% Rs{stats['net_pnl']:>8,.0f}"
            )

    print()


if __name__ == "__main__":
    main()
