# SkladPro — Production Deployment Guide / Развёртывание на продакшене / Ишлаб чиқаришга жойлаштириш

## 📋 Requirements / Требования / Талаблар

- **Docker** ≥ 24.0
- **Docker Compose** ≥ 2.20
- **Domain** with DNS A-record pointing to your server IP
- **Ports**: 80 (HTTP), 443 (HTTPS) — open in firewall

## 🚀 Quick Start / Быстрый старт / Тез бошлаш

### 1. Clone / Клонировать репозиторий

```bash
git clone <repo-url> skladpro
cd skladpro
```

### 2. Configure environment / Настроить окружение / Муҳитни созлаш

```bash
cp .env.prod.example .env
# Edit .env with your values:
nano .env
```

**Critical variables to change (обязательно изменить):**

| Variable | Description | Example |
|----------|-------------|---------|
| `SECRET_KEY` | Django secret key (50+ chars) | `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `DB_PASSWORD` | PostgreSQL password | Strong random password |
| `ALLOWED_HOSTS` | Your domain(s) | `skladpro.example.com` |
| `CORS_ALLOWED_ORIGINS` | Frontend origin(s) | `https://skladpro.example.com` |

### 3. Start services / Запустить сервисы / Хизматларни ишга тушириш

```bash
docker compose build --pull
docker compose up -d
```

### 4. Verify / Проверить / Текшириш

```bash
# Healthcheck
curl http://localhost/health/

# Check logs
docker compose logs -f web

# Run tests inside container
docker compose exec web python manage.py test
```

### 5. Create admin / Создать администратора / Администратор яратиш

```bash
docker compose exec web python manage.py createsuperuser
```

## 🔐 SSL/TLS with Let's Encrypt

### Initial setup / Первоначальная настройка

1. Make sure DNS A-record points to this server:
   ```bash
   dig +short skladpro.example.com
   # → should return your server IP
   ```

2. Generate DH parameters (one-time, ~2 minutes):
   ```bash
   docker compose run --rm dhparam
   ```

3. Request the certificate:
   ```bash
   bash scripts/certbot-init.sh
   ```

4. Verify HTTPS:
   ```bash
   curl https://skladpro.example.com/health/
   ```

### Auto-renewal / Авто-обновление

The `certbot` container runs `certbot renew` every 24 hours automatically.
No additional cron job needed.

To force a manual renewal:
```bash
bash scripts/renew-cert.sh
```

### Certificate files / Файлы сертификатов

| File | Path in nginx |
|------|---------------|
| Certificate | `/etc/letsencrypt/live/$DOMAIN/fullchain.pem` |
| Private key | `/etc/letsencrypt/live/$DOMAIN/privkey.pem` |
| DH params | `/etc/nginx/dhparam.pem` |
| ACME challenge | `/var/www/certbot/.well-known/acme-challenge/` |

### Troubleshooting SSL / SSL проблемы

| Problem | Solution |
|---------|----------|
| Certificate request fails | Check DNS A-record. Port 80 must be open and reachable. |
| HTTPS returns 502 | Check if web container is running: `docker compose ps web` |
| Certificate expired | Run: `bash scripts/renew-cert.sh` |
| Rate limited by Let's Encrypt | Use staging first: `--test-cert` flag in nginx `ssl_certificate` |

## 📦 Architecture / Архитектура

```
                         Internet
                            |
                        [ Nginx :80/:443 ]
                         /              \
                /health/  ← →  /api/*   /static/*  /media/*
                    |              |         |          |
              [ Daphne :8000 ]   [ Nginx serves directly ]
                 /        \
          [ PostgreSQL ]  [ Redis ]
```

- **Nginx**: Reverse proxy, SSL termination, static/media serving, rate limiting, caching
- **Daphne**: Django ASGI server (handles HTTP + WebSocket)
- **PostgreSQL**: Primary database
- **Redis**: Caching, session storage, message broker for Django Channels

## 🔧 Service Details / Детали сервисов / Хизмат маълумотлари

### PostgreSQL (`skladpro-db`)

- Image: `postgres:16-alpine`
- Port: `127.0.0.1:5432` (localhost only)
- Volume: `skladpro_postgres_data`
- Healthcheck: `pg_isready` every 5s
- Resource limits: 1 CPU / 512MB RAM

### Redis (`skladpro-redis`)

- Image: `redis:7-alpine` with AOF persistence
- Port: internal only (exposed to web container)
- Volume: `skladpro_redis_data`
- Healthcheck: `redis-cli ping` every 5s
- Config: `--maxmemory 256mb --maxmemory-policy allkeys-lru`
- Resource limits: 0.5 CPU / 256MB RAM

### Django/Daphne (`skladpro-web`)

- Build: multi-stage Dockerfile (builder + runtime)
- Runs as **non-root user** (`skladpro:skladpro`, uid 1001)
- Port: `127.0.0.1:8000` (for debugging)
- Entrypoint: waits for DB+Redis → migrations → static → Daphne
- Resource limits: 2 CPU / 1GB RAM

### Nginx (`skladpro-nginx`)

- Image: `nginx:1.27-alpine`
- Ports: `80:80`, `443:443`
- Volumes: nginx.conf, static, media (read-only)
- Rate limiting: 3 zones (login, API, general)
- Security headers: CSP, HSTS, X-Frame-Options, etc.
- Resource limits: 0.5 CPU / 128MB RAM

## 🛡️ Security / Безопасность / Хавфсизлик

| Measure | Details |
|---------|---------|
| **Non-root user** | Django runs as `skladpro` (not root) |
| **PostgreSQL** | Bound to localhost only, not exposed publicly |
| **DB password** | Required via `.env`, never hardcoded |
| **Secret key** | Runtime validation: warns if <50 chars or auto-generated |
| **Rate limiting** | Nginx: login (5r/m), API (30r/m), general (10r/s) |
| **Security headers** | CSP, HSTS (1 year), X-Frame-Options, XSS, Content-Type |
| **CORS** | Explicit whitelist via `CORS_ALLOWED_ORIGINS` |
| **JWT** | 45min access token, 7-day refresh with blacklist rotation |
| **CSRF** | SameSite=Lax, HttpOnly cookies |
| **Healthcheck** | No auth required, but no data leaked |

## 📊 Monitoring / Мониторинг / Кузатиш

### Logs / Логи

```bash
# All services
docker compose logs --tail=100 -f

# Specific service
docker compose logs -f web
docker compose logs -f nginx
```

### Health / Состояние

```bash
# Application health
curl http://localhost/health/        # → "healthy"

# Database
docker compose exec db pg_isready -U skladpro

# Redis
docker compose exec redis redis-cli ping    # → "PONG"
```

### Resource usage / Использование ресурсов

```bash
docker compose stats
```

## 🔄 Backup / Резервное копирование / Захиралаш

### Database / База данных

```bash
# Manual backup
docker compose exec db pg_dump -U skladpro skladpro > backup_$(date +%Y%m%d_%H%M%S).sql

# Restore
cat backup.sql | docker compose exec -T db psql -U skladpro skladpro
```

### Volumes / Тома

```bash
# Backup all Docker volumes
docker run --rm -v skladpro_postgres_data:/source -v $(pwd)/backup:/backup \
    alpine tar czf /backup/postgres_data.tar.gz -C /source .
```

## 🛠️ Maintenance / Обслуживание / Хизмат кўрсатиш

### Update application / Обновить приложение

```bash
git pull
docker compose build --pull
docker compose up -d
```

### Restart service / Перезапустить сервис

```bash
docker compose restart web
```

### Full reset / Полный сброс (⚠️ destroys data)

```bash
docker compose down -v   # removes ALL volumes including DB
```

## 🐛 Troubleshooting / Устранение проблем / Муаммоларни ҳал қилиш

| Problem | Check |
|---------|-------|
| Container won't start | `docker compose logs <service>` |
| Database connection error | Is `DB_HOST=db`? Is DB running? `docker compose ps` |
| Static files 404 | `docker compose exec web python manage.py collectstatic --noinput` |
| Permission denied | Non-root user in container — check file ownership |
| "Secret key too short" warning | Generate a proper 64-char key via `secrets.token_urlsafe(64)` |
| Redis connection refused | `docker compose logs redis` — check `REDIS_URL` in `.env` |
| Nginx 502 Bad Gateway | Is web container running? `docker compose ps web` |
| Port already in use | Stop other services: `sudo systemctl stop nginx postgresql` |
