#!/bin/bash
# ──────────────────────────────────────────────────────────────────────
# TreadingBot startup wrapper — safe to call from cron.
#
# Why a shell wrapper instead of calling Python directly from cron?
#   1. Cron runs with a minimal PATH — it doesn't know where the venv is.
#   2. We need to cd to the project root first (relative imports need it).
#   3. We capture stdout+stderr to a dated log in logs/cron/.
#
# Cron entry (install via: python scripts/schedule_bot.py --install):
#   45 8 * * 1-5 /path/to/TreadingBot/scripts/start_bot.sh   # IST system
#   15 3 * * 1-5 /path/to/TreadingBot/scripts/start_bot.sh   # UTC system
#   (08:45 IST = 03:15 UTC)
# ──────────────────────────────────────────────────────────────────────

set -e

# Absolute path to project root (same dir as this script's parent)
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python"
RUN_BOT="$PROJECT_DIR/scripts/run_bot.py"
CRON_LOG_DIR="$PROJECT_DIR/logs/cron"

# Create cron log dir if it doesn't exist
mkdir -p "$CRON_LOG_DIR"

# One cron-level log file per day (separate from the per-run bot log)
DATE=$(date +"%Y-%m-%d")
CRON_LOG="$CRON_LOG_DIR/$DATE.log"

echo "──────────────────────────────────────────" >> "$CRON_LOG"
echo "$(date '+%Y-%m-%d %H:%M:%S') — TreadingBot starting" >> "$CRON_LOG"
echo "PROJECT_DIR: $PROJECT_DIR" >> "$CRON_LOG"
echo "PYTHON: $VENV_PYTHON" >> "$CRON_LOG"

# Check venv exists
if [ ! -f "$VENV_PYTHON" ]; then
    echo "ERROR: venv not found at $VENV_PYTHON" >> "$CRON_LOG"
    echo "Run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt" >> "$CRON_LOG"
    exit 1
fi

# Change to project root so relative imports work
cd "$PROJECT_DIR"

# Run bot — output goes to cron log AND the per-run log inside the bot itself
"$VENV_PYTHON" "$RUN_BOT" >> "$CRON_LOG" 2>&1

echo "$(date '+%Y-%m-%d %H:%M:%S') — TreadingBot exited (code $?)" >> "$CRON_LOG"
