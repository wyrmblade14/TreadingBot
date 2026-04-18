"""
Weekly Saturday Review — backtest + optimize all 6 strategies on top fundamentals.

Runs every Saturday 10 AM IST:
  1. Get top 25 fundamentally-ranked NIFTY50 symbols
  2. For each symbol:
     a. Backtest + optimize all 6 strategies (50 Optuna trials each)
     b. Score by Sharpe × (win_rate / 50)
     c. Pick best strategy if num_trades >= 15
  3. Save approved_symbols.json: {week_of, symbols: [{symbol, strategy, sharpe, win_rate}]}
  4. Update watchlist.py to prioritize these symbols

Usage:
    python scripts/weekly_review.py                    # top 25, write approved_symbols.json
    python scripts/weekly_review.py --top 30           # wider universe
    python scripts/weekly_review.py --dry-run          # print results, don't save
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from analysis.fundamental_filter import score_fundamentals
from backtesting.engine import BacktestEngine
from backtesting.performance import calculate
from data.instruments import SYMBOL_TO_SECTOR
from learning.param_optimizer import ParamOptimizer
from strategies.bb_mean_reversion import BBMeanReversionStrategy
from strategies.ema_crossover import EMACrossoverStrategy
from strategies.opening_range_breakout import ORBStrategy
from strategies.rsi_macd_combo import RSIMACDStrategy
from strategies.trend_rider import TrendRiderStrategy
from strategies.vwap_bounce import VWAPBounceStrategy

STRATEGY_MAP = {
    "ema_crossover":          EMACrossoverStrategy,
    "rsi_macd_combo":         RSIMACDStrategy,
    "opening_range_breakout": ORBStrategy,
    "vwap_bounce":            VWAPBounceStrategy,
    "trend_rider":            TrendRiderStrategy,
    "bb_mean_reversion":      BBMeanReversionStrategy,
}

MIN_TRADES = 15
INITIAL_CAPITAL = 100_000


def get_top_symbols(top: int = 25) -> list[str]:
    """Get top N fundamentally-ranked NIFTY50 symbols."""
    from data.instruments import NIFTY50_INSTRUMENTS

    scores = []
    for inst in NIFTY50_INSTRUMENTS:
        sym = inst.kite_symbol
        score = score_fundamentals(sym)
        scores.append((sym, score.score))

    # Sort by score descending, take top N
    scores.sort(key=lambda x: x[1], reverse=True)
    top_symbols = [s[0] for s in scores[:top]]
    logger.info(f"Top {top} fundamentally-ranked symbols: {top_symbols}")
    return top_symbols


def backtest_symbol_all_strategies(
    symbol: str,
    start: str,
    end: str,
) -> dict[str, dict]:
    """
    Run all 6 strategies on symbol, return results.
    Format: {strategy_name: {sharpe, win_rate, num_trades, score}}
    """
    results = {}

    for strat_name, StrategyClass in STRATEGY_MAP.items():
        try:
            strategy = StrategyClass()
            engine = BacktestEngine(strategy, initial_capital=INITIAL_CAPITAL)
            result = engine.run(symbol, start=start, end=end)
            metrics = calculate(result)

            # Composite score: Sharpe × (win_rate / 50)
            # win_rate=50% is neutral (random), so divide by 50
            score = metrics.sharpe_ratio * (metrics.win_rate_pct / 50.0)

            results[strat_name] = {
                "sharpe":      metrics.sharpe_ratio,
                "win_rate":    metrics.win_rate_pct,
                "num_trades":  metrics.num_trades,
                "score":       score,
                "profit_factor": metrics.profit_factor,
                "max_drawdown": metrics.max_drawdown_pct,
            }
            logger.info(
                f"  {strat_name:<25} | trades={metrics.num_trades:>3} "
                f"| sharpe={metrics.sharpe_ratio:>6.2f} | wr={metrics.win_rate_pct:>5.1f}% "
                f"| score={score:>6.2f}"
            )
        except Exception as e:
            logger.error(f"  {strat_name}: backtest failed — {e}")
            results[strat_name] = None

    return results


def pick_best_strategy(
    symbol: str,
    results: dict[str, dict],
) -> tuple[str, dict] | None:
    """
    Pick best strategy from results.
    Only returns if num_trades >= MIN_TRADES.
    """
    candidates = [
        (strat, res) for strat, res in results.items()
        if res and res["num_trades"] >= MIN_TRADES
    ]

    if not candidates:
        logger.warning(f"  {symbol}: no strategy met MIN_TRADES >= {MIN_TRADES}")
        return None

    # Sort by score descending
    candidates.sort(key=lambda x: x[1]["score"], reverse=True)
    best_strat, best_res = candidates[0]

    logger.success(
        f"  {symbol}: best is {best_strat} "
        f"(score={best_res['score']:.2f}, sharpe={best_res['sharpe']:.2f}, "
        f"wr={best_res['win_rate']:.1f}%, trades={best_res['num_trades']})"
    )
    return (best_strat, best_res)


def optimize_strategy(
    symbol: str,
    strategy_name: str,
    n_trials: int = 30,  # fewer trials for weekly review (faster)
) -> bool:
    """Run Bayesian optimizer for strategy. Returns True if improvement saved."""
    try:
        optimizer = ParamOptimizer()

        # Map strategy name to optimizer method
        method_map = {
            "ema_crossover":          optimizer.optimize_ema_crossover,
            "rsi_macd_combo":         optimizer.optimize_rsi_macd_combo,
            "opening_range_breakout": optimizer.optimize_opening_range_breakout,
            "vwap_bounce":            optimizer.optimize_vwap_bounce,
            "trend_rider":            optimizer.optimize_trend_rider,
            "bb_mean_reversion":      optimizer.optimize_bb_mean_reversion,
        }

        if strategy_name not in method_map:
            return False

        optimize_fn = method_map[strategy_name]
        result = optimize_fn(symbol, n_trials=n_trials)
        return result is not None
    except Exception as e:
        logger.error(f"  {symbol}/{strategy_name}: optimization failed — {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Weekly Saturday Review — backtest + optimize all strategies on top fundamentals",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--top",      default=25, type=int, help="Top N fundamentally-ranked symbols (default: 25)")
    parser.add_argument("--start",    default="2024-01-01", help="Backtest start date YYYY-MM-DD")
    parser.add_argument("--end",      default="2024-12-31", help="Backtest end date YYYY-MM-DD")
    parser.add_argument("--optimize", action="store_true", help="Run Bayesian optimizer on best strategy for each symbol")
    parser.add_argument("--dry-run",  action="store_true", help="Print results, don't save to approved_symbols.json")
    args = parser.parse_args()

    print(f"\n{'='*80}")
    print(f"  Weekly Saturday Review: Top {args.top} Fundamentals")
    print(f"  Period: {args.start} → {args.end}")
    print(f"  Optimize: {args.optimize}")
    print(f"{'='*80}\n")

    # Step 1: Get top symbols
    top_symbols = get_top_symbols(top=args.top)

    approved = {
        "week_of": date.today().isoformat(),
        "generated_at": date.today().isoformat(),
        "symbols": [],
    }

    # Step 2: Backtest all strategies on each symbol
    for i, symbol in enumerate(top_symbols, 1):
        print(f"\n[{i}/{len(top_symbols)}] {symbol}")
        print(f"  Backtesting all 6 strategies...")

        results = backtest_symbol_all_strategies(symbol, args.start, args.end)

        # Step 3: Pick best strategy
        best = pick_best_strategy(symbol, results)
        if not best:
            continue

        best_strat, best_res = best

        # Step 4: Optionally optimize best strategy
        if args.optimize:
            print(f"  Optimizing {best_strat} (30 trials)...")
            optimize_strategy(symbol, best_strat, n_trials=30)

        approved["symbols"].append({
            "symbol": symbol,
            "strategy": best_strat,
            "sharpe": best_res["sharpe"],
            "win_rate": best_res["win_rate"],
            "num_trades": best_res["num_trades"],
            "profit_factor": best_res["profit_factor"],
            "max_drawdown": best_res["max_drawdown"],
        })

    print(f"\n{'='*80}")
    print(f"  Summary: {len(approved['symbols'])} symbols approved for next week")
    print(f"{'='*80}\n")

    for sym_data in approved["symbols"]:
        print(f"  {sym_data['symbol']:<10} → {sym_data['strategy']:<25} "
              f"sharpe={sym_data['sharpe']:>6.2f} wr={sym_data['win_rate']:>5.1f}%")

    # Step 5: Save to approved_symbols.json
    if not args.dry_run:
        out_file = Path("config/approved_symbols.json")
        with open(out_file, "w") as f:
            json.dump(approved, f, indent=2)
        logger.success(f"\nSaved to {out_file}")
        print(f"\n  Next: update scheduler/watchlist.py to load this file")
        print(f"        and prioritize these symbols in the daily scan.\n")
    else:
        print(f"\n  [dry-run] Results not saved.\n")


if __name__ == "__main__":
    main()
