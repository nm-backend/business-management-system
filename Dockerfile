# ── SkladPro.Nod — образ приложения (Django + Channels/ASGI) ──────────────
# Многоэтапная сборка: компиляторы нужны только для установки зависимостей и
# НЕ попадают в финальный образ (меньше вес и поверхность атаки).

# ---------- Этап 1: сборка зависимостей ----------
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Компиляторы нужны, если для пакета нет готового wheel.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Ставим в отдельный префикс, чтобы скопировать одним слоем в финальный образ.
RUN pip install --upgrade pip && pip install --prefix=/install -r requirements.txt

# ---------- Этап 2: финальный образ (без компиляторов) ----------
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Только рантайм-зависимости: netcat для ожидания БД, libpq5 для psycopg2,
# fonts-dejavu-core — кириллический TTF для PDF-экспорта (иначе кириллица в
# отчётах не рендерится на Linux; см. reports/views.register_report_font).
# build-essential/gcc намеренно НЕ ставим — их не должно быть в проде.
RUN apt-get update && apt-get install -y --no-install-recommends \
        netcat-openbsd \
        libpq5 \
        postgresql-client \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

COPY . .

RUN chmod +x /app/docker/entrypoint.sh

# ── Непривилегированный пользователь ──
# Раньше контейнер работал от root (uid=0): при RCE атакующий получал root.
# Каталоги статики/медиа отдаём пользователю, т.к. entrypoint пишет в них.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# entrypoint ждёт БД, применяет миграции и собирает статику, затем — CMD.
ENTRYPOINT ["/app/docker/entrypoint.sh"]
# $PORT задаётся платформой (Railway/Render); локальный compose переопределяет
# command и использует 8000. sh -c нужен для подстановки переменной.
CMD ["sh", "-c", "daphne -b 0.0.0.0 -p ${PORT:-8000} skladpro.asgi:application"]
