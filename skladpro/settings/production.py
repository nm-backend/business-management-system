from .base import *
from decouple import config
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.redis import RedisIntegration

DEBUG = False

# X-Forwarded-For для определения IP клиента обрабатывает ScopedIPThrottle
# (см. apps/core/throttling.py): Django 5.1 удалил USE_X_FORWARDED_FOR и
# TRUSTED_PROXIES, а за reverse-proxy иначе все клиенты — один IP гейта.

# Channels: в production канальный слой должен быть общим для всех воркеров —
# используем Redis (pub/sub-бэкенд). Задайте REDIS_URL в окружении.
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.pubsub.RedisPubSubChannelLayer',
        'CONFIG': {
            'hosts': [config('REDIS_URL', default='redis://127.0.0.1:6379/0')],
        },
    },
}

ALLOWED_HOSTS = config('ALLOWED_HOSTS', cast=lambda v: [s.strip() for s in v.split(',')])

# Railway (и другие PaaS) опрашивают healthcheck по внутреннему домену
# (RAILWAY_PRIVATE_DOMAIN, напр. business-management-system.railway.internal),
# которого обычно нет в ALLOWED_HOSTS. Без него Django отвечает 400 DisallowedHost,
# оркестратор считает контейнер нездоровым, и edge отдаёт 502 "Application failed
# to respond" при живом приложении (воспроизведено на боевом Railway).
# Добавляем приватный домен автоматически, если он задан и ещё не в списке.
_railway_private_domain = config('RAILWAY_PRIVATE_DOMAIN', default='')
if _railway_private_domain and _railway_private_domain not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_railway_private_domain)

# ── Защита: production не должен стартовать с небезопасными настройками ──
# Превращаем «тихий риск» (Django лишь предупреждает) в громкий отказ запуска.
from django.core.exceptions import ImproperlyConfigured  # noqa: E402

_INSECURE_SECRETS = {
    '', 'your-secret-key-here', 'change-me-to-a-long-random-string',
    'dev-insecure-secret-change-me', 'test-secret-key-not-for-production',
}
if (
    SECRET_KEY in _INSECURE_SECRETS
    or len(SECRET_KEY) < 50
    or SECRET_KEY.startswith('django-insecure-')
):
    raise ImproperlyConfigured(
        'Небезопасный SECRET_KEY в production. Сгенерируйте длинный случайный ключ и '
        'задайте его в переменной окружения SECRET_KEY (см. README → «Деплой»). '
        'Команда: python -c "from django.core.management.utils import '
        'get_random_secret_key; print(get_random_secret_key())"'
    )

if '*' in ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        'ALLOWED_HOSTS не должен содержать "*" в production — укажите конкретный домен.'
    )

CORS_ALLOW_ALL_ORIGINS = False
# Разрешённые origins для CORS. Задайте через env: https://skladpro.onrender.com
_CORS_ORIGINS = config('CORS_ALLOWED_ORIGINS', default='')
if _CORS_ORIGINS:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _CORS_ORIGINS.split(',') if o.strip()]

# CSRF trusted origins: Django 4.0+ требует явного указания HTTPS origins
# при работе за reverse-proxy. Без этого CSRF-проверка AJAX POST падает.
CSRF_TRUSTED_ORIGINS = [f'https://{h.strip()}' for h in ALLOWED_HOSTS if h.strip() and h.strip() != 'localhost']

# Security settings for production
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = 'DENY'

# HTTPS enforcement / HSTS. За reverse-proxy (nginx/gunicorn) заголовок
# X-Forwarded-Proto используется, чтобы Django понимал, что запрос пришёл по HTTPS.
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Health-эндпоинт исключён из HTTPS-редиректа. Оркестратор (Railway, k8s, ELB)
# опрашивает контейнер изнутри по обычному HTTP и без X-Forwarded-Proto, поэтому
# получал 301 вместо 200 и считал ЖИВОЙ контейнер нездоровым.
# Воспроизведено на Railway: "1/1 replicas never became healthy!", в логах
# приложения — "GET /api/v1/core/health/ 301" при работающем daphne.
# Весь остальной трафик по-прежнему принудительно уходит на HTTPS.
SECURE_REDIRECT_EXEMPT = [r'^api/v1/core/health/$']
SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=31536000, cast=int)  # 1 год
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_REFERRER_POLICY = 'same-origin'

# HttpOnly-cookie, чтобы session/CSRF не читались из JavaScript.
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True

# VAPID keys for Web Push (push-уведомления)
# Сгенерируйте ключи: python manage.py generate_vapid_keys
# И задайте в переменных окружения:
#   VAPID_PUBLIC_KEY=...
#   VAPID_PRIVATE_KEY=...
VAPID_PUBLIC_KEY = config('VAPID_PUBLIC_KEY', default='')
VAPID_PRIVATE_KEY = config('VAPID_PRIVATE_KEY', default='')
VAPID_SUBJECT = config('VAPID_SUBJECT', default='mailto:admin@skladpro.nod')

# Загруженные файлы (фото работ и т.п.) в production не раздаются ни Django
# (static() подключён только при DEBUG), ни WhiteNoise (он обслуживает только
# статику). На PaaS без nginx/Caddy это даёт 404 на все файлы в /media/.
# Включите MEDIA_SERVE=True, если фронтенд-прокси нет (Railway/Render);
# при наличии nginx/Caddy задайте False и отдавайте /media/ с него.
MEDIA_SERVE = config('MEDIA_SERVE', default=False, cast=bool)

# ── Media Storage: S3 (Cloudflare R2 / AWS S3 / MinIO) ──
# Render filesystem эфемерный: файлы теряются при redeploy/restart.
# Для сохранения фото задайте S3-переменные окружения:
#   AWS_STORAGE_BUCKET_NAME, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
#   AWS_S3_ENDPOINT_URL (для Cloudflare R2: https://<account-id>.r2.cloudflarestorage.com)
#   AWS_S3_REGION_NAME (для R2: auto)
# Если переменные не заданы — используется локальный файловый систем (эфемерный).
_AWS_BUCKET = config('AWS_STORAGE_BUCKET_NAME', default='')
if _AWS_BUCKET:
    STORAGES['default'] = {
        'BACKEND': 'storages.backends.s3boto3.S3Boto3Storage',
        'OPTIONS': {
            'bucket_name': _AWS_BUCKET,
            'region_name': config('AWS_S3_REGION_NAME', default='us-east-1'),
            'endpoint_url': config('AWS_S3_ENDPOINT_URL', default=None),
            'access_key': config('AWS_ACCESS_KEY_ID', default=''),
            'secret_key': config('AWS_SECRET_ACCESS_KEY', default=''),
            'default_acl': 'public-read',
            'querystring_auth': False,  # прямые URL без подписи
            'location': 'media',
        },
    }
    MEDIA_URL = f'https://{_AWS_BUCKET}.s3.amazonaws.com/media/'
    _endpoint = config('AWS_S3_ENDPOINT_URL', default='')
    if _endpoint:
        # Cloudflare R2 / MinIO: URL отличается от стандартного S3
        MEDIA_URL = f'{_endpoint}/{_AWS_BUCKET}/media/'

# ── Sentry Error Tracking ──
# Задайте SENTRY_DSN в переменных окружения для включения мониторинга.
# Без DSN Sentry не инициализируется — приложение работает как обычно.
_SENTRY_DSN = config('SENTRY_DSN', default='')
if _SENTRY_DSN:
    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            RedisIntegration(),
        ],
        # Производительность: 10% транзакций в normal mode, 100% приIssues.
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        # Отправка PII (IP, user info) — включаем для отладки инцидентов.
        send_default_pii=True,
        # Окружение и версия деплоя.
        environment=config('SENTRY_ENVIRONMENT', default='production'),
        release=config('SENTRY_RELEASE', default='skladpro@latest'),
        # Не логировать эти URL в Sentry (health check, static).
        before_send=lambda event, hint: event if '/core/health/' not in (event.get('request', {}).get('url', '') or '') else None,
    )
