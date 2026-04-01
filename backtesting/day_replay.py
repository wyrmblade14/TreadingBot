"""
Day Replay Engine — replay any past trading day candle-by-candle.

What is day replay?
  Unlike backtesting (which silently processes months of data), day replay
  runs a SINGLE day through the SAME live-bot components — PaperBroker,
  RiskManager, OrderManager — candle by candle.

  This lets you:
    - Debug why the bot did or didn't trade on a specific day
    - Validate strategy tweaks before the next live session
    - Watch signals fire in "slow motion" on a past market day

How it differs from backtesting:
  - Uses real PaperBroker (with slippage, brokerage simulation)
  - Uses real RiskManager (all 10 rules enforced — except time gates
    which use candle time, not wall-clock time)
  - Logs trades to the database with trading_mode="replay"
    so they don't pollute the Home page's live paper stats
  - Returns a detailed candle_log showing every event (HOLD, REJECT, BUY, EXIT)

Warmup:
  MACD(26,9) needs 35+ candles. We fetch 5 days of 5-minute data and use
  all candles BEFORE the replay date as indicator warmup, then replay only
  the target date's candles. This mirrors the live bot's behaviour exactly.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, time

import pandas as pd
from loguru import logger

from broker.paper_broker import PaperBroker
from config.settings import (
    FIRST_CANDLE_BLACKOUT,
    IST,
    NO_NEW_ENTRIES_TIME,
    SHORT_SELLING_ENABLED,
    SQUAREOFF_TIME,
    VIRTUAL_CAPITAL,
)
from data.historical import fetch_ohlcv
from data.instruments import KITE_TO_YF, NIFTY50_INSTRUMENTS
from execution.order_manager import OrderManager
from execution.trade_log import TradeLogger
from risk.risk_manager import RiskManager
from strategies.base_strategy import Action, BaseStrategy
from strategies.ema_crossover import EMACrossoverStrategy
from strategies.opening_range_breakout import ORBStrategy
from strategies.rsi_macd_combo import RSIMACDStrategy

NIFTY50_SYMBOLS = [i.kite_symbol for i in NIFTY50_INSTRUMENTS]


def _build_strategies(strategy_name: str | None) -> list[BaseStrategy]:
    """Return the list of strategy instances to run."""
    all_strats = [EMACrossoverStrategy(), RSIMACDStrategy(), ORBStrategy()]
    if strategy_name is None:
        return all_strats
    mapping = {
        "ema":  EMACrossoverStrategy,
        "rsi":  RSIMACDStrategy,
        "orb":  ORBStrategy,
    }
    cls = mapping.get(strategy_name.lower())
    if cls is None:
        raise ValueError(
            f"Unknown strategy {strategy_name!r}. Choose from: ema, rsi, orb."
        )
    return [cls()]


@dataclass
class ReplayResult:
    """All output from a completed day replay."""
    date:              str
    symbols:           list[str]
    trades:            list[dict]          = field(default_factory=list)
    final_cash:        float               = 0.0
    starting_capital:  float               = VIRTUAL_CAPITAL
    brokerage_total:   float               = 0.0
    candle_log:        list[dict]          = field(default_factory=list)

    @property
    def net_pnl(self) -> float:
        return round(self.final_cash - self.starting_capital, 2)

    @property
    def num_trades(self) -> int:
        return len([t for t in self.trades if t.get("exit_price")])

    @property
    def num_winners(self) -> int:
        return len([t for t in self.trades if (t.get("net_pnl") or 0) > 0])

    @property
    def win_rate_pct(self) -> float:
        n = self.num_trades
        return round(100.0 * self.num_winners / n, 1) if n > 0 else 0.0


class DayReplayEngine:
    """
    Replays a single trading day candle-by-candle through all bot components.

    Args:
        capital:    Starting virtual capital (default VIRTUAL_CAPITAL)
        strategies: Strategy name string ("ema"/"rsi"/"orb") or None for all
        live_delay: Seconds to pause between candles (0 = instant)
    """

    def __init__(
        self,
        capital: float = VIRTUAL_CAPITAL,
        strategies: str | None = None,
        live_delay: float = 0.0,
    ) -> None:
        self._capital    = capital
        self._strats     = _build_strategies(strategies)
        self._live_delay = live_delay

    def run(self, symbols: list[str], replay_date: str) -> ReplayResult:
        """
        Run the replay for the given symbols on replay_date.

        Args:
            symbols:      List of Kite symbols e.g. ["RELIANCE", "TCS"]
            replay_date:  "YYYY-MM-DD" string

        Returns:
            ReplayResult with trades, final cash, and candle-level log.

        Raises:
            ValueError: if replay_date is a weekend/holiday with no candles.
        """
        target_date = pd.Timestamp(replay_date).date()

        # Fresh singletons — completely isolated from the live bot
        # replay_mode=True skips PaperBroker's wall-clock market-hours check
        broker    = PaperBroker(initial_capital=self._capital, replay_mode=True)
        risk_mgr  = RiskManager(capital=self._capital)
        trade_log = TradeLogger()
        order_mgr = OrderManager(broker, trade_log, trading_mode="replay")

        result = ReplayResult(
            date=replay_date,
            symbols=symbols,
            starting_capital=self._capital,
        )

        for symbol in symbols:
            yf_sym = KITE_TO_YF.get(symbol, symbol + ".NS")

            try:
                df_all = fetch_ohlcv(yf_sym, period="5d", interval="5m")
            except ValueError as exc:
                logger.warning(f"Replay: skipping {symbol} — {exc}")
                result.candle_log.append({
                    "time":   replay_date,
                    "symbol": symbol,
                    "event":  "ERROR",
                    "detail": str(exc),
                })
                continue

            df_warmup = df_all[df_all.index.date < target_date]
            df_today  = df_all[df_all.index.date == target_date]

            if df_today.empty:
                msg = f"No candles for {symbol} on {replay_date} (market holiday / weekend?)"
                logger.warning(f"Replay: {msg}")
                result.candle_log.append({
                    "time":   replay_date,
                    "symbol": symbol,
                    "event":  "NO DATA",
                    "detail": msg,
                })
                continue

            logger.info(
                f"Replay {replay_date} | {symbol} | "
                f"{len(df_warmup)} warmup candles + {len(df_today)} replay candles"
            )

            # ── Sync capital before processing this symbol ────────────────
            summary = broker.get_summary()
            risk_mgr.state.capital = summary["cash"]

            self._replay_symbol(
                symbol=symbol,
                df_warmup=df_warmup,
                df_today=df_today,
                broker=broker,
                risk_mgr=risk_mgr,
                order_mgr=order_mgr,
                candle_log=result.candle_log,
            )

        # ── Collect results ───────────────────────────────────────────────
        summary = broker.get_summary()
        result.final_cash = round(summary["cash"], 2)

        trades = trade_log.get_all_trades(limit=500)
        result.trades = [t for t in trades if t.get("trading_mode") == "replay"]
        result.brokerage_total = round(
            sum(t.get("brokerage") or 0 for t in result.trades), 2
        )

        return result

    # ── Private helpers ───────────────────────────────────────────────────

    def _replay_symbol(
        self,
        symbol: str,
        df_warmup: pd.DataFrame,
        df_today: pd.DataFrame,
        broker: PaperBroker,
        risk_mgr: RiskManager,
        order_mgr: OrderManager,
        candle_log: list[dict],
    ) -> None:
        """Replay all candles of df_today for one symbol."""

        for i in range(len(df_today)):
            candle      = df_today.iloc[i]
            current_price = float(candle["close"])
            current_time  = df_today.index[i].time()
            ts_str        = str(df_today.index[i])[:16]

            # Build visible slice: warmup + candles up to and including i
            visible = pd.concat([df_warmup, df_today.iloc[: i + 1]])

            # Update broker LTP so exits use current price
            broker.update_ltp(symbol, current_price)

            if self._live_delay > 0:
                print(f"  [{ts_str}] {symbol} — scanning...")
                _time.sleep(self._live_delay)

            # ── First-candle blackout (before 9:20) ──────────────────
            if current_time < FIRST_CANDLE_BLACKOUT:
                candle_log.append({
                    "time":   ts_str,
                    "symbol": symbol,
                    "event":  "SKIP",
                    "detail": "First-candle blackout (<9:20)",
                })
                continue

            # ── EOD square-off at 15:15 ───────────────────────────────
            if current_time >= SQUAREOFF_TIME:
                if order_mgr.has_open_trade(symbol):
                    pnl = order_mgr.square_off_symbol(
                        symbol, f"End-of-day square-off @ {SQUAREOFF_TIME}"
                    )
                    candle_log.append({
                        "time":   ts_str,
                        "symbol": symbol,
                        "event":  "EXIT EOD",
                        "detail": f"Squared off @ ₹{current_price:.2f}  P&L: ₹{pnl:.0f}",
                    })
                    risk_mgr.on_position_closed(symbol, pnl or 0.0)
                break

            # ── Check exits for open positions ───────────────────────
            if order_mgr.has_open_trade(symbol):
                pnl = order_mgr.check_exits(symbol, current_price)
                if pnl is not None:
                    candle_log.append({
                        "time":   ts_str,
                        "symbol": symbol,
                        "event":  "EXIT",
                        "detail": f"Exit @ ₹{current_price:.2f}  P&L: ₹{pnl:.0f}",
                    })
                    risk_mgr.on_position_closed(symbol, pnl)
                else:
                    candle_log.append({
                        "time":   ts_str,
                        "symbol": symbol,
                        "event":  "HOLD",
                        "detail": f"Open trade, price=₹{current_price:.2f}",
                    })
                continue

            # ── No new entries after 14:30 ────────────────────────────
            if current_time >= NO_NEW_ENTRIES_TIME:
                candle_log.append({
                    "time":   ts_str,
                    "symbol": symbol,
                    "event":  "SKIP",
                    "detail": "No new entries after 14:30",
                })
                continue

            # Candle timestamp as timezone-aware datetime for RiskManager time gates
            candle_now = df_today.index[i].to_pydatetime()

            # ── Evaluate signals from each strategy ───────────────────
            for strategy in self._strats:
                signal = strategy.generate_signal(symbol, visible)

                if signal.action == Action.HOLD:
                    candle_log.append({
                        "time":   ts_str,
                        "symbol": symbol,
                        "event":  "HOLD",
                        "detail": f"{strategy.name} → no signal",
                    })
                    continue

                if signal.action == Action.SELL and not SHORT_SELLING_ENABLED:
                    candle_log.append({
                        "time":   ts_str,
                        "symbol": symbol,
                        "event":  "SKIP",
                        "detail": f"{strategy.name} SELL signal — short selling disabled",
                    })
                    continue

                # Pass candle time so Rules 6 & 7 use candle time not wall-clock
                decision = risk_mgr.evaluate(signal, now=candle_now)

                if not decision.approved:
                    candle_log.append({
                        "time":   ts_str,
                        "symbol": symbol,
                        "event":  "REJECTED",
                        "detail": f"{strategy.name} BUY — {decision.reason}",
                    })
                    continue

                # Place the order
                placed = order_mgr.execute_signal(decision.signal)
                if placed:
                    sig = decision.signal
                    risk_mgr.on_position_opened(sig.symbol)
                    candle_log.append({
                        "time":   ts_str,
                        "symbol": symbol,
                        "event":  sig.action.value,
                        "detail": (
                            f"{strategy.name} @ ₹{sig.entry_price:.2f}  "
                            f"qty={sig.quantity}  sl=₹{sig.stop_loss:.2f}  "
                            f"target=₹{sig.target:.2f}"
                        ),
                    })
                    break  # one trade per candle per symbol
                else:
                    candle_log.append({
                        "time":   ts_str,
                        "symbol": symbol,
                        "event":  "REJECTED",
                        "detail": f"{strategy.name} {signal.action.value} — broker rejected order",
                    })
