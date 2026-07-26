#!/bin/sh
# =============================================================================
# SkladPro — Docker Entrypoint
# Runs on every container start in production.
# =============================================================================

set -e  # exit immediately on any error

echo "⏳ SkladPro — waiting for PostgreSQL..."
# Loop until pg_isready succeeds (max 60 seconds)
i=0
while ! pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge 30 ]; then
        echo "❌ PostgreSQL not ready after 30 attempts — exiting."
        exit 1
    fi
    sleep 2
done
echo "✓ PostgreSQL is ready."

echo "⏳ SkladPro — waiting for Redis..."
# Loop until redis-cli ping succeeds (max 30 seconds)
i=0
while ! redis-cli -h "$(echo "$REDIS_URL" | sed -n 's/.*redis:\/\///' | sed -n 's/\/.*//' | sed -n 's/:.*//' 2>/dev/null || echo 'redis')" ping >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge 15 ]; then
        echo "⚠ Redis not ready after 15 attempts — continuing anyway."
        break
    fi
    sleep 2
done
echo "✓ Redis is ready."

# Apply database migrations
echo "⏳ Running migrations..."
python manage.py migrate --noinput
echo "✓ Migrations applied."

# Collect static files (idempotent)
echo "⏳ Collecting static files..."
python manage.py collectstatic --noinput 2>/dev/null || true
echo "✓ Static files collected."

# Compile translation messages
echo "⏳ Compiling translations..."
python manage.py compilemessages --ignore=venv 2>/dev/null || true
echo "✓ Translations compiled."

# Start Daphne ASGI server
echo "🚀 Starting Daphne on 0.0.0.0:8000..."
exec daphne -b 0.0.0.0 -p 8000 \
    --access-log - \
    --proxy-headers \
    skladpro.asgi:application
