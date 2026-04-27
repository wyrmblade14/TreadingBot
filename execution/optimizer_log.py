"""
Optimizer Run Logger — persists strategy sweep results to SQLite and PostgreSQL.

Written after every `assign_strategies.py` run (weekly review).
Provides a historical record of which strategies were selected, with what
metrics, so you can track improvement (or regression) week over week.

Tables created:
  optimizer_runs  — one row per symbol per run
  optimizer_run_meta — one row per full sweep run

Storage:
  - SQLite: logs/trades.db (always, local backup)
  - PostgreSQL: DATABASE_URL env var (optional, same DB as live trades)
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

from loguru import logger
from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, String, create_engine, text
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

SQLITE_PATH = Path(__file__).parent.parent / "logs" / "trades.db"

_DB_URL = os.environ.get("DATABASE_URL")
if _DB_URL and not _DB_URL.startswith("sqlite"):
    _pg_engine = create_engine(_DB_URL, echo=False)
    _PgSession = sessionmaker(bind=_pg_engine)
else:
    _pg_engine = None
    _PgSession = None


class _Base(DeclarativeBase):
    pass


class OptimizerRun(_Base):
    """One row = one symbol's result in a weekly sweep."""
    __tablename__ = "optimizer_runs"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    run_date      = Column(String(10), nullable=False, index=True)   # YYYY-MM-DD
    run_timestamp = Column(DateTime, nullable=False)
    symbol        = Column(String(20), nullable=False, index=True)
    strategy      = Column(String(50), nullable=False)
    num_trades    = Column(Integer, nullable=False)
    win_rate      = Column(Float, nullable=False)
    sharpe        = Column(Float, nullable=False)
    score         = Column(Float, nullable=False)
    optimized     = Column(Boolean, default=False)
    lookback_days = Column(Integer, nullable=True)


_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS optimizer_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date      TEXT    NOT NULL,
    run_timestamp TEXT    NOT NULL,
    symbol        TEXT    NOT NULL,
    strategy      TEXT    NOT NULL,
    num_trades    INTEGER NOT NULL,
    win_rate      REAL    NOT NULL,
    sharpe        REAL    NOT NULL,
    score         REAL    NOT NULL,
    optimized     INTEGER NOT NULL DEFAULT 0,
    lookback_days INTEGER
)
"""


def _ensure_sqlite_table() -> None:
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(SQLITE_PATH) as conn:
        conn.execute(_SQLITE_DDL)
        conn.commit()


def _ensure_pg_table() -> None:
    if _pg_engine is None:
        return
    try:
        _Base.metadata.create_all(_pg_engine)
    except Exception as exc:
        logger.warning(f"OptimizerLog: could not create PG tables — {exc}")


def init_optimizer_log() -> None:
    """Create tables in both stores. Safe to call multiple times."""
    _ensure_sqlite_table()
    _ensure_pg_table()


def save_run(
    symbol: str,
    strategy: str,
    num_trades: int,
    win_rate: float,
    sharpe: float,
    score: float,
    optimized: bool = False,
    lookback_days: int | None = None,
) -> None:
    """
    Persist one symbol's sweep result to SQLite + Postgres.
    Never raises — logs warnings on failure so the sweep continues.
    """
    run_date = date.today().isoformat()
    run_ts   = datetime.now().isoformat(timespec="seconds")

    # ── SQLite ────────────────────────────────────────────────────────────
    try:
        _ensure_sqlite_table()
        with sqlite3.connect(SQLITE_PATH) as conn:
            conn.execute(
                """
                INSERT INTO optimizer_runs
                    (run_date, run_timestamp, symbol, strategy, num_trades,
                     win_rate, sharpe, score, optimized, lookback_days)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_date, run_ts, symbol, strategy, num_trades,
                 win_rate, sharpe, score, int(optimized), lookback_days),
            )
            conn.commit()
    except Exception as exc:
        logger.warning(f"OptimizerLog SQLite: failed for {symbol} — {exc}")

    # ── PostgreSQL ────────────────────────────────────────────────────────
    if _PgSession is None:
        return
    try:
        _ensure_pg_table()
        record = OptimizerRun(
            run_date=run_date,
            run_timestamp=datetime.now(),
            symbol=symbol,
            strategy=strategy,
            num_trades=num_trades,
            win_rate=win_rate,
            sharpe=sharpe,
            score=score,
            optimized=optimized,
            lookback_days=lookback_days,
        )
        with _PgSession() as session:
            session.add(record)
            session.commit()
        logger.debug(f"OptimizerLog PG: saved {symbol} → {strategy}")
    except Exception as exc:
        logger.warning(f"OptimizerLog PG: failed for {symbol} — {exc}")
