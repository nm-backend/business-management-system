"""CI settings: тесты на настоящем PostgreSQL (как в проде), а не SQLite.

Многие баги (гонки select_for_update, порядок агрегатов, unicode) проявляются
только на PostgreSQL — SQLite в test_settings их пропускает.
"""
import os

os.environ.setdefault('SECRET_KEY', 'ci-secret-key-not-for-production')
os.environ.setdefault('DB_NAME', 'skladpro_test')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASSWORD', 'postgres')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')

# Патч совместимости Django 5.1 + Python 3.14 ДО загрузки Django
from skladpro.test_patch import apply as _apply_django_patch
_apply_django_patch()

from skladpro.settings.base import *  # noqa: E402,F401,F403

DEBUG = False
ALLOWED_HOSTS = ['*']

# Ускоряет создание пользователей в тестах.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Высокие лимиты троттлинга — полный набор тестов не должен триггерить 429.
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] = {
    'user': '10000/minute',
    'login': '10000/min',
    'access_key_verify': '10000/min',
    'access_key_redeem': '10000/min',
    'two_factor': '10000/min',
}

MEDIA_ROOT = BASE_DIR / 'test_media'
