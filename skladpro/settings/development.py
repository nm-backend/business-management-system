from .base import *
from decouple import config

DEBUG = True

# 10.0.2.2 — адрес хоста из Android-эмулятора (демо-APK ходит на dev-сервер через него).
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1,10.0.2.2,testserver', cast=lambda v: [s.strip() for s in v.split(',')])

CORS_ALLOW_ALL_ORIGINS = True

# Интерактивный браузерный интерфейс DRF доступен только в development.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ),
}
