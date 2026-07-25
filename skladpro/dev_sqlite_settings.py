"""Development settings with file-based SQLite for visual preview."""
import os

os.environ.setdefault('SECRET_KEY', 'dev-secret-key-not-for-production')
os.environ.setdefault('DB_NAME', 'dev_db')
os.environ.setdefault('DB_USER', 'dev')
os.environ.setdefault('DB_PASSWORD', 'dev')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')

from skladpro.settings.base import *  # noqa: E402,F401,F403

DEBUG = True
ALLOWED_HOSTS = ['*']
CORS_ALLOW_ALL_ORIGINS = True

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'dev_preview.sqlite3',
    }
}

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
MEDIA_ROOT = BASE_DIR / 'test_media'
