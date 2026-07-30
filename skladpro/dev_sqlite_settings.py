"""Development settings with file-based SQLite for visual preview."""
import os

os.environ.setdefault('SECRET_KEY', 'dev-secret-key-not-for-production')
os.environ.setdefault('DB_NAME', 'dev_db')
os.environ.setdefault('DB_USER', 'dev')
os.environ.setdefault('DB_PASSWORD', 'dev')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')

# Патч совместимости Django 5.1 + Python 3.14 ДО загрузки Django
from skladpro.test_patch import apply as _apply_django_patch
_apply_django_patch()

from skladpro.settings.base import *  # noqa: E402,F401,F403

DEBUG = True
ALLOWED_HOSTS = ['*']
CORS_ALLOW_ALL_ORIGINS = True

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'dev_preview.sqlite3',
        'OPTIONS': {
            'timeout': 30,  # SQLite lock timeout (сек) для select_for_update
        },
    }
}

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Высокие лимиты троттлинга — 477 тестов за 8 с не должны триггерить 429.
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] = {
    'user': '10000/minute',
    'login': '10000/min',
    'access_key_verify': '10000/min',
    'access_key_redeem': '10000/min',
    'two_factor': '10000/min',
}

MEDIA_ROOT = BASE_DIR / 'test_media'
