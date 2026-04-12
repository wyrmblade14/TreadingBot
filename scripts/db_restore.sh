#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# TreadingBot — Restore PostgreSQL from Oracle Object Storage backup
#
# Usage:
#   make db-restore DATE=2026-04-12        ← restore latest backup from that date
#   make db-restore OBJECT=backup-2026-04-12_02-00-01.sql.gz  ← specific file
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

BUCKET="treadingbot-backups"
DATE="${DATE:-}"
OBJECT="${OBJECT:-}"
TMPFILE="/tmp/treadingbot-restore.sql.gz"

# ── Find object ───────────────────────────────────────────────────────────────
if [[ -z "$OBJECT" ]]; then
    [[ -n "$DATE" ]] || { echo "Usage: make db-restore DATE=YYYY-MM-DD"; exit 1; }

    echo "Finding latest backup for ${DATE}..."
    OBJECT=$(oci os object list \
        --bucket-name "$BUCKET" \
        --prefix "backup-${DATE}" \
        --query 'data[-1].name' --raw-output 2>/dev/null || echo "")

    [[ -n "$OBJECT" && "$OBJECT" != "null" ]] \
        || { echo "No backup found for ${DATE} in bucket '${BUCKET}'"; exit 1; }
fi

echo "Restoring from: ${OBJECT}"
read -r -p "This will OVERWRITE the current database. Continue? [y/N] " CONFIRM
[[ "${CONFIRM,,}" == "y" ]] || { echo "Aborted."; exit 0; }

# ── Download ──────────────────────────────────────────────────────────────────
echo "Downloading ${BUCKET}/${OBJECT}..."
oci os object get \
    --bucket-name "$BUCKET" \
    --name        "$OBJECT" \
    --file        "$TMPFILE"

# ── Restore ───────────────────────────────────────────────────────────────────
echo "Stopping bot and dashboard-api..."
docker-compose stop bot watchdog dashboard-api 2>/dev/null || true

echo "Restoring database..."
gunzip -c "$TMPFILE" | docker exec -i treadingbot_postgres psql \
    -U "${POSTGRES_USER:-treadingbot}" \
    -d "${POSTGRES_DB:-treadingbot}"

rm -f "$TMPFILE"

echo "Restarting services..."
docker-compose start bot watchdog dashboard-api 2>/dev/null || true

echo "Restore complete from ${OBJECT}."
