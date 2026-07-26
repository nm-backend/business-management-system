from .base import *
from decouple import config

DEBUG = True

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=lambda v: [s.strip() for s in v.split(',')])

CORS_ALLOW_ALL_ORIGINS = True

# ---------- Dev tools (DEBUG only) ----------
if DEBUG:
    INSTALLED_APPS = [
        'debug_toolbar',       # SQL profiling, cache, signals, templates
        'django_extensions',   # shell_plus, show_urls, graph_models
    ] + INSTALLED_APPS

    MIDDLEWARE = [
        'debug_toolbar.middleware.DebugToolbarMiddleware',  # must be as early as possible
    ] + MIDDLEWARE

    # In Docker the host IP isn't localhost, so use the callback approach
    # to show toolbar for all requests when DEBUG=True.
    DEBUG_TOOLBAR_CONFIG = {
        'SHOW_TOOLBAR_CALLBACK': lambda request: True,
    }

    DEBUG_TOOLBAR_PANELS = [
        'debug_toolbar.panels.history.HistoryPanel',          # request history
        'debug_toolbar.panels.versions.VersionsPanel',         # Django/Python versions
        'debug_toolbar.panels.timer.TimerPanel',              # request timing
        'debug_toolbar.panels.settings.SettingsPanel',         # django.conf.settings
        'debug_toolbar.panels.headers.HeadersPanel',          # request/response headers
        'debug_toolbar.panels.request.RequestPanel',          # GET/POST/session/cookies
        'debug_toolbar.panels.sql.SQLPanel',                  # SQL queries (+ EXPLAIN)
        'debug_toolbar.panels.staticfiles.StaticFilesPanel',  # static files
        'debug_toolbar.panels.templates.TemplatesPanel',      # template rendering
        'debug_toolbar.panels.cache.CachePanel',              # cache calls
        'debug_toolbar.panels.signals.SignalsPanel',          # signals sent
        'debug_toolbar.panels.logging.LoggingPanel',          # log messages
        'debug_toolbar.panels.redirects.RedirectsPanel',      # redirect chain
    ]

# ---------- DRF: browsable API only in dev ----------
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ),
}
