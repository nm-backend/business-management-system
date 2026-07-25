from .base import *
from decouple import config

DEBUG = False
USE_X_FORWARDED_FOR = True

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
