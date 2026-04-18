"""
Parameter Optimizer — Bayesian search for best strategy parameters.

How it works:
  1. Measures the baseline performance of a strategy with current parameters
     over the last 30 days of market data.
  2. Uses Optuna (Bayesian optimization) to search for better parameters
     by running hundreds of backtests in parallel.
  3. If a set of parameters is found that improves the Sharpe Ratio by
     more than 10%, it saves those parameters to config/param_history.json.
  4. The bot automatically loads these overrides at startup.

Why Bayesian?
  Grid search (trying every combination) is too slow. Optuna uses probability
  to focus only on the most promising parameter zones, finding the best
  settings 10–20× faster than grid search.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

import optuna
from loguru import logger

from backtesting.engine import BacktestEngine
from backtesting.performance import calculate
from config.strategies import STRATEGY_CONFIGS
from strategies.bb_mean_reversion import BBMeanReversionStrategy
from strategies.ema_crossover import EMACrossoverStrategy
from strategies.opening_range_breakout import ORBStrategy
from strategies.rsi_macd_combo import RSIMACDStrategy
from strategies.trend_rider import TrendRiderStrategy
from strategies.vwap_bounce import VWAPBounceStrategy

# ── Configuration ─────────────────────────────────────────────────────

HISTORY_FILE = Path("config/param_history.json")
OPTIMIZATION_DAYS = 30   # look back 30 days for optimization
MIN_SAMPLES = 5          # need at least 5 trades to trust a parameter set
SHARPE_IMPROVEMENT_THRESHOLD = 1.10  # 10% improvement needed to apply

# ── Optimization Logic ────────────────────────────────────────────────

class ParamOptimizer:
    """
    Finds optimal parameters for strategies using historical data.
    """

    def __init__(self, initial_capital: float = 100_000.0) -> None:
        self.initial_capital = initial_capital
        self.end_date   = date.today().isoformat()
        self.start_date = (date.today() - timedelta(days=OPTIMIZATION_DAYS)).isoformat()

    def optimize_ema_crossover(self, symbol: str, n_trials: int = 50) -> dict | None:
        """
        Run Bayesian optimization for the EMA Crossover strategy.
        """
        logger.info(f"Optimizing EMA Crossover for {symbol} | trials={n_trials}")

        # 1. Establish baseline
        baseline_params = STRATEGY_CONFIGS["ema_crossover"]
        baseline_strategy = EMACrossoverStrategy(params=baseline_params)
        baseline_engine   = BacktestEngine(baseline_strategy, self.initial_capital)
        baseline_result   = baseline_engine.run(symbol, start=self.start_date, end=self.end_date)
        baseline_metrics  = calculate(baseline_result)
        
        baseline_sharpe = max(0.01, baseline_metrics.sharpe_ratio)
        logger.info(f"Baseline Sharpe: {baseline_sharpe:.2f} ({baseline_metrics.num_trades} trades)")

        # 2. Define the objective function for Optuna
        def objective(trial):
            # Define search space
            params = {
                "short_period":      trial.suggest_int("short_period", 5, 15),
                "long_period":       trial.suggest_int("long_period", 15, 35),
                "trend_period":      50,  # kept static
                "volume_multiplier": trial.suggest_float("volume_multiplier", 1.0, 2.5),
                "supertrend_period": trial.suggest_int("supertrend_period", 7, 21),
                "supertrend_multiplier": trial.suggest_float("supertrend_multiplier", 1.5, 4.5),
                "use_first_candle_filter": True,
            }
            
            # Constraints: short < long
            if params["short_period"] >= params["long_period"]:
                return 0.0

            strategy = EMACrossoverStrategy(params=params)
            engine   = BacktestEngine(strategy, self.initial_capital)
            result   = engine.run(symbol, start=self.start_date, end=self.end_date)
            metrics  = calculate(result)

            # Reward Sharpe ratio, but penalize low trade counts
            if metrics.num_trades < MIN_SAMPLES:
                return 0.0
                
            return metrics.sharpe_ratio

        return self._run_study("ema_crossover", symbol, baseline_params, baseline_sharpe, objective, n_trials)

    def optimize_rsi_macd_combo(self, symbol: str, n_trials: int = 50) -> dict | None:
        """Bayesian optimization for RSI + MACD Combo — structural indicator params only."""
        logger.info(f"Optimizing RSI+MACD Combo for {symbol} | trials={n_trials}")
        baseline_params = STRATEGY_CONFIGS["rsi_macd_combo"].copy()
        baseline_strategy = RSIMACDStrategy(params=baseline_params)
        baseline_engine   = BacktestEngine(baseline_strategy, self.initial_capital)
        baseline_result   = baseline_engine.run(symbol, start=self.start_date, end=self.end_date)
        baseline_metrics  = calculate(baseline_result)
        baseline_sharpe   = max(0.01, baseline_metrics.sharpe_ratio)
        logger.info(f"Baseline Sharpe: {baseline_sharpe:.2f} ({baseline_metrics.num_trades} trades)")

        def objective(trial):
            params = {
                **baseline_params,
                "rsi_period":    trial.suggest_int("rsi_period", 4, 14),
                "macd_fast":     trial.suggest_int("macd_fast", 8, 16),
                "macd_slow":     trial.suggest_int("macd_slow", 20, 32),
                "macd_signal":   trial.suggest_int("macd_signal", 7, 12),
                "vwap_band_pct": trial.suggest_float("vwap_band_pct", 0.002, 0.015),
            }
            if params["macd_fast"] >= params["macd_slow"]:
                return 0.0
            strategy = RSIMACDStrategy(params=params)
            engine   = BacktestEngine(strategy, self.initial_capital)
            result   = engine.run(symbol, start=self.start_date, end=self.end_date)
            metrics  = calculate(result)
            return metrics.sharpe_ratio if metrics.num_trades >= MIN_SAMPLES else 0.0

        return self._run_study("rsi_macd_combo", symbol, baseline_params, baseline_sharpe, objective, n_trials)

    def optimize_opening_range_breakout(self, symbol: str, n_trials: int = 50) -> dict | None:
        """Bayesian optimization for Opening Range Breakout."""
        logger.info(f"Optimizing ORB for {symbol} | trials={n_trials}")
        baseline_params = STRATEGY_CONFIGS["opening_range_breakout"].copy()
        baseline_strategy = ORBStrategy(params=baseline_params)
        baseline_engine   = BacktestEngine(baseline_strategy, self.initial_capital)
        baseline_result   = baseline_engine.run(symbol, start=self.start_date, end=self.end_date)
        baseline_metrics  = calculate(baseline_result)
        baseline_sharpe   = max(0.01, baseline_metrics.sharpe_ratio)
        logger.info(f"Baseline Sharpe: {baseline_sharpe:.2f} ({baseline_metrics.num_trades} trades)")

        def objective(trial):
            params = {
                **baseline_params,
                "orb_duration_minutes":  trial.suggest_int("orb_duration_minutes", 15, 45),
                "volume_multiplier":     trial.suggest_float("volume_multiplier", 1.0, 2.5),
                "supertrend_period":     trial.suggest_int("supertrend_period", 7, 21),
                "supertrend_multiplier": trial.suggest_float("supertrend_multiplier", 1.5, 4.5),
            }
            strategy = ORBStrategy(params=params)
            engine   = BacktestEngine(strategy, self.initial_capital)
            result   = engine.run(symbol, start=self.start_date, end=self.end_date)
            metrics  = calculate(result)
            return metrics.sharpe_ratio if metrics.num_trades >= MIN_SAMPLES else 0.0

        return self._run_study("opening_range_breakout", symbol, baseline_params, baseline_sharpe, objective, n_trials)

    def optimize_vwap_bounce(self, symbol: str, n_trials: int = 50) -> dict | None:
        """Bayesian optimization for VWAP Bounce."""
        logger.info(f"Optimizing VWAP Bounce for {symbol} | trials={n_trials}")
        baseline_params = STRATEGY_CONFIGS.get("vwap_bounce", {}).copy()
        baseline_strategy = VWAPBounceStrategy(params=baseline_params)
        baseline_engine   = BacktestEngine(baseline_strategy, self.initial_capital)
        baseline_result   = baseline_engine.run(symbol, start=self.start_date, end=self.end_date)
        baseline_metrics  = calculate(baseline_result)
        baseline_sharpe   = max(0.01, baseline_metrics.sharpe_ratio)
        logger.info(f"Baseline Sharpe: {baseline_sharpe:.2f} ({baseline_metrics.num_trades} trades)")

        def objective(trial):
            params = {
                **baseline_params,
                "rsi_period":         trial.suggest_int("rsi_period", 4, 14),
                "vwap_tolerance_pct": trial.suggest_float("vwap_tolerance_pct", 0.001, 0.008),
                "volume_multiplier":  trial.suggest_float("volume_multiplier", 1.0, 2.0),
            }
            strategy = VWAPBounceStrategy(params=params)
            engine   = BacktestEngine(strategy, self.initial_capital)
            result   = engine.run(symbol, start=self.start_date, end=self.end_date)
            metrics  = calculate(result)
            return metrics.sharpe_ratio if metrics.num_trades >= MIN_SAMPLES else 0.0

        return self._run_study("vwap_bounce", symbol, baseline_params, baseline_sharpe, objective, n_trials)

    def optimize_trend_rider(self, symbol: str, n_trials: int = 50) -> dict | None:
        """Bayesian optimization for Trend Rider."""
        logger.info(f"Optimizing Trend Rider for {symbol} | trials={n_trials}")
        baseline_params = STRATEGY_CONFIGS["trend_rider"].copy()
        baseline_strategy = TrendRiderStrategy(params=baseline_params)
        baseline_engine   = BacktestEngine(baseline_strategy, self.initial_capital)
        baseline_result   = baseline_engine.run(symbol, start=self.start_date, end=self.end_date)
        baseline_metrics  = calculate(baseline_result)
        baseline_sharpe   = max(0.01, baseline_metrics.sharpe_ratio)
        logger.info(f"Baseline Sharpe: {baseline_sharpe:.2f} ({baseline_metrics.num_trades} trades)")

        def objective(trial):
            params = {
                **baseline_params,
                "supertrend_period":     trial.suggest_int("supertrend_period", 7, 21),
                "supertrend_multiplier": trial.suggest_float("supertrend_multiplier", 1.5, 4.5),
                "adx_min":               trial.suggest_int("adx_min", 15, 35),
                "adx_period":            trial.suggest_int("adx_period", 10, 20),
                "volume_multiplier":     trial.suggest_float("volume_multiplier", 1.0, 2.0),
            }
            strategy = TrendRiderStrategy(params=params)
            engine   = BacktestEngine(strategy, self.initial_capital)
            result   = engine.run(symbol, start=self.start_date, end=self.end_date)
            metrics  = calculate(result)
            return metrics.sharpe_ratio if metrics.num_trades >= MIN_SAMPLES else 0.0

        return self._run_study("trend_rider", symbol, baseline_params, baseline_sharpe, objective, n_trials)

    def optimize_bb_mean_reversion(self, symbol: str, n_trials: int = 50) -> dict | None:
        """Bayesian optimization for Bollinger Band Mean Reversion."""
        logger.info(f"Optimizing BB Mean Reversion for {symbol} | trials={n_trials}")
        baseline_params = STRATEGY_CONFIGS["bb_mean_reversion"].copy()
        baseline_strategy = BBMeanReversionStrategy(params=baseline_params)
        baseline_engine   = BacktestEngine(baseline_strategy, self.initial_capital)
        baseline_result   = baseline_engine.run(symbol, start=self.start_date, end=self.end_date)
        baseline_metrics  = calculate(baseline_result)
        baseline_sharpe   = max(0.01, baseline_metrics.sharpe_ratio)
        logger.info(f"Baseline Sharpe: {baseline_sharpe:.2f} ({baseline_metrics.num_trades} trades)")

        def objective(trial):
            params = {
                **baseline_params,
                "bb_period":   trial.suggest_int("bb_period", 10, 30),
                "bb_std_dev":  trial.suggest_float("bb_std_dev", 1.5, 3.0),
                "rsi_period":  trial.suggest_int("rsi_period", 4, 14),
            }
            strategy = BBMeanReversionStrategy(params=params)
            engine   = BacktestEngine(strategy, self.initial_capital)
            result   = engine.run(symbol, start=self.start_date, end=self.end_date)
            metrics  = calculate(result)
            return metrics.sharpe_ratio if metrics.num_trades >= MIN_SAMPLES else 0.0

        return self._run_study("bb_mean_reversion", symbol, baseline_params, baseline_sharpe, objective, n_trials)

    def optimize_all(self, symbol: str, n_trials: int = 30) -> dict[str, dict | None]:
        """
        Run optimization for all 6 strategies for a single symbol.
        Returns a dict mapping strategy name → optimized params (or None if no improvement).
        """
        return {
            "ema_crossover":          self.optimize_ema_crossover(symbol, n_trials),
            "rsi_macd_combo":         self.optimize_rsi_macd_combo(symbol, n_trials),
            "opening_range_breakout": self.optimize_opening_range_breakout(symbol, n_trials),
            "vwap_bounce":            self.optimize_vwap_bounce(symbol, n_trials),
            "trend_rider":            self.optimize_trend_rider(symbol, n_trials),
            "bb_mean_reversion":      self.optimize_bb_mean_reversion(symbol, n_trials),
        }

    def _run_study(
        self,
        strategy_name: str,
        symbol: str,
        baseline_params: dict,
        baseline_sharpe: float,
        objective,
        n_trials: int,
    ) -> dict | None:
        """Shared Optuna study runner + save logic."""
        study = optuna.create_study(direction="maximize")
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study.optimize(objective, n_trials=n_trials)

        best_sharpe = study.best_value
        if best_sharpe > baseline_sharpe * SHARPE_IMPROVEMENT_THRESHOLD:
            logger.success(
                f"{strategy_name} | {symbol}: Sharpe {baseline_sharpe:.2f} → {best_sharpe:.2f} "
                f"({(best_sharpe/baseline_sharpe-1)*100:.1f}% improvement)"
            )
            full_params = baseline_params.copy()
            full_params.update(study.best_params)
            self._save_params(strategy_name, symbol, full_params)
            return full_params
        logger.info(
            f"{strategy_name} | {symbol}: no significant improvement (best={best_sharpe:.2f})"
        )
        return None

    def _save_params(self, strategy: str, symbol: str, params: dict) -> None:
        """Save optimized parameters to history file."""
        data = {}
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, "r") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        if strategy not in data:
            data[strategy] = {}
        
        data[strategy][symbol] = {
            "params":    params,
            "optimized_at": date.today().isoformat()
        }

        with open(HISTORY_FILE, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved optimized params to {HISTORY_FILE}")


def load_optimized_params(strategy: str, symbol: str) -> dict | None:
    """Helper to load overrides from the history file."""
    if not HISTORY_FILE.exists():
        return None
    try:
        with open(HISTORY_FILE, "r") as f:
            data = json.load(f)
        return data.get(strategy, {}).get(symbol, {}).get("params")
    except Exception:
        return None


if __name__ == "__main__":
    # Test script: optimize SBIN
    optimizer = ParamOptimizer()
    optimizer.optimize_ema_crossover("SBIN", n_trials=30)
