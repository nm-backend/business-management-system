"""
Test settings for SkladPro.

Использует in-memory SQLite для быстрых, изолированных unit-тестов,
не требующих запущенного PostgreSQL.

Значения окружения по умолчанию устанавливаются ДО импорта base.py
(в том числе до выполнения skladpro/settings/__init__.py), поэтому
настройки загружаются даже без файла .env. Этот модуль намеренно
расположен вне пакета skladpro.settings, чтобы os.environ.setdefault(...)
успел отработать раньше, чем пакет settings импортирует base.py.

Запуск тестов:
    DJANGO_SETTINGS_MODULE=skladpro.test_settings python manage.py test
"""
import os

os.environ.setdefault('SECRET_KEY', 'test-secret-key-not-for-production')
os.environ.setdefault('DB_NAME', 'test_db')
os.environ.setdefault('DB_USER', 'test')
os.environ.setdefault('DB_PASSWORD', 'test')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')

# Применить патч совместимости Django 5.1 + Python 3.14 ДО загрузки Django.
from skladpro.test_patch import apply as _apply_django_patch
_apply_django_patch()

from skladpro.settings.base import *  # noqa: E402,F401,F403

DEBUG = False

# Тестовый клиент Django ходит с Host: testserver.
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1', '*']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Ускоряет создание пользователей в тестах.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

MEDIA_ROOT = BASE_DIR / 'test_media'
