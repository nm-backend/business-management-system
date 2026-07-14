from .base import *
from decouple import config

DEBUG = False

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
