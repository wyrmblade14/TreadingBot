#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# TreadingBot — Daily PostgreSQL backup to Oracle Object Storage
#
# Runs inside the bot container at 02:00 IST (scheduled via APScheduler).
# Dumps the entire treadingbot database and uploads to OCI Object Storage.
# The bucket lifecycle policy deletes backups older than 30 days automatically.
#
# Requires on the host:
#   OCI CLI installed + configured:  pip install oci-cli && oci setup config
#   Bucket created:                  make oci-setup-services
#
# To restore:
#   make db-restore DATE=2026-04-12
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

BUCKET="treadingbot-backups"
DATE=$(date +%Y-%m-%d)
TIME=$(date +%H-%M-%S)
OBJECT="backup-${DATE}_${TIME}.sql.gz"
TMPFILE="/tmp/${OBJECT}"

# ── Dump ──────────────────────────────────────────────────────────────────────
echo "[backup] Starting pg_dump at $(date)"

docker exec treadingbot_postgres pg_dump \
    -U "${POSTGRES_USER:-treadingbot}" \
    -d "${POSTGRES_DB:-treadingbot}" \
    --no-password \
    | gzip > "$TMPFILE"

SIZE=$(du -sh "$TMPFILE" | cut -f1)
echo "[backup] Dump complete — ${SIZE}"

# ── Upload ────────────────────────────────────────────────────────────────────
echo "[backup] Uploading to OCI Object Storage: ${BUCKET}/${OBJECT}"

oci os object put \
    --bucket-name "$BUCKET" \
    --name        "$OBJECT" \
    --file        "$TMPFILE" \
    --no-multipart \
    --force

rm -f "$TMPFILE"
echo "[backup] Done — ${BUCKET}/${OBJECT} (${SIZE})"
