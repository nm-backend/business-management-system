"""
Preview settings — lightweight SQLite-based dev server for live preview.

Usage:
    DJANGO_SETTINGS_MODULE=skladpro.settings.preview python manage.py migrate
    DJANGO_SETTINGS_MODULE=skladpro.settings.preview python manage.py runserver

Works on a fresh checkout — no .env file required.
"""
import os

# Set default env vars BEFORE importing base.py (via development.py)
# to avoid UndefinedValueError from python-decouple when .env is missing.
os.environ.setdefault('SECRET_KEY', 'preview-secret-key-not-for-production')
os.environ.setdefault('DB_NAME', 'preview')
os.environ.setdefault('DB_USER', 'preview')
os.environ.setdefault('DB_PASSWORD', 'preview')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')

from skladpro.settings.development import *  # noqa: E402,F401,F403

# ---- Override database to SQLite (file-based) ----
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'preview_db.sqlite3',  # noqa: F405
    }
}

# ---- Disable HTTPS security for preview ----
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0

# ---- Disable password validators for quick dev login ----
AUTH_PASSWORD_VALIDATORS = []

# ---- Allow all hosts for preview ----
ALLOWED_HOSTS = ['*']

# ---- Faster password hashing ----
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
