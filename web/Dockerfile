# ──────────────────────────────────────────────────────────────────────────────
# TreadingBot — Optimized Next.js Docker image
# ──────────────────────────────────────────────────────────────────────────────

FROM node:22-alpine AS base
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

# Stage 1: Install dependencies
FROM base AS deps
# Use cache for npm install
COPY package.json package-lock.json* ./
RUN npm ci --prefer-offline --no-audit

# Stage 2: Build the application
FROM base AS builder
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* vars are baked into the JS bundle at build time.
# Pass the API URL so the browser knows where to find the Python API.
ARG NEXT_PUBLIC_DASHBOARD_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_DASHBOARD_API_URL=${NEXT_PUBLIC_DASHBOARD_API_URL}

RUN npm run build

# Stage 3: Runner
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# Only copy the necessary files from the builder
# standalone mode includes both node_modules and .next server files
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]

# Stage 4: Dev (for docker-compose)
FROM base AS dev
COPY --from=deps /app/node_modules ./node_modules
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]
