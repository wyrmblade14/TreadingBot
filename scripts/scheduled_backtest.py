"""
Weekly scheduled backtest — runs every Saturday at 10:00 IST.

For each of the top-10 fundamentally-ranked NIFTY50 symbols, runs all 5
strategies over the past 90 days. If any strategy's win rate drops below 40%
or profit factor drops below 1.0, sends a Telegram alert.

Results are saved to logs/backtest_weekly_YYYY-MM-DD.json for trend tracking.

Usage:
    python scripts/scheduled_backtest.py           # normal run
    python scripts/scheduled_backtest.py --symbols RELIANCE TCS --days 30
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backtesting.engine import BacktestEngine
from backtesting.performance import PerformanceMetrics
from strategies.ema_crossover import EMACrossoverStrategy
from strategies.rsi_macd import RSIMACDStrategy
from strategies.opening_range_breakout import ORBStrategy
from strategies.bb_mean_reversion import BBMeanReversionStrategy
from strategies.vwap_bounce import VWAPBounceStrategy
from scheduler.watchlist import static_watchlist

STRATEGY_MAP: dict[str, type] = {
    "ema_crossover":          EMACrossoverStrategy,
    "rsi_macd_combo":         RSIMACDStrategy,
    "opening_range_breakout": ORBStrategy,
    "bb_mean_reversion":      BBMeanReversionStrategy,
    "vwap_bounce":            VWAPBounceStrategy,
}

# Alert thresholds
MIN_WIN_RATE     = 0.40   # 40 %
MIN_PROFIT_FACTOR = 1.0

BASELINE_FILE = ROOT / "logs" / "backtest_baseline.json"
RESULTS_DIR   = ROOT / "logs"


def _send_alert(msg: str) -> None:
    try:
        from notifications.telegram_notifier import TelegramNotifier
        TelegramNotifier().send_message(msg)
    except Exception:
        pass


def _load_baseline() -> dict:
    if BASELINE_FILE.exists():
        try:
            return json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_baseline(data: dict) -> None:
    BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_weekly(symbols: list[str], lookback_days: int = 90) -> None:
    end   = date.today().strftime("%Y-%m-%d")
    start = (date.today() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    print(f"\nWeekly backtest  |  {start} → {end}  |  {len(symbols)} symbols")
    print("=" * 72)

    baseline = _load_baseline()
    results: dict[str, dict] = {}
    alerts: list[str] = []

    for strategy_name, StrategyClass in STRATEGY_MAP.items():
        strat_wins:   list[float] = []
        strat_pf:     list[float] = []
        strat_trades: int         = 0

        for symbol in symbols:
            try:
                strategy = StrategyClass()
                engine   = BacktestEngine(strategy, initial_capital=1_00_000.0)
                result   = engine.run(symbol, start=start, end=end)
                metrics  = PerformanceMetrics(result)

                win_rate      = metrics.win_rate()
                profit_factor = metrics.profit_factor()
                n_trades      = len(result.trades)

                if n_trades > 0:
                    strat_wins.append(win_rate)
                    strat_pf.append(profit_factor)
                    strat_trades += n_trades
            except Exception as exc:
                print(f"  ⚠ {symbol}/{strategy_name}: {exc}")

        avg_win_rate     = sum(strat_wins)     / len(strat_wins)     if strat_wins else 0.0
        avg_profit_factor = sum(strat_pf)      / len(strat_pf)       if strat_pf   else 0.0

        status = "✅" if avg_win_rate >= MIN_WIN_RATE and avg_profit_factor >= MIN_PROFIT_FACTOR else "⚠️"
        print(
            f"{status}  {strategy_name:<26}  "
            f"Win {avg_win_rate*100:5.1f}%  "
            f"PF {avg_profit_factor:.2f}  "
            f"Trades {strat_trades}"
        )

        results[strategy_name] = {
            "win_rate":      round(avg_win_rate, 4),
            "profit_factor": round(avg_profit_factor, 4),
            "trades":        strat_trades,
        }

        # Compare vs baseline
        prev = baseline.get(strategy_name, {})
        degraded = []
        if avg_win_rate < MIN_WIN_RATE:
            degraded.append(f"win rate {avg_win_rate*100:.1f}% < {MIN_WIN_RATE*100:.0f}%")
        if avg_profit_factor < MIN_PROFIT_FACTOR:
            degraded.append(f"profit factor {avg_profit_factor:.2f} < {MIN_PROFIT_FACTOR:.1f}")
        if degraded:
            prev_wr = prev.get("win_rate", "n/a")
            alerts.append(
                f"⚠️ {strategy_name}: {', '.join(degraded)} "
                f"(prev win rate: {prev_wr})"
            )

    print("=" * 72)

    # Persist results
    out_file = RESULTS_DIR / f"backtest_weekly_{date.today()}.json"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps({
        "date": date.today().isoformat(),
        "period": f"{start} to {end}",
        "symbols": symbols,
        "strategies": results,
    }, indent=2), encoding="utf-8")
    print(f"\nResults saved → {out_file.name}")

    # Update baseline with current results
    _save_baseline(results)

    # Send Telegram alerts
    if alerts:
        msg = "📉 Weekly backtest degradation detected:\n" + "\n".join(alerts)
        print(f"\n{msg}")
        _send_alert(msg)
    else:
        summary = f"✅ Weekly backtest OK — all strategies healthy ({start} to {end})"
        print(f"\n{summary}")
        _send_alert(summary)


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly scheduled backtest")
    parser.add_argument("--symbols", nargs="+", default=None,
                        help="Symbols to test (default: top-10 fundamental watchlist)")
    parser.add_argument("--days", type=int, default=90,
                        help="Lookback period in days (default: 90)")
    args = parser.parse_args()

    if args.symbols:
        symbols = [s.upper() for s in args.symbols]
    else:
        # Fall back to static watchlist if fundamentals unavailable
        try:
            from analysis.fundamental_selector import select_fundamental_watchlist
            symbols, _ = select_fundamental_watchlist(10)
        except Exception:
            symbols = static_watchlist(10)

    run_weekly(symbols, lookback_days=args.days)


if __name__ == "__main__":
    main()
