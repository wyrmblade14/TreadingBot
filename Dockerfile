# ──────────────────────────────────────────────────────────────────────────────
# TreadingBot — Optimized Multi-stage Docker image
# ──────────────────────────────────────────────────────────────────────────────

# Stage 1: Build & Dependencies
FROM python:3.14-slim AS builder

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install build dependencies for C-extensions (like psycopg2 or numpy if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies into a temporary directory
COPY requirements.txt .
RUN pip install --user -r requirements.txt


# Stage 2: Runtime
FROM python:3.14-slim AS runtime

# Set IST timezone
ENV TZ=Asia/Kolkata
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    libpq5 \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the installed packages from the builder stage
COPY --from=builder /root/.local /root/.local

# Ensure /root/.local/bin is in PATH
ENV PATH=/root/.local/bin:$PATH

# Copy the rest of the project
COPY . .

# Ensure necessary directories exist
RUN mkdir -p logs && chmod +x scripts/*.sh 2>/dev/null || true

# Default command can be overridden in docker-compose
CMD ["python", "scripts/run_bot.py"]
