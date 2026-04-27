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

Quality gate: strategy is only eligible if num_trades >= MIN_TRADES (default 10).
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
import csv
import json
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from execution.optimizer_log import init_optimizer_log, save_run as _log_run
from backtesting.engine import BacktestEngine
from backtesting.performance import calculate
from strategies.bb_mean_reversion import BBMeanReversionStrategy
from strategies.ema_crossover import EMACrossoverStrategy
from strategies.opening_range_breakout import ORBStrategy
from strategies.rsi_macd_combo import RSIMACDStrategy
from strategies.trend_rider import TrendRiderStrategy
from strategies.vwap_bounce import VWAPBounceStrategy

HISTORY_FILE   = Path("config/param_history.json")
APPROVED_FILE  = Path("config/approved_symbols.json")
MIN_TRADES          = 10   # minimum trades needed to trust the assignment
KITE_DAYS           = 380  # ~400 days of 60-min data from Kite (leaves margin)
RATE_LIMIT_S        = 0.35 # ~3 req/sec — stays under Kite's historical API limit
LOCK_DAYS           = 7    # approved_symbols.json valid for 7 days
MIN_APPROVED_SCORE  = 0.3  # symbols must score above this to enter the approved universe
CACHE_TTL_HOURS     = 12   # re-download OHLCV after this many hours
CACHE_DIR           = Path("cache/ohlcv")

STRATEGY_MAP = {
    "ema_crossover":          EMACrossoverStrategy,
    "rsi_macd_combo":         RSIMACDStrategy,
    "opening_range_breakout": ORBStrategy,
    "vwap_bounce":            VWAPBounceStrategy,
    "trend_rider":            TrendRiderStrategy,
    "bb_mean_reversion":      BBMeanReversionStrategy,
}

# ── Concurrency locks ─────────────────────────────────────────────────────────
_json_lock  = threading.Lock()   # protects param_history.json + approved_symbols.json
_kite_lock  = threading.Lock()   # serialises Kite fetches so rate limit is respected
_print_lock = threading.Lock()   # prevents interleaved stdout from parallel workers

DEFAULT_STRATEGY = "ema_crossover"


# ── Data fetching ─────────────────────────────────────────────────────────────

def _cache_path(symbol: str, days: int) -> Path:
    return CACHE_DIR / f"{symbol}_{days}d.parquet"


def _load_cached_ohlcv(symbol: str, days: int) -> "pd.DataFrame | None":
    """Return cached OHLCV DataFrame if it exists and is fresh, else None."""
    import pandas as pd
    path = _cache_path(symbol, days)
    if path.exists():
        age_h = (time.time() - path.stat().st_mtime) / 3600
        if age_h < CACHE_TTL_HOURS:
            try:
                df = pd.read_parquet(path)
                logger.debug(f"{symbol}: {len(df)} rows from cache ({age_h:.1f}h old)")
                return df
            except Exception:
                pass
    return None


def _save_cached_ohlcv(symbol: str, days: int, df: "pd.DataFrame") -> None:
    """Persist OHLCV to disk cache."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(_cache_path(symbol, days))
    except Exception as exc:
        logger.debug(f"{symbol}: cache write failed — {exc}")


def _fetch_ohlcv_for_sweep(symbol: str, days: int) -> "pd.DataFrame | None":
    """
    Fetch OHLCV data for backtest sweep.

    Checks disk cache first (TTL = CACHE_TTL_HOURS).
    Tries Kite 60-min data next (real NSE prices, up to 400 days).
    Falls back to yfinance 1-hour data if Kite is unavailable.
    Returns None when all sources fail.
    """
    import pandas as pd

    # 0. Disk cache — skip the network entirely on re-runs
    cached = _load_cached_ohlcv(symbol, days)
    if cached is not None:
        return cached

    # 1. Try Kite Connect
    df = None
    try:
        from data.kite_feed import fetch_kite_ohlcv
        df = fetch_kite_ohlcv(symbol, days=days, interval="60minute")
        if df is not None and len(df) >= 50:
            logger.info(f"{symbol}: {len(df)} 60-min candles from Kite")
    except Exception as exc:
        logger.debug(f"{symbol}: Kite fetch failed — {exc}")

    # 2. Fallback: yfinance hourly
    if df is None or len(df) < 50:
        try:
            end   = date.today().isoformat()
            start = (date.today() - timedelta(days=days)).isoformat()
            from data.instruments import KITE_TO_YF
            yf_sym = KITE_TO_YF.get(symbol, f"{symbol}.NS")
            import yfinance as yf
            df = yf.download(yf_sym, start=start, end=end, interval="1h", progress=False, auto_adjust=True)
            if df is not None and len(df) >= 50:
                df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
                df.index.name = "datetime"
                logger.info(f"{symbol}: {len(df)} 1-hour candles from yfinance (fallback)")
        except Exception as exc:
            logger.debug(f"{symbol}: yfinance fallback failed — {exc}")
            df = None

    if df is None or len(df) < 50:
        logger.warning(f"{symbol}: no data from Kite or yfinance — skipping")
        return None

    _save_cached_ohlcv(symbol, days, df)
    return df


# ── Scoring ───────────────────────────────────────────────────────────────────

def _composite_score(sharpe: float, win_rate_pct: float, num_trades: int) -> float:
    """
    Composite score used to rank strategies for a symbol.

    Sharpe alone rewards high-variance outliers.  Multiplying by win_rate/50
    penalises lucky-few-big-wins strategies and rewards consistent ones.
    num_trades < MIN_TRADES returns -inf so the quality gate eliminates them.
    (MIN_TRADES = 10)
    """
    if num_trades < MIN_TRADES:
        return float("-inf")
    return sharpe * (win_rate_pct / 50.0)


# ── Per-symbol sweep ──────────────────────────────────────────────────────────

def sweep_symbol(symbol: str, df: "pd.DataFrame", start: str, end: str, capital: float) -> dict:
    """
    Run all 6 strategies against *df* for *symbol* in parallel.

    Returns: { strategy_name: {"sharpe": ..., "win_rate": ..., "num_trades": ..., "score": ...} }

    Thread safety: regime_detector uses threading.local() so each thread maintains
    its own backtest flag — no cross-thread interference.
    """
    results: dict[str, dict] = {}

    def _run_one(strat_name: str, StratClass) -> tuple[str, dict]:
        strategy = StratClass()
        engine   = BacktestEngine(strategy, initial_capital=capital)
        result   = engine.run(symbol, start=start, end=end, df=df)
        metrics  = calculate(result)
        score    = _composite_score(metrics.sharpe_ratio, metrics.win_rate_pct, metrics.num_trades)
        meta = {
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
        return strat_name, meta

    with ThreadPoolExecutor(max_workers=len(STRATEGY_MAP)) as inner_pool:
        futures = {inner_pool.submit(_run_one, name, cls): name
                   for name, cls in STRATEGY_MAP.items()}
        for fut in as_completed(futures):
            strat_name = futures[fut]
            try:
                name, meta = fut.result()
                results[name] = meta
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
    with _json_lock:
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}


def save_assignment(symbol: str, strategy: str, meta: dict, dry_run: bool) -> None:
    if dry_run:
        logger.info(f"[dry-run] Would save: {symbol} → {strategy} (score={meta.get('score', 0):.3f})")
        return
    with _json_lock:
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE) as f:
                    data = json.load(f)
            except Exception:
                data = {}
        else:
            data = {}
        data.setdefault("strategy_assignment", {})[symbol] = {
            "strategy":    strategy,
            "score":       meta.get("score", 0.0),
            "sharpe":      meta.get("sharpe", 0.0),
            "win_rate":    meta.get("win_rate", 0.0),
            "num_trades":  meta.get("num_trades", 0),
            "assigned_at": date.today().isoformat(),
        }
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(HISTORY_FILE, "w") as f:
            json.dump(data, f, indent=2)


def save_approved_symbols(summary: list[tuple[str, str, dict]], dry_run: bool) -> None:
    """Write approved_symbols.json with the locked universe for the next LOCK_DAYS days."""
    qualified = [
        (sym, strat, meta) for sym, strat, meta in summary
        if meta.get("score", 0.0) > MIN_APPROVED_SCORE
    ]
    if len(qualified) < 3:
        logger.warning(
            f"Only {len(qualified)} symbol(s) passed MIN_APPROVED_SCORE={MIN_APPROVED_SCORE} "
            f"gate — market conditions may be unfavourable for the current strategy set."
        )
    approved = {
        "week_of":      date.today().isoformat(),
        "generated_at": date.today().isoformat(),
        "expires":      (date.today() + timedelta(days=LOCK_DAYS)).isoformat(),
        "symbols": [
            {
                "symbol":        sym,
                "strategy":      strat,
                "sharpe":        meta.get("sharpe", 0.0),
                "win_rate":      meta.get("win_rate", 0.0),
                "num_trades":    meta.get("num_trades", 0),
                "score":         meta.get("score", 0.0),
            }
            for sym, strat, meta in qualified
        ],
    }
    if dry_run:
        logger.info(
            f"[dry-run] Would write {APPROVED_FILE} with {len(qualified)}/{len(summary)} "
            f"qualified symbols (score > {MIN_APPROVED_SCORE})"
        )
        return
    APPROVED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(APPROVED_FILE, "w") as f:
        json.dump(approved, f, indent=2)
    logger.success(
        f"Saved approved universe ({len(qualified)}/{len(summary)} symbols qualified) "
        f"→ {APPROVED_FILE} (expires {approved['expires']})"
    )


def _run_optimizer(symbol: str, strategy: str, n_trials: int = 50) -> bool:
    """Run Bayesian optimizer for strategy on symbol. Returns True if improvement saved."""
    try:
        from learning.param_optimizer import ParamOptimizer
        optimizer = ParamOptimizer()
        method_map = {
            "ema_crossover":          optimizer.optimize_ema_crossover,
            "rsi_macd_combo":         optimizer.optimize_rsi_macd_combo,
            "opening_range_breakout": optimizer.optimize_opening_range_breakout,
            "vwap_bounce":            optimizer.optimize_vwap_bounce,
            "trend_rider":            optimizer.optimize_trend_rider,
            "bb_mean_reversion":      optimizer.optimize_bb_mean_reversion,
        }
        fn = method_map.get(strategy)
        if fn is None:
            return False
        return fn(symbol, n_trials=n_trials) is not None
    except Exception as exc:
        logger.warning(f"  {symbol}/{strategy}: optimizer failed — {exc}")
        return False


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


# ── CSV log ───────────────────────────────────────────────────────────────────

LOG_DIR = Path("logs")

def _save_csv_log(summary: list[tuple[str, str, dict]], lookback_days: int) -> None:
    """Write logs/optimizer_YYYY-MM-DD.csv with this run's full results."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"optimizer_{date.today().isoformat()}.csv"
    with open(log_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["run_date", "symbol", "strategy", "num_trades", "win_rate", "sharpe", "score", "lookback_days"])
        for sym, strat, meta in summary:
            writer.writerow([
                date.today().isoformat(),
                sym,
                strat,
                meta.get("num_trades", 0),
                meta.get("win_rate", 0.0),
                meta.get("sharpe", 0.0),
                meta.get("score", 0.0),
                lookback_days,
            ])
    logger.success(f"CSV log saved → {log_path}")


# ── Per-symbol worker (runs in thread pool) ───────────────────────────────────

def _process_symbol(
    symbol: str,
    i: int,
    total: int,
    start_date: str,
    end_date: str,
    capital: float,
    days: int,
    optimize: bool,
    dry_run: bool,
    n_trials: int = 25,
) -> "tuple[str, str, dict] | None":
    """Fetch, sweep, optionally optimize, save, and log one symbol. Thread-safe."""
    with _print_lock:
        print(f"[{i:>2}/{total}] {symbol} — fetching data...")

    # Cached symbols skip the network entirely; only live fetches need the rate-limit delay.
    from_cache = _load_cached_ohlcv(symbol, days) is not None
    with _kite_lock:
        df = _fetch_ohlcv_for_sweep(symbol, days)
        if not from_cache:
            time.sleep(RATE_LIMIT_S)

    if df is None:
        with _print_lock:
            print(f"[{i:>2}/{total}] {symbol} — SKIP (no data)\n")
        return None

    results   = sweep_symbol(symbol, df, start_date, end_date, capital)
    best_name, best_meta = pick_best(results)
    save_assignment(symbol, best_name, best_meta, dry_run)  # uses _json_lock internally

    improved = False
    if optimize and best_meta.get("score", 0.0) > MIN_APPROVED_SCORE:
        with _print_lock:
            print(f"[{i:>2}/{total}] {symbol} — optimizing {best_name} ({n_trials} trials)...")
        improved = _run_optimizer(symbol, best_name, n_trials=n_trials)
        with _print_lock:
            status = "✅ improved" if improved else "ℹ️  no gain"
            print(f"[{i:>2}/{total}] {symbol} — optimizer: {status}")

    if not dry_run:
        _log_run(
            symbol=symbol,
            strategy=best_name,
            num_trades=best_meta.get("num_trades", 0),
            win_rate=best_meta.get("win_rate", 0.0),
            sharpe=best_meta.get("sharpe", 0.0),
            score=best_meta.get("score", 0.0),
            optimized=improved,
            lookback_days=days,
        )

    marker = "✅" if best_meta.get("num_trades", 0) >= MIN_TRADES else "⚠️ (low trades)"
    with _print_lock:
        print(
            f"[{i:>2}/{total}] {symbol} → {best_name:<28} "
            f"trades={best_meta.get('num_trades', 0):>3} "
            f"win={best_meta.get('win_rate', 0):>5.1f}% "
            f"score={best_meta.get('score', 0):>6.3f} {marker}\n"
        )

    return symbol, best_name, best_meta


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strategy Assignment Sweep — find best strategy per symbol",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--top",      default=25,  type=int,   help="Number of top fundamental stocks to sweep (default: 25)")
    parser.add_argument("--symbol",   default=None,            help="Single symbol to sweep (overrides --top)")
    parser.add_argument("--days",     default=KITE_DAYS, type=int, help=f"Lookback days for data (default: {KITE_DAYS})")
    parser.add_argument("--capital",  default=100_000, type=float, help="Backtest capital in INR (default: 100000)")
    parser.add_argument("--optimize", action="store_true",     help="Run Bayesian optimizer on approved symbols after sweep")
    parser.add_argument("--trials",   default=25, type=int,    help="Bayesian optimizer trials per symbol (default: 25)")
    parser.add_argument("--fast",     action="store_true",     help="Quick sweep: 120-day lookback + 10 optimizer trials (good for mid-week checks)")
    parser.add_argument("--dry-run",  action="store_true",     help="Print results but do not write to param_history.json or approved_symbols.json")
    parser.add_argument("--workers",  default=8, type=int,     help="Parallel worker threads for sweep (default: 8; set 1 to disable)")
    args = parser.parse_args()

    if args.fast:
        args.days   = min(args.days, 120)
        args.trials = min(args.trials, 10)

    end_date   = date.today().isoformat()
    start_date = (date.today() - timedelta(days=args.days)).isoformat()

    symbols = [args.symbol.upper()] if args.symbol else get_sweep_universe(args.top)

    mode_tag = "[FAST]" if args.fast else ""
    print(f"\n{'='*70}")
    print(f"  Weekend Review — Strategy Assignment Sweep {mode_tag}")
    print(f"  Universe : {len(symbols)} symbols")
    print(f"  Period   : {start_date} → {end_date} ({args.days} days)")
    print(f"  Optimize : {args.optimize} ({args.trials} trials, approved symbols only)")
    print(f"  Workers  : {args.workers} symbol threads × 6 strategy threads each")
    print(f"  Min score to approve : {MIN_APPROVED_SCORE}")
    print(f"  Dry run  : {args.dry_run}")
    print(f"{'='*70}\n")

    if not args.dry_run:
        init_optimizer_log()

    # Run per-symbol work in parallel; collect results in original symbol order
    raw_results: dict[str, tuple[str, str, dict]] = {}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                _process_symbol,
                sym, i, len(symbols),
                start_date, end_date,
                args.capital, args.days,
                args.optimize, args.dry_run,
                args.trials,
            ): sym
            for i, sym in enumerate(symbols, 1)
        }
        for fut in as_completed(futures):
            result = fut.result()
            if result is not None:
                sym, best_name, best_meta = result
                raw_results[sym] = (sym, best_name, best_meta)

    # Preserve original symbol ordering in summary table
    summary: list[tuple[str, str, dict]] = [
        raw_results[sym] for sym in symbols if sym in raw_results
    ]

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

    # Save approved universe (valid for LOCK_DAYS days)
    save_approved_symbols(summary, args.dry_run)

    if not args.dry_run:
        _save_csv_log(summary, args.days)
        print(f"\n  Saved to {HISTORY_FILE}")
        print(f"  Approved universe locked → {APPROVED_FILE} (expires in {LOCK_DAYS} days)")
        print(f"  Bot will use ONLY these symbols and strategies until next weekend review.\n")
    else:
        print(f"\n  [dry-run] Nothing written to disk.\n")


if __name__ == "__main__":
    main()
