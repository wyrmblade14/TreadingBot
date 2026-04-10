"""
One-shot migration: copy all rows from logs/trades.db (SQLite) into PostgreSQL.

Run this once after the postgres container is up and before starting the bot
against the new database.

Usage:
    # 1. Start the postgres container
    docker-compose up -d postgres

    # 2. Wait ~10 seconds for it to become healthy, then run from the project root:
    python scripts/migrate_sqlite_to_postgres.py

    # 3. Verify the row count matches
    docker exec treadingbot_postgres psql -U treadingbot -d treadingbot -c "SELECT COUNT(*) FROM trades;"

Requirements:
    - DATABASE_URL must be set in .env and point to PostgreSQL (not SQLite)
    - logs/trades.db must exist

The script is idempotent: rows whose id already exists in PostgreSQL are skipped,
so it is safe to run more than once.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ── make project root importable ──────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text

# ── source: SQLite ─────────────────────────────────────────────────────
SQLITE_PATH = Path(__file__).parent.parent / "logs" / "trades.db"
if not SQLITE_PATH.exists():
    print(f"ERROR: SQLite file not found at {SQLITE_PATH}")
    sys.exit(1)

sqlite_engine = create_engine(f"sqlite:///{SQLITE_PATH}")

# ── destination: PostgreSQL ────────────────────────────────────────────
pg_url = os.environ.get("DATABASE_URL", "")
if not pg_url or pg_url.startswith("sqlite"):
    print("ERROR: DATABASE_URL must be set to a PostgreSQL URL in .env")
    print("  Example: postgresql://treadingbot:secret@localhost:5432/treadingbot")
    print("  Note: use 'localhost' when running this script outside Docker.")
    sys.exit(1)

pg_engine = create_engine(pg_url)

# ── ensure PostgreSQL schema exists ───────────────────────────────────
from execution.trade_log import Base
Base.metadata.create_all(pg_engine)

# ── migrate rows ───────────────────────────────────────────────────────
COLUMNS = [
    "id", "date", "timestamp", "exit_timestamp", "symbol", "action",
    "quantity", "entry_price", "exit_price", "stop_loss", "target",
    "pnl", "brokerage", "net_pnl", "strategy", "reason",
    "order_id", "trading_mode",
]
COL_LIST = ", ".join(COLUMNS)
PLACEHOLDERS = ", ".join(f":{c}" for c in COLUMNS)

with sqlite_engine.connect() as src, pg_engine.connect() as dst:
    rows = src.execute(text(f"SELECT {COL_LIST} FROM trades ORDER BY id")).fetchall()
    print(f"Found {len(rows)} row(s) in SQLite.")

    existing_ids = {
        r[0] for r in dst.execute(text("SELECT id FROM trades")).fetchall()
    }

    inserted = skipped = 0
    for row in rows:
        row_dict = dict(zip(COLUMNS, row))
        if row_dict["id"] in existing_ids:
            skipped += 1
            continue
        dst.execute(
            text(f"INSERT INTO trades ({COL_LIST}) VALUES ({PLACEHOLDERS})"),
            row_dict,
        )
        inserted += 1

    dst.commit()

print(f"Done. Inserted: {inserted}  Skipped (already existed): {skipped}")
