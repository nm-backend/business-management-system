# SkladPro.Nod — Docker (краткий справочник)

Быстрый справочник по Docker-стеку для того, кто уже знает проект.
Для новичка/партнёра — см. [GETTING_STARTED.md](GETTING_STARTED.md).

## Стек
`docker-compose.yml` поднимает три сервиса:

| Сервис | Образ | Назначение | Том |
|--------|-------|------------|-----|
| `web` | сборка из `Dockerfile` (python:3.13-slim) | Django + Channels/ASGI (daphne) на :8000 | `media_data`, `static_data` (+ bind-mount кода `.:/app`) |
| `db` | `postgres:16-alpine` | PostgreSQL | `pg_data` |
| `redis` | `redis:7-alpine` | канальный слой Channels (WebSocket) | `redis_data` |

- Приложение работает по **ASGI** (daphne) → обслуживает и HTTP, и WebSocket `/ws/chat/`.
- Статику под daphne отдаёт **WhiteNoise** (включая статику Django Admin).
- Канальный слой: **RedisPubSubChannelLayer** (переключается автоматически, когда
  задан `REDIS_URL`; в compose = `redis://redis:6379/0`).
- `docker/entrypoint.sh` при старте ждёт БД → `migrate` → `collectstatic` → daphne.

## Ежедневные команды
```bash
docker compose up --build -d        # собрать и запустить в фоне
docker compose ps                   # статус
docker compose logs -f web          # логи приложения
docker compose restart web          # перечитать изменённый код (daphne не автоперезагружается)
docker compose down                 # остановить (данные в томах сохраняются)
docker compose down -v              # остановить и стереть данные (чистый старт)
```

## Разовые операции
```bash
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py migrate
docker compose exec web python manage.py shell
DJANGO_SETTINGS_MODULE=skladpro.test_settings \
  docker compose exec -e DJANGO_SETTINGS_MODULE=skladpro.test_settings web python manage.py test
```

## Переменные окружения
Значения по умолчанию заданы прямо в `docker-compose.yml`; переопределяются через
`.env` (см. `.env.docker.example`). Внутри стека `DB_HOST=db`, `REDIS_URL=redis://redis:6379/0`
зафиксированы. Для смены пароля БД / `SECRET_KEY` — создайте `.env`.

## Access Key в админке (онбординг сотрудников)
1. `Companies → Add` — компания + владелец за один шаг.
2. `Accounts → Users` — создать сотрудника (пароль можно не задавать).
3. Действие **«Сгенерировать Access Key»** или раздел **`Accounts → Access keys`**:
   код `SKP-XXXX-XXXX-XXXX`, статус, действия «Отозвать»/«Перевыпустить».
4. Сотрудник вводит код на `/accounts/login/` → «У меня есть код доступа» → задаёт пароль → вход.
   Код одноразовый.

## Production (кратко)
- `DJANGO_ENV=production`, `DEBUG=False`, реальные `SECRET_KEY`, `ALLOWED_HOSTS`, `REDIS_URL`.
- Запуск по ASGI: `daphne skladpro.asgi:application` (в образе уже так) или
  gunicorn+uvicorn-worker. Чистый WSGI не обслужит WebSocket.
- За nginx с HTTPS; проксировать `/ws/` с заголовками `Upgrade`/`Connection`.
- В `production.py` включены HSTS, secure-cookies, SSL-redirect.

## Проверка «здоровья»
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/accounts/login/   # 200
curl -s http://localhost:8000/api/v1/accounts/setup/check/                        # {"setup_required":...}
docker compose ps        # db и redis → healthy
```
