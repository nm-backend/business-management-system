#!/bin/sh
# Entrypoint контейнера web: дождаться БД → миграции → статика → запуск сервера.
set -e

DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"

echo "⏳ Ожидание PostgreSQL на ${DB_HOST}:${DB_PORT}..."
while ! nc -z "$DB_HOST" "$DB_PORT"; do
  sleep 0.5
done
echo "✅ PostgreSQL доступен."

echo "▶ Применение миграций..."
python manage.py migrate --noinput

echo "▶ Сборка статики..."
python manage.py collectstatic --noinput

echo "🚀 Запуск: $*"
exec "$@"
