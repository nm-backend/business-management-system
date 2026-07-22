#!/usr/bin/env bash
# SkladPro.Nod — запуск всего стека одной командой (Linux/macOS).
# Docker + PostgreSQL + Redis + миграции + статика + health-check.
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "[ОШИБКА] Docker не найден. Установите Docker: https://docs.docker.com/get-docker/"
  exit 1
fi

echo "==> Поднимаю стек (docker compose up --build)..."
docker compose up -d --build

echo "==> Жду готовности приложения (health-check)..."
if curl -s --retry 60 --retry-delay 2 --retry-connrefused --max-time 5 \
     -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/core/health/ | grep -q 200; then
  echo
  echo "=============================================="
  echo " SkladPro запущен."
  echo " Сайт:    http://localhost:8000/"
  echo " Health:  http://localhost:8000/api/v1/core/health/"
  echo " Остановить:  docker compose down"
  echo "=============================================="
else
  echo "[ОШИБКА] Приложение не ответило 200. Логи: docker compose logs web"
  exit 1
fi
