# ──────────────────────────────────────────────────────────────────────────────
# TreadingBot — Optimized Multi-stage Docker image
# ──────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Core Builder (Minimal dependencies) ──────────────────────────────
FROM python:3.14-slim AS builder-core

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install build dependencies for C-extensions
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install core dependencies (needed by everything, including watchdog)
COPY requirements-base.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --user --prefer-binary -r requirements-base.txt


# ── Stage 2: Bot Builder (Adds heavy math/TA libs) ────────────────────────────
FROM builder-core AS builder-bot

# Install bot dependencies (heavy math/TA libs, needed by bot and api)
COPY requirements-bot.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --user --prefer-binary -r requirements-bot.txt


# ── Stage 3: Full Builder (Adds everything else) ──────────────────────────────
FROM builder-bot AS builder-full

# Install full dependencies (slowest, includes legacy streamlit)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --user --prefer-binary -r requirements.txt


# ── Stage 4: Runtime Base (Shared) ────────────────────────────────────────────
FROM python:3.14-slim AS runtime-base

# Set IST timezone
ENV TZ=Asia/Kolkata
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    libpq5 \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PATH=/root/.local/bin:$PATH


# ── Stage 5: Watchdog Runtime (Minimal) ───────────────────────────────────────
FROM runtime-base AS watchdog-runtime
COPY --from=builder-core /root/.local /root/.local
COPY . .
RUN mkdir -p logs && chmod +x scripts/*.sh 2>/dev/null || true
CMD ["python", "scripts/watchdog.py"]


# ── Stage 6: Bot Runtime (Standard) ───────────────────────────────────────────
FROM runtime-base AS bot-runtime
COPY --from=builder-bot /root/.local /root/.local
COPY . .
RUN mkdir -p logs && chmod +x scripts/*.sh 2>/dev/null || true
CMD ["python", "scripts/run_bot.py"]


# ── Stage 7: Full Runtime (All dependencies) ──────────────────────────────────
FROM runtime-base AS full-runtime
COPY --from=builder-full /root/.local /root/.local
COPY . .
RUN mkdir -p logs && chmod +x scripts/*.sh 2>/dev/null || true
CMD ["python", "scripts/run_bot.py"]
