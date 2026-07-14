# ── SkladPro.Nod — образ приложения (Django + Channels/ASGI) ──────────────
FROM python:3.13-slim

# Служебные переменные окружения Python.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Системные зависимости:
#   netcat-openbsd — ожидание готовности PostgreSQL в entrypoint;
#   остальное — на случай сборки пакетов без готовых wheel (psycopg2 и т.п.).
RUN apt-get update && apt-get install -y --no-install-recommends \
        netcat-openbsd \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Зависимости — отдельным слоем для кэширования.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Исходный код.
COPY . .

RUN chmod +x /app/docker/entrypoint.sh

EXPOSE 8000

# entrypoint ждёт БД, применяет миграции и собирает статику, затем — CMD.
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "skladpro.asgi:application"]
