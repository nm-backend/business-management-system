# Развёртывание SkladPro.Nod без привязки к PaaS

Проект запускается на любом Linux-сервере с Docker: приложение и инфраструктура
разделены, все внешние адреса и секреты приходят из переменных окружения.
Render Blueprint и платформенные переменные Railway из репозитория удалены —
никакой хостинг здесь не является обязательным.

## Состав стека

```
интернет → nginx (TLS, :443) → daphne (:127.0.0.1:8000)
                               ├── PostgreSQL 16 (volume pg_data)
                               ├── Redis 7 (volume redis_data)
                               ├── Celery worker
                               └── Celery beat (django-celery-beat)
```

Файлы:

| Файл | Назначение |
|---|---|
| [`Dockerfile`](../Dockerfile) | образ приложения (non-root, daphne) |
| [`docker-compose.prod.yml`](../docker-compose.prod.yml) | web + worker + beat + PostgreSQL + Redis, fail-closed по секретам |
| [`deploy/nginx.conf`](nginx.conf) | TLS, WebSocket, health без буферизации, `/media/` через Django |
| [`docker/entrypoint.sh`](../docker/entrypoint.sh) | миграции, collectstatic, ensure_superuser |
| [`docker/healthcheck.py`](../docker/healthcheck.py) | проба контейнера под production-настройками |

## 1. Требования к серверу

- 2 vCPU / 4 ГБ RAM / 40 ГБ SSD (минимум 1/2/20);
- Ubuntu 22.04+ или Debian 12+, Docker Engine + compose plugin;
- открытые 80 и 443, исходящий доступ к registry и S3/Telegram (если используются);
- DNS A-записи `example.com` и `www.example.com` → IP сервера.

## 2. Переменные окружения

Создайте `.env.prod` рядом с `docker-compose.prod.yml` (файл в `.gitignore`,
права `chmod 600`). Обязательные:

| Переменная | Комментарий |
|---|---|
| `SECRET_KEY` | ≥ 50 символов, случайный, уникальный для инсталляции |
| `ALLOWED_HOSTS` | `example.com,www.example.com` — без `*` |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD` | пароль БД генерируется заново |
| `REDIS_PASSWORD` | пароль Redis |

Рекомендуемые:

| Переменная | Комментарий |
|---|---|
| `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD` | первый SuperAdmin создаётся автоматически |
| `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `SENTRY_RELEASE` | мониторинг ошибок |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | web-push уведомления |
| `AWS_STORAGE_BUCKET_NAME`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_ENDPOINT_URL`, `AWS_S3_REGION_NAME` | S3/R2 для media вместо локального тома |
| `PRIVATE_HEALTH_HOST` | имя, по которому внутренняя проба обращается к контейнеру, если оно отличается от `ALLOWED_HOSTS` |
| `PROTECTED_MEDIA_ACCEL_LOCATION` | `/protected-media/`, только если включили accel-блок в nginx |
| `SECURE_SSL_REDIRECT` | по умолчанию `True`; `False` только для отладки без TLS |

Сгенерировать ключ:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

## 3. Первый запуск

```bash
git clone <repo> /srv/skladpro && cd /srv/skladpro
cp .env.example .env.prod   # заполнить значения из таблиц выше
chmod 600 .env.prod

docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
docker compose -f docker-compose.prod.yml ps
```

Дождитесь `healthy` у `db`, `redis`, `web`. Миграции и `collectstatic`
выполняет entrypoint web-сервиса (у worker/beat `SKIP_INIT=1`).

Проверка без прокси:

```bash
curl -fsS -H "Host: example.com" http://127.0.0.1:8000/api/v1/core/health/
```

## 4. TLS

Certbot в режиме webroot (порт 80 уже слушает nginx, конфиг это учитывает):

```bash
sudo apt install -y certbot
sudo mkdir -p /var/www/certbot

# первый сертификат: временно поднимите только HTTP-блок из deploy/nginx.conf
sudo certbot certonly --webroot -w /var/www/certbot \
  -d example.com -d www.example.com --email admin@example.com --agree-tos

sudo cp deploy/nginx.conf /etc/nginx/sites-available/skladpro.conf
# замените домен в конфиге на свой
sudo ln -s /etc/nginx/sites-available/skladpro.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Продление уже настроено пакетом certbot. Проверьте `sudo certbot renew --dry-run`.
Сертификат должен покрывать **и apex, и `www`** — иначе `https://www.example.com`
даст ошибку имени; в конфиге оба имени сведены к одному `server_name`.

## 5. Обновление и откат

```bash
# обновление
git pull --ff-only
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build

# откат на предыдущий коммит
git checkout <previous-sha>
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

Образ собирается из текущего дерева, поэтому откат кода = откат контейнера.
Миграции назад не откатываются автоматически: перед обновлением, меняющим
схему, снимите дамп (ниже).

## 6. Резервное копирование и восстановление

Встроенный модуль (`apps/backup`) делает `pg_dump` + `media` и отправляет архив
в S3 или Telegram; расписание задаётся в интерфейсе SuperAdmin. Ручная копия:

```bash
# дамп БД
docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc > backup-$(date +%F).dump

# media (именованный том)
docker run --rm -v skladpro_media_data:/data -v "$PWD":/out alpine \
  tar czf /out/media-$(date +%F).tar.gz -C /data .
```

Восстановление на чистом сервере:

```bash
docker compose -f docker-compose.prod.yml up -d db redis
docker compose -f docker-compose.prod.yml exec -T db \
  pg_restore -U "$DB_USER" -d "$DB_NAME" --clean --if-exists < backup.dump
docker run --rm -v skladpro_media_data:/data -v "$PWD":/out alpine \
  sh -c "cd /data && tar xzf /out/media.tar.gz"
docker compose -f docker-compose.prod.yml up -d --build
```

Проверка восстановления обязательна: поднимите копию на отдельном порту/хосте
и сверьте контрольные суммы финансовых отчётов до переключения DNS.

## 7. Перенос с текущего хостинга

1. Зафиксируйте дамп БД, архив media и список переменных окружения (только имена).
2. Разверните новый сервер по шагам 1–3, примените миграции на пустой БД.
3. Восстановите дамп и media, перезапустите web/worker/beat.
4. Прогоните smoke: `/api/v1/core/health/`, вход, 404, загрузка и открытие фото,
   WebSocket-чат, выгрузка отчёта.
5. Снизьте TTL DNS до 300 с за сутки, переключите A-записи, проверьте TLS для
   apex и `www`. Старый сервер не выключайте 5–7 дней.

## 8. Диагностика

| Симптом | Причина | Что делать |
|---|---|---|
| 502 от nginx | web не healthy | `docker compose logs web`, проверить `db`/`redis` |
| 400 DisallowedHost в пробе | внутреннее имя не в `ALLOWED_HOSTS` | задать `PRIVATE_HEALTH_HOST` |
| Петля 301 | не передаётся `X-Forwarded-Proto` | проверить `proxy_set_header` в nginx |
| `unhealthy` у web | проба не получает 200 от health | `docker compose exec web python /app/docker/healthcheck.py` |
| Фото 404 после редеплоя | нет тома media и нет S3 | вернуть `media_data` или настроить S3 |
| Чат не подключается | нет upgrade-заголовков | блок `location /ws/` из `nginx.conf` |
