"""
Stock Scanner — scans NIFTY50 for active strategy signals.

The scanner runs all three strategies against recent data for every stock
and returns a list of stocks that currently have BUY/SELL signals.

Why scan all stocks?
  Instead of watching one stock at a time, the scanner acts like a
  filter — it surfaces only the stocks where your strategy says something
  interesting is happening RIGHT NOW. In live trading, this runs every
  few minutes during market hours.

In paper/backtest mode: uses end-of-day daily data from yfinance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from analysis.signal_scorer import score_signal, ScoreResult
from data.historical import fetch_ohlcv
from data.instruments import NIFTY50_INSTRUMENTS, KITE_TO_YF
from strategies.base_strategy import Action, Signal
from strategies.ema_crossover import EMACrossoverStrategy
from strategies.gap_and_go import GapAndGoStrategy
from strategies.opening_range_breakout import ORBStrategy
from strategies.rsi_macd_combo import RSIMACDStrategy


@dataclass
class ScanResult:
    """A stock that produced a non-HOLD signal."""
    symbol:            str
    strategy:          str
    action:            Action
    entry_price:       float
    stop_loss:         float
    target:            float
    rr_ratio:          float
    scanned_at:        datetime
    confidence_score:  int   = 0     # 0–5 — how many of the 5 quality checks passed
    confidence_checks: dict  = None  # {check_name: (passed, detail_text)}
    divergence:        str   = "—"   # "LAGGING ↓" | "IN_LINE" | "LEADING ↑" | "—"


_STRATEGIES = {
    "EMA Crossover":  EMACrossoverStrategy(),
    "RSI+MACD Combo": RSIMACDStrategy(),
    "ORB":            ORBStrategy(),
    "Gap & Go":       GapAndGoStrategy(),
}


def scan_nifty50(
    strategies: list[str] | None = None,
    max_symbols: int = 50,
) -> list[ScanResult]:
    """
    Scan NIFTY50 stocks for current signals.

    Args:
        strategies: Which strategies to run. None = all three.
        max_symbols: Limit how many symbols to check (useful for demos).

    Returns:
        List of ScanResult for any symbol/strategy that gave a signal.
    """
    active_strats = {
        k: v for k, v in _STRATEGIES.items()
        if strategies is None or k in strategies
    }

    symbols = [i.kite_symbol for i in NIFTY50_INSTRUMENTS[:max_symbols]]
    results: list[ScanResult] = []
    now = datetime.now()

    # Fetch NIFTY's intraday change once for the whole scan (cached 5 min)
    _nifty_chg = 0.0
    try:
        from analysis.nifty_correlation import get_nifty_change
        _nifty_chg = get_nifty_change()
    except Exception:
        pass

    for kite_sym in symbols:
        yf_sym = KITE_TO_YF.get(kite_sym, kite_sym + ".NS")
        try:
            df = fetch_ohlcv(yf_sym, period="6mo", interval="1d")
        except Exception:
            continue  # symbol delisted or unavailable — skip silently

        if df is None or len(df) < 60:
            continue

        for strat_name, strategy in active_strats.items():
            try:
                signal: Signal = strategy.generate_signal(kite_sym, df)
                if signal.action != Action.HOLD and signal.is_valid():
                    scored: ScoreResult = score_signal(signal, df)
                    # Compute divergence label for display
                    _div_label = "—"
                    try:
                        from analysis.nifty_correlation import get_divergence as _get_div
                        _div = _get_div(kite_sym, df, _nifty_chg)
                        _div_label = {"LAGGING": "LAGGING ↓", "LEADING": "LEADING ↑"}.get(
                            _div.label, "IN_LINE"
                        )
                    except Exception:
                        pass
                    results.append(ScanResult(
                        symbol=kite_sym,
                        strategy=strat_name,
                        action=signal.action,
                        entry_price=round(signal.entry_price, 2),
                        stop_loss=round(signal.stop_loss, 2),
                        target=round(signal.target, 2),
                        rr_ratio=round(signal.reward_risk_ratio, 2),
                        scanned_at=now,
                        confidence_score=scored.score,
                        confidence_checks=scored.checks,
                        divergence=_div_label,
                    ))
            except Exception:
                continue

    return results
