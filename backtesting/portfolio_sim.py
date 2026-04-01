"""
Portfolio Simulation — runs the full bot across all strategies and symbols
for the last N trading days, using real historical data.

What is this?
  Instead of waiting 30 days to see if the bot works, this simulation
  replays the last 30 trading days through the EXACT same pipeline:
    - All 3 strategies (EMA, RSI+MACD, ORB) running simultaneously
    - All 10 risk rules enforced (1% risk, daily loss halt, etc.)
    - Shared capital pool (max 3 open positions at once)
    - End-of-day square-off at 3:15 PM every day
    - Capital from yesterday carries into today

  After the simulation you can answer:
    "Would my bot have made money over the last 30 days?"
    "Which strategy contributed the most trades/profit?"
    "How often did the daily loss halt fire?"

How it differs from the existing BacktestEngine:
  BacktestEngine    → 1 strategy × 1 symbol × any date range
  WalkForwardEngine → 1 strategy × 1 symbol × rolling windows
  PortfolioSimulator→ ALL strategies × ALL selected symbols × last N days
                      with shared capital and position limits

No database writes:
  Results are returned in memory only. The live trades.db is not touched.
  This keeps the Home page's paper-trading stats clean.

Data limit:
  yfinance provides 5-minute data for ~60 calendar days.
  Default of 30 trading days = ~44 calendar days → fits comfortably.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import pandas as pd
from loguru import logger

from backtesting.day_replay import _build_strategies, NIFTY50_SYMBOLS
from config.settings import (
    BROKERAGE_PER_ORDER,
    EXCHANGE_TRANSACTION_CHARGE,
    FIRST_CANDLE_BLACKOUT,
    GST_RATE,
    NO_NEW_ENTRIES_TIME,
    SHORT_SELLING_ENABLED,
    SQUAREOFF_TIME,
    STT_INTRADAY_SELL,
    VIRTUAL_CAPITAL,
)
from data.historical import fetch_ohlcv
from data.instruments import KITE_TO_YF
from risk.position_sizer import calculate_quantity
from risk.risk_manager import RiskManager
from strategies.base_strategy import Action, BaseStrategy


# ── Internal trade tracker (no DB) ───────────────────────────────────

@dataclass
class _OpenPos:
    """Tracks a live position during simulation."""
    symbol:      str
    strategy:    str
    action:      Action
    quantity:    int
    entry_price: float
    stop_loss:   float
    target:      float
    entry_time:  datetime


@dataclass
class SimTrade:
    """A completed trade from the portfolio simulation."""
    symbol:      str
    strategy:    str
    action:      Action
    quantity:    int
    entry_price: float
    exit_price:  float
    stop_loss:   float
    target:      float
    entry_time:  datetime
    exit_time:   datetime
    exit_reason: str        # "target" | "stop_loss" | "eod_squareoff"
    brokerage:   float

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


# ── Per-day and aggregate results ─────────────────────────────────────

@dataclass
class SimDay:
    """Results for a single trading day in the simulation."""
    date:           date
    capital_start:  float
    capital_end:    float
    trades:         list[SimTrade] = field(default_factory=list)
    halted:         bool           = False   # True if daily loss halt fired

    @property
    def net_pnl(self) -> float:
        return round(self.capital_end - self.capital_start, 2)

    @property
    def num_trades(self) -> int:
        return len(self.trades)

    @property
    def num_winners(self) -> int:
        return sum(1 for t in self.trades if t.is_winner)

    @property
    def win_rate_pct(self) -> float:
        return round(100.0 * self.num_winners / self.num_trades, 1) if self.trades else 0.0


@dataclass
class PortfolioSimResult:
    """Aggregated results from the full N-day portfolio simulation."""
    symbols:         list[str]
    initial_capital: float
    days:            list[SimDay] = field(default_factory=list)

    @property
    def all_trades(self) -> list[SimTrade]:
        return [t for day in self.days for t in day.trades]

    @property
    def total_net_pnl(self) -> float:
        return round(sum(day.net_pnl for day in self.days), 2)

    @property
    def final_capital(self) -> float:
        return round(self.initial_capital + self.total_net_pnl, 2)

    @property
    def total_return_pct(self) -> float:
        return round(self.total_net_pnl / self.initial_capital * 100, 2)

    @property
    def total_trades(self) -> int:
        return sum(day.num_trades for day in self.days)

    @property
    def num_winners(self) -> int:
        return sum(day.num_winners for day in self.days)

    @property
    def win_rate_pct(self) -> float:
        return round(100.0 * self.num_winners / self.total_trades, 1) if self.total_trades else 0.0

    @property
    def equity_curve(self) -> list[float]:
        """Capital at end of each simulated day (starting point first)."""
        curve = [self.initial_capital]
        for day in self.days:
            curve.append(day.capital_end)
        return curve

    @property
    def profitable_days(self) -> int:
        return sum(1 for d in self.days if d.net_pnl > 0)

    @property
    def halted_days(self) -> int:
        """Days where the daily loss halt (Rule 4) fired."""
        return sum(1 for d in self.days if d.halted)

    def strategy_breakdown(self) -> dict[str, dict]:
        """Per-strategy: trades, wins, total P&L."""
        breakdown: dict[str, dict] = {}
        for t in self.all_trades:
            if t.strategy not in breakdown:
                breakdown[t.strategy] = {"trades": 0, "wins": 0, "net_pnl": 0.0}
            breakdown[t.strategy]["trades"] += 1
            if t.is_winner:
                breakdown[t.strategy]["wins"] += 1
            breakdown[t.strategy]["net_pnl"] += t.net_pnl
        return breakdown


# ── Main engine ───────────────────────────────────────────────────────

class PortfolioSimulator:
    """
    Simulates the full TreadingBot portfolio across the last N trading days.

    Args:
        capital:       Starting virtual capital (default ₹1,00,000)
        trading_days:  Number of recent trading days to simulate (default 30)
        strategies:    Strategy filter ("ema"/"rsi"/"orb") or None for all three
    """

    def __init__(
        self,
        capital:      float = VIRTUAL_CAPITAL,
        trading_days: int   = 30,
        strategies:   str | None = None,
    ) -> None:
        self._initial_capital = capital
        self._trading_days    = trading_days
        self._strats: list[BaseStrategy] = _build_strategies(strategies)

    def run(self, symbols: list[str]) -> PortfolioSimResult:
        """
        Run the simulation for all symbols.

        Args:
            symbols: List of Kite symbols e.g. ["RELIANCE", "TCS", "INFY"]

        Returns:
            PortfolioSimResult with per-day and aggregate stats.
        """
        logger.info(
            f"PortfolioSim | {len(symbols)} symbols | "
            f"{self._trading_days} trading days | capital=₹{self._initial_capital:,.0f} | "
            f"strategies={[s.name for s in self._strats]}"
        )

        result = PortfolioSimResult(
            symbols=symbols,
            initial_capital=self._initial_capital,
        )

        # ── Fetch data for all symbols (once, upfront) ────────────────
        # period="60d" gives ~60 calendar days / ~42 trading days of 5m data.
        # This covers our default 30-day simulation with warmup to spare.
        symbol_data: dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            yf_sym = KITE_TO_YF.get(symbol, symbol + ".NS")
            try:
                df = fetch_ohlcv(yf_sym, period="60d", interval="5m")
                symbol_data[symbol] = df
            except ValueError as exc:
                logger.warning(f"PortfolioSim: skipping {symbol} — {exc}")

        if not symbol_data:
            logger.error("PortfolioSim: no data fetched for any symbol.")
            return result

        # ── Determine the trading days to simulate ────────────────────
        # Use the first available symbol's date index as the trading calendar.
        ref_df     = next(iter(symbol_data.values()))
        all_days   = sorted({d.date() for d in ref_df.index})
        sim_days   = all_days[-self._trading_days:]  # last N trading days

        logger.info(
            f"PortfolioSim | simulating {len(sim_days)} days: "
            f"{sim_days[0]} -> {sim_days[-1]}"
        )

        # ── Day-by-day simulation loop ────────────────────────────────
        capital = self._initial_capital
        risk_mgr = RiskManager(capital=capital)

        for day_date in sim_days:
            sim_day = self._run_day(
                day_date=day_date,
                symbol_data=symbol_data,
                capital=capital,
                risk_mgr=risk_mgr,
            )
            result.days.append(sim_day)
            capital = sim_day.capital_end

            logger.info(
                f"  [{day_date}] trades={sim_day.num_trades} "
                f"win_rate={sim_day.win_rate_pct:.0f}% "
                f"pnl=₹{sim_day.net_pnl:+,.0f} "
                f"capital=₹{capital:,.0f}"
                + (" HALTED" if sim_day.halted else "")
            )

        logger.info(
            f"PortfolioSim complete | "
            f"total_trades={result.total_trades} "
            f"win_rate={result.win_rate_pct:.1f}% "
            f"net_pnl=₹{result.total_net_pnl:+,.0f} "
            f"return={result.total_return_pct:+.2f}%"
        )
        return result

    # ── Private helpers ───────────────────────────────────────────────

    def _run_day(
        self,
        day_date: date,
        symbol_data: dict[str, pd.DataFrame],
        capital: float,
        risk_mgr: RiskManager,
    ) -> SimDay:
        """Simulate a single trading day across all symbols."""
        risk_mgr.new_day(capital)
        sim_day = SimDay(date=day_date, capital_start=capital, capital_end=capital)

        # Open positions: symbol → _OpenPos (one per symbol at most)
        open_positions: dict[str, _OpenPos] = {}

        for symbol, df_all in symbol_data.items():
            df_today = df_all[df_all.index.date == day_date]
            if df_today.empty:
                continue

            # All candles BEFORE today = warmup for indicator initialisation
            df_warmup = df_all[df_all.index.date < day_date]

            self._replay_symbol_in_day(
                symbol=symbol,
                df_warmup=df_warmup,
                df_today=df_today,
                open_positions=open_positions,
                sim_day=sim_day,
                risk_mgr=risk_mgr,
            )

        sim_day.capital_end = round(capital + sum(t.net_pnl for t in sim_day.trades), 2)
        sim_day.halted = risk_mgr.state.trading_halted
        return sim_day

    def _replay_symbol_in_day(
        self,
        symbol: str,
        df_warmup: pd.DataFrame,
        df_today: pd.DataFrame,
        open_positions: dict[str, _OpenPos],
        sim_day: SimDay,
        risk_mgr: RiskManager,
    ) -> None:
        """Replay all candles of df_today for one symbol."""

        for i in range(len(df_today)):
            candle        = df_today.iloc[i]
            current_price = float(candle["close"])
            current_time  = df_today.index[i].time()
            candle_dt     = df_today.index[i].to_pydatetime()

            # Full visible history: all warmup + today up to and including this candle
            visible = pd.concat([df_warmup, df_today.iloc[: i + 1]])

            # ── EOD square-off ────────────────────────────────────────
            if current_time >= SQUAREOFF_TIME:
                if symbol in open_positions:
                    pos = open_positions.pop(symbol)
                    trade = self._close_trade(pos, current_price, candle_dt, "eod_squareoff")
                    sim_day.trades.append(trade)
                    risk_mgr.on_position_closed(symbol, trade.net_pnl)
                break

            # ── Check exit for open position ──────────────────────────
            if symbol in open_positions:
                pos = open_positions[symbol]
                reason = _check_exit_signal(pos, current_price, current_time)
                if reason:
                    trade = self._close_trade(pos, current_price, candle_dt, reason)
                    sim_day.trades.append(trade)
                    risk_mgr.on_position_closed(symbol, trade.net_pnl)
                    del open_positions[symbol]
                continue

            # ── First-candle blackout ─────────────────────────────────
            if current_time < FIRST_CANDLE_BLACKOUT:
                continue

            # ── No new entries after 14:30 ────────────────────────────
            if current_time >= NO_NEW_ENTRIES_TIME:
                continue

            # ── Halt check ────────────────────────────────────────────
            if risk_mgr.state.trading_halted:
                continue

            # ── Evaluate all strategies ───────────────────────────────
            for strategy in self._strats:
                signal = strategy.generate_signal(symbol, visible)

                if signal.action == Action.HOLD:
                    continue
                if signal.action == Action.SELL and not SHORT_SELLING_ENABLED:
                    continue

                decision = risk_mgr.evaluate(signal, now=candle_dt)
                if not decision.approved:
                    continue

                sig = decision.signal
                open_positions[symbol] = _OpenPos(
                    symbol=symbol,
                    strategy=strategy.name,
                    action=sig.action,
                    quantity=sig.quantity,
                    entry_price=current_price,
                    stop_loss=sig.stop_loss,
                    target=sig.target,
                    entry_time=candle_dt,
                )
                risk_mgr.on_position_opened(symbol)
                break   # one trade per candle per symbol

    @staticmethod
    def _close_trade(
        pos: _OpenPos,
        exit_price: float,
        exit_time: datetime,
        reason: str,
    ) -> SimTrade:
        brokerage = _estimate_brokerage(pos.quantity, pos.entry_price, exit_price)
        return SimTrade(
            symbol=pos.symbol,
            strategy=pos.strategy,
            action=pos.action,
            quantity=pos.quantity,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            stop_loss=pos.stop_loss,
            target=pos.target,
            entry_time=pos.entry_time,
            exit_time=exit_time,
            exit_reason=reason,
            brokerage=brokerage,
        )


# ── Internal helpers ──────────────────────────────────────────────────

def _check_exit_signal(pos: _OpenPos, price: float, t) -> str | None:
    """Return exit reason if the trade should close, else None."""
    if pos.action == Action.BUY:
        if price <= pos.stop_loss: return "stop_loss"
        if price >= pos.target:    return "target"
    else:
        if price >= pos.stop_loss: return "stop_loss"
        if price <= pos.target:    return "target"
    return None


def _estimate_brokerage(qty: int, entry: float, exit_: float) -> float:
    """Approximate round-trip Zerodha cost for one intraday trade."""
    buy_turn  = qty * entry
    sell_turn = qty * exit_
    broker    = BROKERAGE_PER_ORDER * 2
    stt       = sell_turn * STT_INTRADAY_SELL
    exc       = (buy_turn + sell_turn) * EXCHANGE_TRANSACTION_CHARGE
    gst       = (broker + exc) * GST_RATE
    return round(broker + stt + exc + gst, 2)
