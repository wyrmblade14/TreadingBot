"""
Trade Log — persists every trade to a SQLite database.

Why log trades?
  The only way to improve as a trader (or improve your bot) is to review
  your past trades. The trade log is your record of:
    - What signals the bot generated
    - What prices were filled
    - What the P&L was on each trade
    - Which strategies worked and which didn't

  After 30 days of paper trading, you should review this log to answer:
    - Which strategy has the highest win rate?
    - What time of day produces the best trades?
    - Which stocks work best with each strategy?

Database: SQLite (built into Python, no server needed)
Location: logs/trades.db

The log is append-only. We never delete or modify past trades.
"""

from __future__ import annotations

import os
from datetime import datetime, date
from pathlib import Path

from loguru import logger
from sqlalchemy import (
    Column, DateTime, Float, Integer, String, Text, create_engine, text
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


# ── Database setup ────────────────────────────────────────────────────

DB_PATH = Path(__file__).parent.parent / "logs" / "trades.db"
DB_PATH.parent.mkdir(exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class TradeRecord(Base):
    """SQLAlchemy ORM model for a single completed trade."""
    __tablename__ = "trades"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    date             = Column(String(10), nullable=False, index=True)   # YYYY-MM-DD
    timestamp        = Column(DateTime, nullable=False)                 # entry time
    exit_timestamp   = Column(DateTime, nullable=True)                  # exit time (NULL while open)
    symbol           = Column(String(20), nullable=False, index=True)
    action           = Column(String(4), nullable=False)   # BUY or SELL
    quantity         = Column(Integer, nullable=False)
    entry_price      = Column(Float, nullable=False)
    exit_price       = Column(Float, nullable=True)        # NULL for still-open trades
    stop_loss        = Column(Float, nullable=True)
    target           = Column(Float, nullable=True)
    pnl              = Column(Float, nullable=True)        # NULL until position closed
    brokerage        = Column(Float, nullable=True)
    net_pnl          = Column(Float, nullable=True)        # pnl - brokerage
    strategy         = Column(String(50), nullable=False)
    reason           = Column(Text, nullable=True)
    order_id         = Column(String(50), nullable=True)
    trading_mode     = Column(String(10), default="paper") # "paper" or "live"


def init_db() -> None:
    """Create tables if they don't exist. Safe to call multiple times."""
    is_new = not DB_PATH.exists()
    Base.metadata.create_all(engine)
    if is_new:
        logger.info(f"Trade database created at {DB_PATH}")
    else:
        # Add exit_timestamp column to existing databases that predate this field
        with engine.connect() as conn:
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(trades)")).fetchall()]
            if "exit_timestamp" not in cols:
                conn.execute(text("ALTER TABLE trades ADD COLUMN exit_timestamp DATETIME"))
                conn.commit()
                logger.info("Trade database migrated: added exit_timestamp column")
        logger.debug(f"Trade database ready at {DB_PATH}")


class TradeLogger:
    """
    Records trades to the SQLite database.

    Usage:
        log = TradeLogger()
        trade_id = log.record_entry(symbol="RELIANCE", action="BUY", ...)
        log.record_exit(trade_id, exit_price=510, pnl=1250)
    """

    def __init__(self) -> None:
        init_db()

    def record_entry(
        self,
        symbol: str,
        action: str,
        quantity: int,
        entry_price: float,
        stop_loss: float,
        target: float,
        strategy: str,
        reason: str = "",
        order_id: str = "",
        trading_mode: str = "paper",
    ) -> int:
        """
        Record a new trade entry. Returns the database row ID.
        Use this ID later to record the exit.
        """
        record = TradeRecord(
            date=date.today().isoformat(),
            timestamp=datetime.now(),
            symbol=symbol,
            action=action,
            quantity=quantity,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=target,
            strategy=strategy,
            reason=reason,
            order_id=order_id,
            trading_mode=trading_mode,
        )
        with SessionLocal() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            trade_id = record.id

        logger.info(
            f"TradeLog ENTRY #{trade_id} | {action} {quantity}×{symbol} "
            f"@ ₹{entry_price:.2f} | sl={stop_loss:.2f} target={target:.2f} "
            f"strategy={strategy}"
        )
        return trade_id

    def record_exit(
        self,
        trade_id: int,
        exit_price: float,
        brokerage: float = 0.0,
    ) -> float:
        """
        Update the exit price and calculate P&L for a trade.

        Returns net_pnl (P&L after brokerage).
        """
        with SessionLocal() as session:
            record = session.get(TradeRecord, trade_id)
            if record is None:
                logger.error(f"TradeLog: trade #{trade_id} not found")
                return 0.0

            record.exit_price     = exit_price
            record.exit_timestamp = datetime.now()
            record.brokerage      = brokerage

            if record.action == "BUY":
                raw_pnl = (exit_price - record.entry_price) * record.quantity
            else:
                raw_pnl = (record.entry_price - exit_price) * record.quantity

            record.pnl     = round(raw_pnl, 2)
            record.net_pnl = round(raw_pnl - brokerage, 2)
            session.commit()

            # Capture values before the session closes — accessing ORM attributes
            # after the with-block raises DetachedInstanceError (lazy loading fails).
            symbol  = record.symbol
            pnl     = record.pnl
            net_pnl = record.net_pnl

        logger.info(
            f"TradeLog EXIT #{trade_id} | {symbol} exit=₹{exit_price:.2f} "
            f"pnl=₹{pnl:.2f} brokerage=₹{brokerage:.2f} "
            f"net_pnl=₹{net_pnl:.2f}"
        )
        return net_pnl

    def get_today_trades(self) -> list[dict]:
        """Return all trades for today."""
        today = date.today().isoformat()
        with SessionLocal() as session:
            records = session.query(TradeRecord).filter(
                TradeRecord.date == today
            ).order_by(TradeRecord.timestamp).all()
            return [_record_to_dict(r) for r in records]

    def get_all_trades(self, limit: int = 200) -> list[dict]:
        """Return the most recent trades across all days."""
        with SessionLocal() as session:
            records = session.query(TradeRecord).order_by(
                TradeRecord.timestamp.desc()
            ).limit(limit).all()
            return [_record_to_dict(r) for r in records]

    def get_daily_pnl(self) -> list[dict]:
        """Return daily P&L summary grouped by date."""
        with SessionLocal() as session:
            rows = session.execute(text(
                """
                SELECT date,
                       COUNT(*)          AS num_trades,
                       SUM(pnl)          AS gross_pnl,
                       SUM(brokerage)    AS total_brokerage,
                       SUM(net_pnl)      AS net_pnl,
                       SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN net_pnl < 0 THEN 1 ELSE 0 END) AS losses
                FROM trades
                WHERE net_pnl IS NOT NULL
                GROUP BY date
                ORDER BY date DESC
                LIMIT 60
                """
            )).fetchall()
            return [dict(r._mapping) for r in rows]

    def get_rolling_win_rate(
        self, strategy: str, n: int = 20
    ) -> tuple[float | None, int]:
        """
        Return (win_rate_pct, trade_count) for the last *n* closed trades
        for a given strategy.

        Returns (None, 0) if there are no closed trades for the strategy.
        """
        with SessionLocal() as session:
            rows = session.execute(text(
                """
                SELECT net_pnl
                FROM trades
                WHERE strategy = :strategy AND net_pnl IS NOT NULL
                ORDER BY timestamp DESC
                LIMIT :n
                """
            ), {"strategy": strategy, "n": n}).fetchall()

        if not rows:
            return None, 0

        pnls  = [r[0] for r in rows]
        wins  = sum(1 for p in pnls if p > 0)
        count = len(pnls)
        return round(wins / count * 100, 1), count

    def get_strategy_summary(self) -> list[dict]:
        """Return P&L and win-rate summary per strategy."""
        with SessionLocal() as session:
            rows = session.execute(text(
                """
                SELECT strategy,
                       COUNT(*)          AS num_trades,
                       SUM(net_pnl)      AS total_net_pnl,
                       AVG(net_pnl)      AS avg_net_pnl,
                       SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) AS wins,
                       ROUND(
                           100.0 * SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) / COUNT(*), 1
                       ) AS win_rate_pct
                FROM trades
                WHERE net_pnl IS NOT NULL
                GROUP BY strategy
                ORDER BY total_net_pnl DESC
                """
            )).fetchall()
            return [dict(r._mapping) for r in rows]


def _record_to_dict(r: TradeRecord) -> dict:
    return {
        "id":             r.id,
        "date":           r.date,
        "timestamp":      r.timestamp.isoformat() if r.timestamp else None,
        "exit_timestamp": r.exit_timestamp.isoformat() if getattr(r, "exit_timestamp", None) else None,
        "symbol":         r.symbol,
        "action":       r.action,
        "quantity":     r.quantity,
        "entry_price":  r.entry_price,
        "exit_price":   r.exit_price,
        "stop_loss":    r.stop_loss,
        "target":       r.target,
        "pnl":          r.pnl,
        "brokerage":    r.brokerage,
        "net_pnl":      r.net_pnl,
        "strategy":     r.strategy,
        "reason":       r.reason,
        "order_id":     r.order_id,
        "trading_mode": r.trading_mode,
    }
