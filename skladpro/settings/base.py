"""
Base Django settings for SkladPro project.

Этот файл содержит общие настройки Django, используемые во всех средах
(development, production). Специфичные настройки находятся в development.py
и production.py.

Основные настройки:
- Установленные приложения (INSTALLED_APPS)
- Middleware для обработки запросов
- Конфигурация базы данных PostgreSQL
- Настройки REST Framework и JWT аутентификации
- Настройки статических файлов и медиа
- Локализация и часовой пояс
"""
import os
from datetime import timedelta
from pathlib import Path
from decouple import config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Секретный ключ Django для криптографии (берется из .env)
SECRET_KEY = config('SECRET_KEY')

# Установленные приложения Django
INSTALLED_APPS = [
    # Django built-in apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third party apps
    'rest_framework',  # Django REST Framework для API
    'rest_framework_simplejwt',  # JWT аутентификация
    'rest_framework_simplejwt.token_blacklist',  # Blacklist для refresh токенов
    'corsheaders',  # CORS заголовки для фронтенда
    'django_filters',  # Фильтрация в DRF

    # Local apps
    'apps.core',  # Базовые модели и утилиты
    'apps.accounts',  # Управление пользователями и аутентификация
    'apps.warehouse',  # Управление складом (сырье и готовая продукция)
    'apps.orders',  # Управление заказами (заглушка)
    'apps.production',  # Управление производством (заглушка)
    'apps.clients',  # Управление клиентами (заглушка)
    'apps.finance',  # Финансовые отчеты (заглушка)
    'apps.messaging',  # Сообщения (заглушка)
    'apps.reports',  # Отчеты (заглушка)
    'apps.audit',  # Система аудита действий
]

# Middleware - обработчики запросов
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',  # Безопасность (HTTPS, HSTS)
    'corsheaders.middleware.CorsMiddleware',  # CORS для фронтенда
    'django.contrib.sessions.middleware.SessionMiddleware',  # Сессии
    'django.middleware.common.CommonMiddleware',  # Общие функции
    'django.middleware.csrf.CsrfViewMiddleware',  # CSRF защита
    'django.contrib.auth.middleware.AuthenticationMiddleware',  # Аутентификация
    'django.contrib.messages.middleware.MessageMiddleware',  # Сообщения
    'django.middleware.clickjacking.XFrameOptionsMiddleware',  # Защита от clickjacking
]

ROOT_URLCONF = 'skladpro.urls'

# Настройки шаблонов
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],  # Директория с шаблонами
        'APP_DIRS': True,  # Искать шаблоны в директориях apps
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'skladpro.wsgi.application'
ASGI_APPLICATION = 'skladpro.asgi.application'

# Настройки базы данных PostgreSQL
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME'),
        'USER': config('DB_USER'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST'),
        'PORT': config('DB_PORT', cast=int),
    }
}

# Кастомная модель пользователя
AUTH_USER_MODEL = 'accounts.User'

# Валидаторы паролей Django
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Настройки Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',  # JWT токены
        'rest_framework.authentication.SessionAuthentication',  # Сессии (для админки)
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',  # Требовать аутентификацию по умолчанию
    ),
    'DEFAULT_PAGINATION_CLASS': 'core.pagination.StandardPagination',  # Кастомная пагинация
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',  # Фильтрация по полям
        'rest_framework.filters.SearchFilter',  # Поиск по тексту
        'rest_framework.filters.OrderingFilter',  # Сортировка
    ),
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',  # JSON ответ
        'rest_framework.renderers.BrowsableAPIRenderer',  # HTML интерфейс для отладки
    )
}

# Настройки JWT токенов (Simple JWT)
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=45),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),  # Refresh токен живет 7 дней
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,  # Добавлять в blacklist после вращения
}

# Локализация и часовой пояс
LANGUAGE_CODE = 'uz-cyrl'  # Узбекский (кириллица) по умолчанию
TIME_ZONE = 'Asia/Bishkek'  # Часовой пояс Бишкека
USE_I18N = True  # Включить интернационализацию
USE_L10N = True  # Включить локализацию форматов
USE_TZ = True  # Включить поддержку часовых поясов
LOCALE_PATHS = [BASE_DIR / 'locale']  # Директория с файлами переводов

# Настройки статических файлов (CSS, JS, изображения)
STATIC_URL = 'static/'  # URL для статических файлов
STATIC_ROOT = BASE_DIR / 'staticfiles'  # Директория для collectstatic
STATICFILES_DIRS = [BASE_DIR / 'static']  # Директория с исходными статическими файлами

# Настройки медиа файлов (загруженные пользователями)
MEDIA_URL = config('MEDIA_URL', default='/media/')  # URL для медиа файлов
MEDIA_ROOT = BASE_DIR / config('MEDIA_ROOT', default='media/')  # Директория для медиа файлов

# Тип авто-поля по умолчанию
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# URL для аутентификации
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'
