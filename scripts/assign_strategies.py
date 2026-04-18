"""
Strategy Assignment Sweep — find the best strategy per symbol using Kite data.

Runs all active strategies against the top 25 fundamentally ranked NIFTY50
stocks using 60-minute Kite Connect historical data (up to 400 days).  The
best-performing strategy per symbol is written to config/param_history.json
under the "strategy_assignment" key so the live bot picks it up automatically.

Data source priority:
  1. Kite Connect 60-minute bars (real NSE data, up to 400 days)
  2. yfinance 1-hour bars (fallback when Kite is unavailable / not authenticated)

Scoring: composite_score = Sharpe × (win_rate / 50)
  — Sharpe alone rewards high-variance strategies; win_rate normalises for that.
  — 50% is the neutral win rate (equivalent to random).

Quality gate: strategy is only eligible if num_trades >= MIN_TRADES (default 15).
  — Fewer trades = overfitting risk; assigned strategy defaults to ema_crossover.

Usage:
    python scripts/assign_strategies.py                     # top 25 by fundamentals
    python scripts/assign_strategies.py --top 30            # wider universe
    python scripts/assign_strategies.py --symbol INFY       # single symbol only
    python scripts/assign_strategies.py --days 200          # shorter lookback
    python scripts/assign_strategies.py --dry-run           # print results, don't save
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from backtesting.engine import BacktestEngine
from backtesting.performance import calculate
from strategies.bb_mean_reversion import BBMeanReversionStrategy
from strategies.ema_crossover import EMACrossoverStrategy
from strategies.opening_range_breakout import ORBStrategy
from strategies.rsi_macd_combo import RSIMACDStrategy
from strategies.trend_rider import TrendRiderStrategy
from strategies.vwap_bounce import VWAPBounceStrategy

HISTORY_FILE = Path("config/param_history.json")
MIN_TRADES   = 15       # minimum trades needed to trust the assignment
KITE_DAYS    = 380      # ~400 days of 60-min data from Kite (leaves margin)
RATE_LIMIT_S = 0.35     # ~3 req/sec — stays under Kite's historical API limit

STRATEGY_MAP = {
    "ema_crossover":          EMACrossoverStrategy,
    "rsi_macd_combo":         RSIMACDStrategy,
    "opening_range_breakout": ORBStrategy,
    "vwap_bounce":            VWAPBounceStrategy,
    "trend_rider":            TrendRiderStrategy,
    "bb_mean_reversion":      BBMeanReversionStrategy,
}

DEFAULT_STRATEGY = "ema_crossover"


# ── Data fetching ─────────────────────────────────────────────────────────────

def _fetch_ohlcv_for_sweep(symbol: str, days: int) -> "pd.DataFrame | None":
    """
    Fetch OHLCV data for backtest sweep.

    Tries Kite 60-min data first (real NSE prices, up to 400 days).
    Falls back to yfinance 1-hour data if Kite is unavailable.
    Returns None when both sources fail.
    """
    import pandas as pd

    # 1. Try Kite Connect
    try:
        from data.kite_feed import fetch_kite_ohlcv
        df = fetch_kite_ohlcv(symbol, days=days, interval="60minute")
        if df is not None and len(df) >= 50:
            logger.info(f"{symbol}: {len(df)} 60-min candles from Kite")
            return df
    except Exception as exc:
        logger.debug(f"{symbol}: Kite fetch failed — {exc}")

    # 2. Fallback: yfinance hourly
    try:
        from data.historical import fetch_ohlcv
        end   = date.today().isoformat()
        start = (date.today() - timedelta(days=days)).isoformat()
        # fetch_ohlcv uses yfinance symbol format (SYMBOL.NS)
        from data.instruments import KITE_TO_YF
        yf_sym = KITE_TO_YF.get(symbol, f"{symbol}.NS")
        import yfinance as yf
        df = yf.download(yf_sym, start=start, end=end, interval="1h", progress=False, auto_adjust=True)
        if df is not None and len(df) >= 50:
            df.columns = [c.lower() for c in df.columns]
            df.index.name = "datetime"
            logger.info(f"{symbol}: {len(df)} 1-hour candles from yfinance (fallback)")
            return df
    except Exception as exc:
        logger.debug(f"{symbol}: yfinance fallback failed — {exc}")

    logger.warning(f"{symbol}: no data from Kite or yfinance — skipping")
    return None


# ── Scoring ───────────────────────────────────────────────────────────────────

def _composite_score(sharpe: float, win_rate_pct: float, num_trades: int) -> float:
    """
    Composite score used to rank strategies for a symbol.

    Sharpe alone rewards high-variance outliers.  Multiplying by win_rate/50
    penalises lucky-few-big-wins strategies and rewards consistent ones.
    num_trades < MIN_TRADES returns -inf so the quality gate eliminates them.
    """
    if num_trades < MIN_TRADES:
        return float("-inf")
    return max(sharpe, 0.0) * (win_rate_pct / 50.0)


# ── Per-symbol sweep ──────────────────────────────────────────────────────────

def sweep_symbol(symbol: str, df: "pd.DataFrame", start: str, end: str, capital: float) -> dict:
    """
    Run all strategies against *df* for *symbol*.  Returns a results dict:
      { strategy_name: {"sharpe": ..., "win_rate": ..., "num_trades": ..., "score": ...} }
    """
    results: dict[str, dict] = {}

    for strat_name, StratClass in STRATEGY_MAP.items():
        try:
            strategy = StratClass()
            engine   = BacktestEngine(strategy, initial_capital=capital)
            result   = engine.run(symbol, start=start, end=end)
            metrics  = calculate(result)
            score    = _composite_score(metrics.sharpe_ratio, metrics.win_rate_pct, metrics.num_trades)
            results[strat_name] = {
                "sharpe":     round(metrics.sharpe_ratio, 3),
                "win_rate":   round(metrics.win_rate_pct, 1),
                "num_trades": metrics.num_trades,
                "score":      round(score, 4),
            }
            logger.debug(
                f"  {symbol} | {strat_name:<28} trades={metrics.num_trades:>3} "
                f"win={metrics.win_rate_pct:>5.1f}% sharpe={metrics.sharpe_ratio:>5.2f} "
                f"score={score:>6.3f}"
            )
        except Exception as exc:
            logger.warning(f"  {symbol} | {strat_name}: backtest failed — {exc}")
            results[strat_name] = {"sharpe": 0.0, "win_rate": 0.0, "num_trades": 0, "score": float("-inf")}

    return results


def pick_best(results: dict[str, dict]) -> tuple[str, dict]:
    """Return (strategy_name, metrics) for the highest-scoring eligible strategy."""
    best_name  = DEFAULT_STRATEGY
    best_score = float("-inf")
    best_meta  = results.get(DEFAULT_STRATEGY, {})

    for name, meta in results.items():
        if meta["score"] > best_score:
            best_score = meta["score"]
            best_name  = name
            best_meta  = meta

    # If no strategy cleared the MIN_TRADES gate, fall back to default
    if best_score == float("-inf"):
        best_name = DEFAULT_STRATEGY
        best_meta = results.get(DEFAULT_STRATEGY, {})

    return best_name, best_meta


# ── Save / load assignments ───────────────────────────────────────────────────

def load_history() -> dict:
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_assignment(symbol: str, strategy: str, meta: dict, dry_run: bool) -> None:
    data = load_history()
    data.setdefault("strategy_assignment", {})[symbol] = {
        "strategy":    strategy,
        "score":       meta.get("score", 0.0),
        "sharpe":      meta.get("sharpe", 0.0),
        "win_rate":    meta.get("win_rate", 0.0),
        "num_trades":  meta.get("num_trades", 0),
        "assigned_at": date.today().isoformat(),
    }
    if dry_run:
        logger.info(f"[dry-run] Would save: {symbol} → {strategy} (score={meta.get('score', 0):.3f})")
        return
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ── Universe selection ────────────────────────────────────────────────────────

def get_sweep_universe(top_n: int) -> list[str]:
    """
    Return top *top_n* NIFTY50 symbols by fundamental score.
    Falls back to the static first-N order if scoring fails.
    """
    from data.instruments import NIFTY50_INSTRUMENTS
    try:
        from analysis.fundamental_selector import select_fundamental_watchlist
        symbols, _ = select_fundamental_watchlist(top_n)
        if symbols:
            return symbols
    except Exception as exc:
        logger.warning(f"Fundamental selector failed: {exc} — using static order")
    return [i.kite_symbol for i in NIFTY50_INSTRUMENTS[:top_n]]


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strategy Assignment Sweep — find best strategy per symbol",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--top",     default=25,  type=int,   help="Number of top fundamental stocks to sweep (default: 25)")
    parser.add_argument("--symbol",  default=None,            help="Single symbol to sweep (overrides --top)")
    parser.add_argument("--days",    default=KITE_DAYS, type=int, help=f"Lookback days for data (default: {KITE_DAYS})")
    parser.add_argument("--capital", default=100_000, type=float, help="Backtest capital in INR (default: 100000)")
    parser.add_argument("--dry-run", action="store_true",     help="Print results but do not write to param_history.json")
    args = parser.parse_args()

    end_date   = date.today().isoformat()
    start_date = (date.today() - timedelta(days=args.days)).isoformat()

    symbols = [args.symbol.upper()] if args.symbol else get_sweep_universe(args.top)

    print(f"\n{'='*70}")
    print(f"  Strategy Assignment Sweep")
    print(f"  Universe : {len(symbols)} symbols")
    print(f"  Period   : {start_date} → {end_date} ({args.days} days)")
    print(f"  Min trades gate : {MIN_TRADES}")
    print(f"  Dry run  : {args.dry_run}")
    print(f"{'='*70}\n")

    summary: list[tuple[str, str, dict]] = []

    for i, symbol in enumerate(symbols, 1):
        print(f"[{i:>2}/{len(symbols)}] {symbol} — fetching data...")
        df = _fetch_ohlcv_for_sweep(symbol, args.days)
        if df is None:
            print(f"       SKIP (no data)\n")
            continue

        time.sleep(RATE_LIMIT_S)  # respect Kite rate limit after historical fetch

        print(f"       Running {len(STRATEGY_MAP)} strategies...")
        results  = sweep_symbol(symbol, df, start_date, end_date, args.capital)
        best_name, best_meta = pick_best(results)
        save_assignment(symbol, best_name, best_meta, args.dry_run)
        summary.append((symbol, best_name, best_meta))

        marker = "✅" if best_meta.get("num_trades", 0) >= MIN_TRADES else "⚠️ (low trades)"
        print(
            f"       → {best_name:<28} "
            f"trades={best_meta.get('num_trades', 0):>3} "
            f"win={best_meta.get('win_rate', 0):>5.1f}% "
            f"score={best_meta.get('score', 0):>6.3f} {marker}\n"
        )

    # Summary table
    print(f"\n{'='*70}")
    print(f"  {'Symbol':<14} {'Strategy':<28} {'Trades':>6} {'Win%':>6} {'Score':>7}")
    print(f"  {'─'*60}")
    for sym, strat, meta in summary:
        print(
            f"  {sym:<14} {strat:<28} "
            f"{meta.get('num_trades', 0):>6} "
            f"{meta.get('win_rate', 0):>5.1f}% "
            f"{meta.get('score', 0):>7.3f}"
        )

    if not args.dry_run:
        print(f"\n  Saved to {HISTORY_FILE}")
        print(f"  Bot will pick up assignments on next restart.\n")
    else:
        print(f"\n  [dry-run] Nothing written to disk.\n")


if __name__ == "__main__":
    main()
