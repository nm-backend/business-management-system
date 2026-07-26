# =============================================================================
# SkladPro — Production Dockerfile
# Multi-stage build: builder → runtime
# =============================================================================

# --------------- Builder stage ---------------
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build-time system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    gettext \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --------------- Runtime stage ---------------
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=skladpro.settings.production \
    DJANGO_ENV=production \
    # Python output goes straight to terminal (no buffering)
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Runtime system dependencies + redis-cli for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    gettext \
    redis-tools \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# Copy application code
COPY . .

# Compile translation messages and collect static files
RUN python manage.py compilemessages --ignore=venv 2>/dev/null || true && \
    python manage.py collectstatic --noinput 2>/dev/null || true

# Create non-root user for security
RUN addgroup --system --gid 1001 skladpro && \
    adduser --system --uid 1001 --ingroup skladpro skladpro && \
    chown -R skladpro:skladpro /app

USER skladpro

EXPOSE 8000

# Healthcheck — Django returns 200 on /health/ (handled in skladpro/urls.py)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/', timeout=3)" || exit 1

# Entrypoint runs migrations, then starts Daphne
COPY scripts/entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
