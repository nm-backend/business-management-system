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
from datetime import timedelta
from pathlib import Path
from decouple import config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Секретный ключ Django для криптографии (берется из .env)
SECRET_KEY = config('SECRET_KEY')

# Установленные приложения Django
INSTALLED_APPS = [
    # Daphne должен идти первым: он подменяет runserver на ASGI (WebSocket).
    'daphne',

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
    'channels',  # WebSocket (real-time чат)
    'django_otp',  # Двухэтапное подтверждение (2FA)
    'django_otp.plugins.otp_totp',  # TOTP-приложения (Google Authenticator и др.)
    'django_otp.plugins.otp_static',  # Резервные коды восстановления

    # Local apps
    'apps.core',  # Базовые модели и утилиты
    'apps.companies',  # Компании (арендаторы) - мультикомпанийная изоляция
    'apps.accounts',  # Управление пользователями и аутентификация
    'apps.warehouse',  # Управление складом (сырье и готовая продукция)
    'apps.orders',  # Управление заказами
    'apps.production',  # Производство: задачи и подтверждение работ
    'apps.clients',  # Клиенты и оплаты
    'apps.finance',  # Расходы, ставки и выплаты работникам
    'apps.messaging',  # Сообщения и уведомления
    'apps.reports',  # Аналитика и экспорт отчетов
    'apps.audit',  # Система аудита действий
    'apps.backup',  # Резервное копирование (Celery Beat)
    
    'drf_spectacular',  # Автоматическая генерация OpenAPI схемы
    'django_celery_beat',  # Celery Beat scheduler
    # Бэкенд результатов задач в БД. Без этого приложения CELERY_RESULT_BACKEND
    # = 'django-db' не резолвится и воркер падает на старте
    # (ModuleNotFoundError: No module named 'django-db').
    'django_celery_results',
]

# Middleware - обработчики запросов
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',  # Безопасность (HTTPS, HSTS)
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Отдача собранной статики (Docker/prod); в DEBUG инертна
    'corsheaders.middleware.CorsMiddleware',  # CORS для фронтенда
    'django.contrib.sessions.middleware.SessionMiddleware',  # Сессии
    'django.middleware.common.CommonMiddleware',  # Общие функции
    'django.middleware.csrf.CsrfViewMiddleware',  # CSRF защита
    'django.contrib.auth.middleware.AuthenticationMiddleware',  # Аутентификация
    'django_otp.middleware.OTPMiddleware',  # request.user.is_verified() для 2FA
    'django.contrib.messages.middleware.MessageMiddleware',  # Сообщения
    'django.middleware.clickjacking.XFrameOptionsMiddleware',  # Защита от clickjacking
    'apps.core.middleware.SecurityHeadersMiddleware',  # CSP + Permissions-Policy
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
                'skladpro.context_processors.asset_version',
            ],
        },
    },
]

WSGI_APPLICATION = 'skladpro.wsgi.application'
ASGI_APPLICATION = 'skladpro.asgi.application'

# Канальный слой Channels для WebSocket.
# Если задан REDIS_URL (например, в Docker или production) — используем Redis
# (общий слой для нескольких воркеров). Иначе — in-memory (голый локальный
# runserver и тесты; Redis не требуется).
REDIS_URL = config('REDIS_URL', default='')
if REDIS_URL:
    # RedisPubSubChannelLayer — рекомендуемый бэкенд для pub/sub-рассылки групп:
    # надёжнее классического RedisChannelLayer и не шумит таймаутами brpop при
    # простое соединения.
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.pubsub.RedisPubSubChannelLayer',
            'CONFIG': {'hosts': [REDIS_URL]},
        },
    }
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        },
    }

# Настройки базы данных PostgreSQL
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME'),
        'USER': config('DB_USER'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST'),
        'PORT': config('DB_PORT', cast=int),
        'OPTIONS': {
            'client_encoding': 'UTF8',
        }
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
    # Аутентификация
    'DEFAULT_AUTHENTICATION_CLASSES': (
        # JWT + отметка last_activity сотрудника на каждом API-запросе.
        'apps.accounts.authentication.ActivityJWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',         # Django Admin
    ),

    # Генерация OpenAPI (Swagger / ReDoc)
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',

    # Разрешения по умолчанию
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),

    # Пагинация
    'DEFAULT_PAGINATION_CLASS': 'core.pagination.StandardPagination',
    'PAGE_SIZE': 20,

    # Фильтрация
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),

    # Форматы ответа
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
        # В development.py можно добавить:
        # 'rest_framework.renderers.BrowsableAPIRenderer',
    ),

    # DRF по умолчанию сам обрабатывает ?format=... для выбора рендерера и
    # отдаёт 404, если формат ему неизвестен. Экспорт отчётов использует
    # ?format=pdf — и кнопка «PDF» всегда возвращала 404, не доходя до вьюхи.
    # Отключаем перехват: параметр читают сами вьюхи экспорта.
    'URL_FORMAT_OVERRIDE': None,

    # Ограничение частоты запросов (защита от перебора кодов и паролей).
    # ScopedRateThrottle действует только на view с заданным throttle_scope,
    # поэтому остальные эндпоинты работают как прежде.
    # ScopedIPThrottle вместо ScopedRateThrottle: за reverse-proxy Django 5.1
    # не разворачивает X-Forwarded-For (USE_X_FORWARDED_FOR удалён из 4.1),
    # и все клиенты выглядели одним IP гейта. Кастомный троттл доверяет XFF
    # только от приватных прокси (см. apps/core/throttling.py).
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.UserRateThrottle',
        'apps.core.throttling.ScopedIPThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'user': '300/minute',
        'login': '10/min',               # подбор пароля
        'access_key_verify': '10/min',   # перебор кода доступа
        'access_key_redeem': '5/min',    # активация по коду
        'two_factor': '10/min',          # перебор 6-значного кода 2FA
    },
}

# Двухэтапное подтверждение (2FA)
# Название издателя в приложении-аутентификаторе (Google Authenticator и др.).
OTP_TOTP_ISSUER = 'SkladPro'
# Окно допуска по времени: ±1 шаг (30 с) компенсирует расхождение часов телефона.
# Больше делать нельзя — расширяет окно для перебора и повторного использования.
OTP_TOTP_SYNC = False
# Количество резервных кодов, выдаваемых при включении 2FA.
TWO_FACTOR_RECOVERY_CODE_COUNT = 10

# Настройки JWT токенов (Simple JWT)
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=45),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),  # Refresh токен живет 7 дней
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,  # Добавлять в blacklist после вращения
}

# Локализация и часовой пояс
# У Django НЕТ локали 'uz-cyrl', поэтому весь его интерфейс (админка, тексты
# ошибок, форматы дат) откатывался в английский — получалась смесь языков.
# 'ru' переведён в Django полностью. На язык SPA это не влияет: там свой
# переключатель (locale/*.json, по умолчанию узбекская кириллица).
LANGUAGE_CODE = 'ru'
TIME_ZONE = 'Asia/Bishkek'  # Часовой пояс Бишкека
USE_I18N = True  # Включить интернационализацию
USE_L10N = True  # Включить локализацию форматов
USE_TZ = True  # Включить поддержку часовых поясов
LOCALE_PATHS = [BASE_DIR / 'locale']  # Директория с файлами переводов

# Настройки статических файлов (CSS, JS, изображения)
# Ведущий слэш обязателен: с относительным 'static/' hard-reload на
# подстранице SPA (/orders/123/) резолвил стили в /orders/123/static/ — 404.
STATIC_URL = '/static/'  # URL для статических файлов
STATIC_ROOT = BASE_DIR / 'staticfiles'  # Директория для collectstatic
STATICFILES_DIRS = [BASE_DIR / 'static']  # Директория с исходными статическими файлами

# WhiteNoise: под ASGI-сервером (daphne в Docker/production) отдаёт собранную
# статику, включая статику Django Admin. Сжатие без manifest-хэширования —
# совместимо с ?v=ASSET_VERSION. В DEBUG WhiteNoise не мешает обычной раздаче.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}

# Настройки медиа файлов (загруженные пользователями)
MEDIA_URL = config('MEDIA_URL', default='/media/')  # URL для медиа файлов
MEDIA_ROOT = BASE_DIR / config('MEDIA_ROOT', default='media/')  # Директория для медиа файлов

# Максимальный размер загружаемого файла: 10 МБ
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB

# Тип авто-поля по умолчанию
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Версия статики для cache-busting (?v=...). Бампайте при изменении CSS/JS.
def _compute_asset_version():
    """
    Версия статики для ?v=... — считается по времени изменения файлов в static/.

    Раньше здесь стояла константа, которую нужно было помнить и бампать руками.
    Её забывали — и после деплоя браузеры продолжали крутить СТАРЫЕ js/css из
    кэша (воспроизведено: правка ui.js не доезжала до страницы, пока не сброшен
    кэш). Теперь любое изменение файла меняет версию само.

    ASSET_VERSION из окружения имеет приоритет: на проде удобно подставить хеш
    коммита, чтобы все инстансы отдавали одинаковую версию.
    """
    env_version = config('ASSET_VERSION', default='')
    if env_version:
        return env_version
    latest = 0
    for directory in (BASE_DIR / 'static',):
        if not directory.exists():
            continue
        for path in directory.rglob('*'):
            if path.is_file():
                latest = max(latest, int(path.stat().st_mtime))
    return str(latest or 1)


ASSET_VERSION = _compute_asset_version()

# URL для аутентификации
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# Настройки Swagger / ReDoc
SPECTACULAR_SETTINGS = {
    'TITLE': 'SkladPro ERP API',
    'DESCRIPTION': 'ERP система для управления камнеобрабатывающим бизнесом.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,

    # Не сбрасывать JWT после обновления страницы Swagger
    'SWAGGER_UI_SETTINGS': {
        'persistAuthorization': True,
    },
}

# ── Celery Configuration ──
# Брокер сообщений (Redis)
CELERY_BROKER_URL = config('REDIS_URL', default='redis://localhost:6379/0')
# Хранилище результатов (необязательно)
CELERY_RESULT_BACKEND = 'django-db'
# Сериализация
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
# Часовой пояс для Beat
CELERY_TIMEZONE = 'Asia/Bishkek'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# Логирование: пишем в stdout (12-factor: удобно для Docker/облака, где логи
# собираются из потока вывода). Уровень настраивается через LOG_LEVEL.
# disable_existing_loggers=False, чтобы не глушить логгеры Django/сторонних.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '{asctime} {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': config('LOG_LEVEL', default='INFO'),
    },
    'loggers': {
        # Ошибки обработки запросов (5xx) — всегда видны.
        'django.request': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}
