"""
Day Replay CLI — replay a past trading day through all strategies.

Usage examples:
    # Replay today with first 5 NIFTY50 symbols
    python scripts/run_replay.py

    # Replay a specific date
    python scripts/run_replay.py --date 2026-03-27

    # Replay one symbol
    python scripts/run_replay.py --date 2026-03-27 --symbol RELIANCE

    # Replay first 10 symbols
    python scripts/run_replay.py --date 2026-03-27 --watchlist 10

    # Replay with a single strategy
    python scripts/run_replay.py --date 2026-03-27 --strategy orb

    # Slow replay — 0.5s pause per candle (feels live)
    python scripts/run_replay.py --date 2026-03-27 --live

Run from the project root after activating the virtual environment:
    source venv/bin/activate
    python scripts/run_replay.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is importable when run from scripts/
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtesting.day_replay import DayReplayEngine, NIFTY50_SYMBOLS
from config.settings import VIRTUAL_CAPITAL


def _parse_args() -> argparse.Namespace:
    from datetime import date as _date

    parser = argparse.ArgumentParser(
        description="Replay a past trading day through the TreadingBot strategies.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--date",
        default=_date.today().isoformat(),
        help='Date to replay in YYYY-MM-DD format (default: today)',
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help='Single Kite symbol to replay e.g. RELIANCE (default: watchlist)',
    )
    parser.add_argument(
        "--watchlist",
        type=int,
        default=5,
        metavar="N",
        help='Number of NIFTY50 symbols to replay (default: 5)',
    )
    parser.add_argument(
        "--strategy",
        default=None,
        choices=["ema", "rsi", "orb"],
        help='Strategy to run: ema / rsi / orb (default: all)',
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=VIRTUAL_CAPITAL,
        help=f'Starting virtual capital (default: ₹{VIRTUAL_CAPITAL:,.0f})',
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help='0.5 second pause between candles for real-time feel',
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.symbol:
        symbols = [args.symbol.upper()]
    else:
        symbols = NIFTY50_SYMBOLS[: args.watchlist]

    strat_label = args.strategy or "all strategies"
    live_delay  = 0.5 if args.live else 0.0

    print("=" * 54)
    print(
        f"REPLAY  {args.date} | ₹{args.capital:,.0f} | "
        f"{len(symbols)} symbol(s) | {strat_label}"
    )
    print("=" * 54)

    engine = DayReplayEngine(
        capital=args.capital,
        strategies=args.strategy,
        live_delay=live_delay,
    )

    try:
        result = engine.run(symbols=symbols, replay_date=args.date)
    except ValueError as exc:
        print(f"\nERROR: {exc}")
        sys.exit(1)

    # ── Print candle-level events ─────────────────────────────────────
    interesting_events = {"BUY", "EXIT", "EXIT EOD", "REJECTED", "ERROR", "NO DATA"}
    for entry in result.candle_log:
        if entry["event"] in interesting_events:
            print(
                f"[{entry['time'][-5:]} IST]  "
                f"{entry['symbol']:<12}  "
                f"{entry['event']:<10}  "
                f"{entry['detail']}"
            )

    # ── Summary ───────────────────────────────────────────────────────
    print("=" * 54)
    winners = result.num_winners
    trades  = result.num_trades
    win_pct = result.win_rate_pct
    pnl_str = f"₹{result.net_pnl:+,.0f}"

    print(
        f"SUMMARY  "
        f"Trades: {trades} | "
        f"Winners: {winners} ({win_pct:.0f}%) | "
        f"Net P&L: {pnl_str} | "
        f"Final cash: ₹{result.final_cash:,.0f}"
    )
    print("=" * 54)

    if result.brokerage_total > 0:
        print(f"         Total brokerage deducted: ₹{result.brokerage_total:,.2f}")


if __name__ == "__main__":
    main()
