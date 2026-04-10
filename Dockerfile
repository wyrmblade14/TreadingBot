# ──────────────────────────────────────────────────────────────────────────────
# TreadingBot — Docker image
#
# Build:   docker build -t treadingbot .
# Run:     docker-compose up -d   (see docker-compose.yml)
#
# Python version: matches project requirement (3.14).
# If python:3.14-slim is not yet on Docker Hub, use python:3.13-slim as fallback.
# ──────────────────────────────────────────────────────────────────────────────

FROM python:3.14-slim

# Set IST timezone so APScheduler cron jobs fire at the correct wall-clock time
ENV TZ=Asia/Kolkata
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cached unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project
COPY . .

# Ensure the logs directory exists (will be overridden by volume mount)
RUN mkdir -p logs

# Make shell scripts executable
RUN chmod +x scripts/start_bot.sh scripts/start_dashboard.sh 2>/dev/null || true
