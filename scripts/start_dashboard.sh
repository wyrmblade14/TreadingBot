#!/bin/bash
# ──────────────────────────────────────────────────────────────────────
# TreadingBot dashboard startup wrapper — safe to call from cron.
# Starts Streamlit and keeps it running until 15:40 IST, then exits.
#
# Cron entry (managed by: python scripts/schedule_bot.py --install):
#   45 8 * * 1-5 /path/to/TreadingBot/scripts/start_dashboard.sh   # IST system
#   15 3 * * 1-5 /path/to/TreadingBot/scripts/start_dashboard.sh   # UTC system
# ──────────────────────────────────────────────────────────────────────

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python"
DASHBOARD="$PROJECT_DIR/dashboard/app.py"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "ERROR: venv not found at $VENV_PYTHON" >&2
    exit 1
fi

cd "$PROJECT_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') — Dashboard starting"
"$VENV_PYTHON" -m streamlit run "$DASHBOARD" \
    --server.address 0.0.0.0 \
    --server.port 8501 \
    --server.headless true \
    >> "$LOG_DIR/dashboard.log" 2>&1 &

DASH_PID=$!
echo "$(date '+%Y-%m-%d %H:%M:%S') — Dashboard PID $DASH_PID"

# Wait until 15:40 IST then kill the dashboard
while true; do
    HOUR=$(date +%H)
    MIN=$(date +%M)
    if [ "$HOUR" -gt 15 ] || ([ "$HOUR" -eq 15 ] && [ "$MIN" -ge 40 ]); then
        echo "$(date '+%Y-%m-%d %H:%M:%S') — Market closed, stopping dashboard"
        kill "$DASH_PID" 2>/dev/null || true
        exit 0
    fi
    sleep 60
done
