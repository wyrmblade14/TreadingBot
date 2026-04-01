"""
Backtesting Engine — replay historical data through strategies.

What is backtesting?
  Backtesting means running your strategy on past price data to see how
  it would have performed. Before risking real money (or even paper trading),
  backtesting answers: "Has this strategy ever worked historically?"

The most important rule: NO LOOKAHEAD BIAS.
  When processing candle #50, the strategy must only see candles 1–50.
  It must never "see" candle #51's data. In real trading, the future doesn't
  exist yet. If the backtest accidentally uses future data, the results will
  look fantastic but will fail completely in live trading.

  We enforce this by slicing: `df.iloc[:i+1]` on every iteration.

How a backtest run works:
  1. Download historical OHLCV data (daily or intraday candles)
  2. Group candles by trading day
  3. For each day, replay candles in order:
       a. Feed candles seen so far into indicator → strategy → risk manager
       b. If signal is BUY/SELL and approved: record a paper trade
       c. On each subsequent candle: check if stop-loss or target was hit
       d. At end of day (15:15 IST): square off any remaining positions
  4. Collect all trades → calculate performance metrics → generate report
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import pandas as pd
from loguru import logger

from config.settings import IST, SQUAREOFF_TIME
from data.historical import fetch_ohlcv
from data.instruments import KITE_TO_YF
from risk.position_sizer import calculate_quantity
from risk.risk_manager import RiskManager
from strategies.base_strategy import Action, BaseStrategy, Signal


@dataclass
class BacktestTrade:
    """A single completed trade recorded during a backtest."""
    symbol:       str
    strategy:     str
    action:       Action
    quantity:     int
    entry_price:  float
    exit_price:   float
    stop_loss:    float
    target:       float
    entry_time:   datetime
    exit_time:    datetime
    exit_reason:  str       # "target", "stop_loss", "eod_squareoff"
    brokerage:    float     = 40.0   # ₹20 entry + ₹20 exit (approx)

    @property
    def gross_pnl(self) -> float:
        if self.action == Action.BUY:
            return (self.exit_price - self.entry_price) * self.quantity
        return (self.entry_price - self.exit_price) * self.quantity

    @property
    def net_pnl(self) -> float:
        return round(self.gross_pnl - self.brokerage, 2)

    @property
    def is_winner(self) -> bool:
        return self.net_pnl > 0


@dataclass
class BacktestResult:
    """All trades and summary data from a completed backtest run."""
    symbol:        str
    strategy_name: str
    start_date:    date
    end_date:      date
    initial_capital: float
    trades:        list[BacktestTrade] = field(default_factory=list)

    @property
    def num_trades(self) -> int:
        return len(self.trades)

    @property
    def total_net_pnl(self) -> float:
        return round(sum(t.net_pnl for t in self.trades), 2)

    @property
    def final_capital(self) -> float:
        return round(self.initial_capital + self.total_net_pnl, 2)

    @property
    def total_return_pct(self) -> float:
        return round(self.total_net_pnl / self.initial_capital * 100, 2)


class BacktestEngine:
    """
    Runs a strategy on historical OHLCV data and records all trades.

    Args:
        strategy:        A strategy instance (EMACrossoverStrategy etc.)
        initial_capital: Starting capital for position sizing (default ₹1,00,000)
    """

    def __init__(self, strategy: BaseStrategy, initial_capital: float = 1_00_000.0) -> None:
        self._strategy       = strategy
        self._initial_capital = initial_capital

    def run(
        self,
        symbol: str,
        start: str = "2023-01-01",
        end:   str = "2024-12-31",
    ) -> BacktestResult:
        """
        Run the backtest for one symbol over a date range.

        Args:
            symbol: Kite symbol e.g. "RELIANCE". Converted to yfinance format internally.
            start:  Start date "YYYY-MM-DD"
            end:    End date "YYYY-MM-DD"

        Returns:
            BacktestResult with all trades and summary stats.
        """
        yf_symbol = KITE_TO_YF.get(symbol, symbol + ".NS")
        logger.info(
            f"Backtest | {symbol} | strategy={self._strategy.name} "
            f"| {start} → {end}"
        )

        # yfinance intraday limits:
        #   5m  → last 60 days only
        #   1h  → last 730 days (2 years)
        #   1d  → unlimited
        # We always prefer intraday candles so strategies run as designed.
        days = (pd.Timestamp(end) - pd.Timestamp(start)).days
        if days <= 55:
            interval = "5m"
        elif days <= 700:
            interval = "1h"
        else:
            interval = "1d"

        use_daily = (interval == "1d")

        logger.info(f"Using {interval} candles for {days}-day range")
        df_all = fetch_ohlcv(yf_symbol, interval=interval, start=start, end=end)

        if df_all.empty:
            logger.warning(f"No data for {yf_symbol}. Returning empty result.")
            return BacktestResult(
                symbol=symbol,
                strategy_name=self._strategy.name,
                start_date=pd.Timestamp(start).date(),
                end_date=pd.Timestamp(end).date(),
                initial_capital=self._initial_capital,
            )

        result = BacktestResult(
            symbol=symbol,
            strategy_name=self._strategy.name,
            start_date=df_all.index[0].date(),
            end_date=df_all.index[-1].date(),
            initial_capital=self._initial_capital,
        )

        capital = self._initial_capital
        open_trade: Optional[_OpenTrade] = None

        if use_daily:
            # ── Daily mode: one candle per bar, iterate the full series ───
            # Entry signal fires on candle i; exit checked on candle i+1 onwards.
            # No intraday time gates; no EOD squareoff (hold until SL/target).
            df_daily = df_all.sort_index()
            for i in range(1, len(df_daily)):
                visible = df_daily.iloc[: i + 1]
                current = df_daily.iloc[i]
                current_price = float(current["close"])
                current_time  = visible.index[-1]

                # Check exits first
                if open_trade is not None:
                    exit_reason = _check_exit_daily(open_trade, current)
                    if exit_reason:
                        brokerage = _estimate_brokerage(open_trade.quantity, open_trade.entry_price, current_price)
                        trade = BacktestTrade(
                            symbol=symbol,
                            strategy=self._strategy.name,
                            action=open_trade.action,
                            quantity=open_trade.quantity,
                            entry_price=open_trade.entry_price,
                            exit_price=current_price,
                            stop_loss=open_trade.stop_loss,
                            target=open_trade.target,
                            entry_time=open_trade.entry_time,
                            exit_time=current_time,
                            exit_reason=exit_reason,
                            brokerage=brokerage,
                        )
                        result.trades.append(trade)
                        capital += trade.net_pnl
                        open_trade = None
                        logger.debug(
                            f"{exit_reason.upper()} {symbol} "
                            f"exit={current_price:.2f} pnl={trade.net_pnl:.0f}"
                        )
                    continue  # one action per candle in daily mode

                # Generate signal on current candle's close
                signal: Signal = self._strategy.generate_signal(symbol, visible)
                if signal.action == Action.HOLD:
                    continue

                qty = calculate_quantity(capital, signal.entry_price, signal.stop_loss)
                if qty <= 0:
                    continue

                signal.quantity = qty
                if signal.reward_risk_ratio < 2.0:
                    continue

                open_trade = _OpenTrade(
                    action=signal.action,
                    quantity=qty,
                    entry_price=current_price,
                    stop_loss=signal.stop_loss,
                    target=signal.target,
                    entry_time=current_time,
                )
                logger.debug(
                    f"ENTRY {signal.action.value} {symbol} "
                    f"@ {current_price:.2f} sl={signal.stop_loss:.2f} "
                    f"target={signal.target:.2f} qty={qty}"
                )

            # Close any position still open at end of data
            if open_trade is not None:
                last_price = float(df_daily.iloc[-1]["close"])
                brokerage  = _estimate_brokerage(open_trade.quantity, open_trade.entry_price, last_price)
                trade = BacktestTrade(
                    symbol=symbol,
                    strategy=self._strategy.name,
                    action=open_trade.action,
                    quantity=open_trade.quantity,
                    entry_price=open_trade.entry_price,
                    exit_price=last_price,
                    stop_loss=open_trade.stop_loss,
                    target=open_trade.target,
                    entry_time=open_trade.entry_time,
                    exit_time=df_daily.index[-1],
                    exit_reason="end_of_data",
                    brokerage=brokerage,
                )
                result.trades.append(trade)
                capital += trade.net_pnl
                open_trade = None

        else:
            # ── Intraday mode: many candles per day, grouped by date ──────
            # IMPORTANT: strategies need full history (RSI/MACD need 26+ candles).
            # We pass df_all.iloc[:global_idx+1] so the strategy always sees all
            # candles up to now — not just today's. The day grouping is only used
            # for EOD square-off logic.
            from config.settings import FIRST_CANDLE_BLACKOUT, NO_NEW_ENTRIES_TIME
            days = df_all.groupby(df_all.index.date)
            global_idx = 0   # tracks position in df_all across all days

            for day, day_df in days:
                day_df = day_df.sort_index()
                day_len = len(day_df)

                for i in range(day_len):
                    abs_idx = global_idx + i
                    if abs_idx == 0:
                        continue  # need at least one prior candle

                    current       = day_df.iloc[i]
                    current_price = float(current["close"])
                    current_time  = day_df.index[i]

                    # Full history up to and including this candle — no lookahead
                    visible = df_all.iloc[: abs_idx + 1]

                    # Check exits for open trade
                    if open_trade is not None:
                        exit_reason = _check_exit(open_trade, current_price, current_time)
                        if exit_reason:
                            brokerage = _estimate_brokerage(open_trade.quantity, open_trade.entry_price, current_price)
                            trade = BacktestTrade(
                                symbol=symbol,
                                strategy=self._strategy.name,
                                action=open_trade.action,
                                quantity=open_trade.quantity,
                                entry_price=open_trade.entry_price,
                                exit_price=current_price,
                                stop_loss=open_trade.stop_loss,
                                target=open_trade.target,
                                entry_time=open_trade.entry_time,
                                exit_time=current_time,
                                exit_reason=exit_reason,
                                brokerage=brokerage,
                            )
                            result.trades.append(trade)
                            capital += trade.net_pnl
                            open_trade = None
                            logger.debug(
                                f"[{day}] {exit_reason.upper()} {symbol} "
                                f"exit={current_price:.2f} pnl={trade.net_pnl:.0f}"
                            )
                            continue

                    if open_trade is not None:
                        continue

                    # Time gates
                    t = current_time.time()
                    if not (FIRST_CANDLE_BLACKOUT <= t < NO_NEW_ENTRIES_TIME):
                        continue

                    signal: Signal = self._strategy.generate_signal(symbol, visible)
                    if signal.action == Action.HOLD:
                        continue

                    qty = calculate_quantity(capital, signal.entry_price, signal.stop_loss)
                    if qty <= 0:
                        continue

                    signal.quantity = qty
                    if signal.reward_risk_ratio < 2.0:
                        continue

                    open_trade = _OpenTrade(
                        action=signal.action,
                        quantity=qty,
                        entry_price=current_price,
                        stop_loss=signal.stop_loss,
                        target=signal.target,
                        entry_time=current_time,
                    )
                    logger.debug(
                        f"[{day}] ENTRY {signal.action.value} {symbol} "
                        f"@ {current_price:.2f} sl={signal.stop_loss:.2f} "
                        f"target={signal.target:.2f} qty={qty}"
                    )

                global_idx += day_len

                # End-of-day: square off any open position
                if open_trade is not None:
                    eod_price = float(day_df.iloc[-1]["close"])
                    brokerage  = _estimate_brokerage(open_trade.quantity, open_trade.entry_price, eod_price)
                    trade = BacktestTrade(
                        symbol=symbol,
                        strategy=self._strategy.name,
                        action=open_trade.action,
                        quantity=open_trade.quantity,
                        entry_price=open_trade.entry_price,
                        exit_price=eod_price,
                        stop_loss=open_trade.stop_loss,
                        target=open_trade.target,
                        entry_time=open_trade.entry_time,
                        exit_time=day_df.index[-1],
                        exit_reason="eod_squareoff",
                        brokerage=brokerage,
                    )
                    result.trades.append(trade)
                    capital += trade.net_pnl
                    open_trade = None

        logger.info(
            f"Backtest complete | {symbol} {self._strategy.name} "
            f"| trades={result.num_trades} "
            f"| net_pnl=₹{result.total_net_pnl:,.0f} "
            f"| return={result.total_return_pct:.1f}%"
        )
        return result


# ── Internal helpers ──────────────────────────────────────────────────

@dataclass
class _OpenTrade:
    action:      Action
    quantity:    int
    entry_price: float
    stop_loss:   float
    target:      float
    entry_time:  datetime


def _check_exit_daily(trade: _OpenTrade, candle: pd.Series) -> str | None:
    """
    For daily candles: check if the candle's high/low touched SL or target.

    A daily candle's high and low tell us the full price range for that day.
    If the low dipped below stop-loss, the stop was hit.
    If the high touched the target, the target was hit.
    We conservatively assume stop-loss fires first on unfavourable candles.
    """
    high  = float(candle["high"])
    low   = float(candle["low"])
    close = float(candle["close"])

    if trade.action == Action.BUY:
        if low <= trade.stop_loss:   return "stop_loss"
        if high >= trade.target:     return "target"
    else:  # SELL
        if high >= trade.stop_loss:  return "stop_loss"
        if low <= trade.target:      return "target"
    return None


def _check_exit(trade: _OpenTrade, price: float, time: datetime) -> str | None:
    """Return exit reason string if the trade should close, else None."""
    eod = time.time() >= SQUAREOFF_TIME

    if trade.action == Action.BUY:
        if price <= trade.stop_loss: return "stop_loss"
        if price >= trade.target:    return "target"
    else:
        if price >= trade.stop_loss: return "stop_loss"
        if price <= trade.target:    return "target"

    if eod:
        return "eod_squareoff"
    return None


def _estimate_brokerage(qty: int, entry: float, exit_: float) -> float:
    """Approximate round-trip Zerodha cost for one trade."""
    from config.settings import (
        BROKERAGE_PER_ORDER, STT_INTRADAY_SELL,
        EXCHANGE_TRANSACTION_CHARGE, GST_RATE,
    )
    buy_turn  = qty * entry
    sell_turn = qty * exit_
    broker    = BROKERAGE_PER_ORDER * 2
    stt       = sell_turn * STT_INTRADAY_SELL
    exc       = (buy_turn + sell_turn) * EXCHANGE_TRANSACTION_CHARGE
    gst       = (broker + exc) * GST_RATE
    return round(broker + stt + exc + gst, 2)
