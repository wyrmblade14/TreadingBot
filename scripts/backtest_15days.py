# -*- coding: utf-8 -*-
"""
15-Day Multi-Symbol Backtest -- VWAP Bounce + RSI+MACD with VIX direction bias.

Tests the new system against the last 15 trading days across 12 NIFTY50 symbols.

Direction logic (3-signal consensus at 10:00 AM, no look-ahead):
  UP   : gap vs prev_close > +0.2% AND intraday > +0.1% AND NIFTY EMA9 > EMA21
  DOWN : gap vs prev_close < -0.2% AND intraday < -0.1% AND NIFTY EMA9 < EMA21
  NEUT : signals disagree -> sit out both sides (no trades that day)

Usage:
    python scripts/backtest_15days.py
    python scripts/backtest_15days.py --capital 200000
    python scripts/backtest_15days.py --symbols TCS,INFY,HDFCBANK
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import ta
from loguru import logger
logger.remove()

from data.historical import fetch_ohlcv
from data.instruments import KITE_TO_YF
from strategies.vwap_bounce import VWAPBounceStrategy
from strategies.rsi_macd_combo import RSIMACDStrategy
from strategies.ema_crossover import EMACrossoverStrategy
from strategies.base_strategy import Action

DEFAULT_SYMBOLS = [
    "TCS", "INFY", "HDFCBANK", "KOTAKBANK", "BAJFINANCE",
    "LT", "SBIN", "ICICIBANK", "AXISBANK", "WIPRO",
    "RELIANCE", "MARUTI",
]

CAPITAL  = 100_000
RISK_PCT = 0.01
MAX_POS  = 3


def nifty_direction_at_10am(nifty_5m, day):
    """
    3-signal consensus direction at 10:00 AM. No look-ahead.
    Returns (skip_sells, skip_buys, eod_chg_pct, bias_label).

    All 3 signals must agree for a directional call:
      1. Gap vs yesterday's close  (overnight institutional bias)
      2. Intraday momentum vs 9:15 open
      3. NIFTY 5m EMA9 vs EMA21 at 10 AM

    Disagreement -> NEUTRAL -> skip BOTH sides (sit out the day).
    This is deliberately conservative: only trade when direction is unambiguous.
    """
    day_df = nifty_5m[nifty_5m.index.date == day]
    if day_df is None or len(day_df) < 5:
        return False, False, 0.0, "NEUT"

    nifty_open  = float(day_df["open"].iloc[0])
    nifty_close = float(day_df["close"].iloc[-1])
    eod_chg     = (nifty_close - nifty_open) / nifty_open * 100

    # Yesterday's close (known at market open — no look-ahead)
    prev_days = nifty_5m[nifty_5m.index.date < day]
    if prev_days.empty:
        return False, False, eod_chg, "NEUT"
    prev_close = float(prev_days["close"].iloc[-1])

    # 10 AM candle
    at_10 = day_df[day_df.index.time >= dtime(10, 0)]
    if at_10.empty:
        return False, False, eod_chg, "NEUT"

    price_10am = float(at_10["close"].iloc[0])
    # Signal 2: 10 AM price vs 9:15 open (pure intraday — no multi-day EMA)
    intra_pct = (price_10am - nifty_open) / nifty_open

    # Signal 3: fraction of green 5m candles 9:15-10:00 (candle quality)
    morning    = day_df[day_df.index.time < dtime(10, 0)]
    green_frac = (morning["close"] > morning["open"]).mean() if len(morning) >= 3 else 0.5

    # Gap vs yesterday's close (known at market open — no look-ahead)
    gap_pct = (nifty_open - prev_close) / prev_close

    # All 3 must agree — strict thresholds prevent noise from triggering direction
    if gap_pct > 0.001 and intra_pct > 0.003 and green_frac >= 0.60:
        return True, False, eod_chg, "UP ^"     # block shorts

    if gap_pct < -0.001 and intra_pct < -0.003 and green_frac <= 0.40:
        return False, True, eod_chg, "DN v"     # block longs

    return False, False, eod_chg, "NEUT"        # sit out


def simulate_day(day, sym_data, nifty_5m, strategies, skip_sells, skip_buys):
    """Simulate one trading day. Returns list of trade dicts."""
    trades     = []
    open_count = 0

    for sym in sym_data:
        if open_count >= MAX_POS:
            break

        df     = sym_data[sym]
        day_df = df[df.index.date == day]
        if len(day_df) < 5:
            continue

        day_start = df.index.get_loc(day_df.index[0])
        fired     = False

        for i_off, candle_ts in enumerate(day_df.index):
            if fired:
                break
            t = candle_ts.time()
            if t < dtime(9, 45) or t > dtime(13, 30):
                continue

            abs_idx = day_start + i_off
            window  = df.iloc[max(0, abs_idx - 100): abs_idx + 1]
            if len(window) < 30:
                continue

            for strat in strategies:
                if fired:
                    break
                try:
                    sig = strat.generate_signal(sym, window)
                except Exception:
                    continue

                if sig.action == Action.HOLD:
                    continue
                if sig.action == Action.SELL and skip_sells:
                    continue
                if sig.action == Action.BUY and skip_buys:
                    continue

                entry = sig.entry_price
                sl    = sig.stop_loss
                tgt   = sig.target
                risk  = abs(entry - sl)
                if risk <= 0:
                    continue

                qty  = max(1, int(CAPITAL * RISK_PCT / risk))
                after = day_df[day_df.index > candle_ts]
                if after.empty:
                    continue

                eod = float(day_df["close"].iloc[-1])

                if sig.action == Action.BUY:
                    tgt_hit = float(after["high"].max()) >= tgt
                    sl_hit  = float(after["low"].min())  <= sl
                    if tgt_hit and not sl_hit:
                        net, outcome = (tgt - entry) * qty, "WIN"
                    elif sl_hit:
                        net, outcome = (sl  - entry) * qty, "LOSS"
                    else:
                        net, outcome = (eod - entry) * qty, "EOD"
                else:
                    tgt_hit = float(after["low"].min())  <= tgt
                    sl_hit  = float(after["high"].max()) >= sl
                    if tgt_hit and not sl_hit:
                        net, outcome = (entry - tgt) * qty, "WIN"
                    elif sl_hit:
                        net, outcome = (entry - sl ) * qty, "LOSS"
                    else:
                        net, outcome = (entry - eod) * qty, "EOD"

                trades.append({
                    "day": day, "sym": sym, "strategy": strat.name,
                    "action": sig.action.value,
                    "entry": round(entry, 2), "sl": round(sl, 2), "tgt": round(tgt, 2),
                    "qty": qty, "net": round(net, 2), "outcome": outcome,
                    "time": candle_ts.strftime("%H:%M"),
                })
                open_count += 1
                fired = True

    return trades


def main(capital: float, symbols: list[str]) -> None:
    global CAPITAL
    CAPITAL = capital

    def _fetch(kite_sym: str) -> object:
        """Fetch 22 days of 5m data. yfinance for historical backtesting."""
        yf_sym = KITE_TO_YF.get(kite_sym, kite_sym + ".NS")
        return fetch_ohlcv(yf_sym, period="22d", interval="5m")

    print("Fetching market data (yfinance)...")
    sym_data = {}
    for sym in symbols:
        df = _fetch(sym)
        if df is not None and len(df) > 50:
            sym_data[sym] = df
            print(f"  {sym}: {len(df)} candles")
        else:
            print(f"  {sym}: no data -- skipped")

    nifty_5m = fetch_ohlcv("^NSEI", period="22d", interval="5m")
    if nifty_5m is None:
        print("ERROR: could not fetch NIFTY50 data")
        sys.exit(1)

    trading_days = sorted(set(
        ts.date() for sym in sym_data for ts in sym_data[sym].index
    ))[-15:]

    print(f"\nTesting {len(trading_days)} days: {trading_days[0]} to {trading_days[-1]}")
    print(f"Symbols: {len(sym_data)}   Capital: Rs{capital:,.0f}   "
          f"Risk/trade: {RISK_PCT*100:.0f}%   Max positions/day: {MAX_POS}")
    print()

    strategies = [
        VWAPBounceStrategy(),
        RSIMACDStrategy(),
    ]

    all_trades    = []
    day_summaries = []

    hdr = (f"{'Date':<12} {'NIFTY':>8}  {'Bias':<7}  "
           f"{'Tr':>3}  {'W':>3}  {'L':>3}  {'EOD':>3}  "
           f"{'Day P&L':>10}  {'Cumul':>10}")
    print(hdr)
    print("-" * len(hdr))

    cumul = 0.0
    for day in trading_days:
        skip_sells, skip_buys, nifty_chg, bias = nifty_direction_at_10am(nifty_5m, day)
        # NEUTRAL = direction unclear → sit out entirely (preserve capital)
        if bias == "NEUT":
            skip_sells = True
            skip_buys  = True

        day_trades = simulate_day(day, sym_data, nifty_5m, strategies, skip_sells, skip_buys)
        all_trades.extend(day_trades)

        day_pnl = sum(t["net"] for t in day_trades)
        wins    = sum(1 for t in day_trades if t["outcome"] == "WIN")
        losses  = sum(1 for t in day_trades if t["outcome"] == "LOSS")
        eods    = sum(1 for t in day_trades if t["outcome"] == "EOD")
        cumul  += day_pnl

        day_summaries.append({
            "day": day, "pnl": day_pnl, "trades": len(day_trades),
            "wins": wins, "losses": losses, "bias": bias, "nifty_chg": nifty_chg,
        })

        marker = " << TODAY" if day == trading_days[-1] else ""
        print(
            f"{str(day):<12} {nifty_chg:>+7.2f}%  {bias:<7}  "
            f"{len(day_trades):>3}  {wins:>3}  {losses:>3}  {eods:>3}  "
            f"Rs{day_pnl:>+8,.0f}  Rs{cumul:>+8,.0f}{marker}"
        )

    # ── Summary ──────────────────────────────────────────────────────
    total_trades  = len(all_trades)
    total_wins    = sum(1 for t in all_trades if t["outcome"] == "WIN")
    total_losses  = sum(1 for t in all_trades if t["outcome"] == "LOSS")
    total_eod     = sum(1 for t in all_trades if t["outcome"] == "EOD")
    total_pnl     = sum(t["net"] for t in all_trades)
    win_rate      = total_wins / max(1, total_trades) * 100
    profit_days   = sum(1 for d in day_summaries if d["pnl"] > 0)
    loss_days     = sum(1 for d in day_summaries if d["pnl"] < 0)
    zero_days     = sum(1 for d in day_summaries if d["pnl"] == 0)
    avg_win       = (sum(t["net"] for t in all_trades if t["outcome"] == "WIN")
                     / max(1, total_wins))
    avg_loss      = (sum(t["net"] for t in all_trades if t["outcome"] == "LOSS")
                     / max(1, total_losses))
    gross_win     = sum(t["net"] for t in all_trades if t["net"] > 0)
    gross_loss    = abs(sum(t["net"] for t in all_trades if t["net"] < 0))
    profit_factor = gross_win / max(1, gross_loss)

    # NEUTRAL days (no trades)
    neutral_days = sum(1 for d in day_summaries if d["trades"] == 0)

    print()
    print("=" * 68)
    print("15-DAY SUMMARY")
    print("-" * 68)
    print(f"  Total P&L        : Rs{total_pnl:>+10,.0f}  ({total_pnl/capital*100:+.2f}% of capital)")
    print(f"  Profit days      : {profit_days}    Loss days: {loss_days}    "
          f"No-trade days: {neutral_days}")
    print(f"  Total trades     : {total_trades}   Wins: {total_wins}   "
          f"Losses: {total_losses}   EOD exits: {total_eod}")
    print(f"  Win rate         : {win_rate:.1f}%")
    print(f"  Avg win / loss   : Rs{avg_win:+,.0f} / Rs{avg_loss:+,.0f}")
    print(f"  Profit factor    : {profit_factor:.2f}x")
    print(f"  Avg P&L / day    : Rs{total_pnl/max(1,len(trading_days)):+,.0f}")
    print()

    strat_names = sorted({t["strategy"] for t in all_trades})
    if len(strat_names) > 1:
        print("  BY STRATEGY:")
        for sn in strat_names:
            st = [t for t in all_trades if t["strategy"] == sn]
            sw = sum(1 for t in st if t["outcome"] == "WIN")
            sp = sum(t["net"] for t in st)
            print(f"    {sn:<28}  trades={len(st):>3}  wins={sw:>3}  "
                  f"P&L=Rs{sp:>+8,.0f}")
        print()

    if day_summaries:
        best  = max(day_summaries, key=lambda d: d["pnl"])
        worst = min(day_summaries, key=lambda d: d["pnl"])
        print(f"  Best day   : {best['day']}  Rs{best['pnl']:+,.0f}  "
              f"(NIFTY {best['nifty_chg']:+.2f}%  {best['bias']})")
        print(f"  Worst day  : {worst['day']}  Rs{worst['pnl']:+,.0f}  "
              f"(NIFTY {worst['nifty_chg']:+.2f}%  {worst['bias']})")
    print("=" * 68)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="15-day VWAP Bounce + RSI+MACD backtest with direction bias"
    )
    parser.add_argument("--capital", type=float, default=100_000,
                        help="Starting capital in Rs (default 100000)")
    parser.add_argument("--symbols", type=str,
                        default=",".join(DEFAULT_SYMBOLS),
                        help="Comma-separated symbols")
    args = parser.parse_args()
    main(
        capital=args.capital,
        symbols=[s.strip().upper() for s in args.symbols.split(",")],
    )
