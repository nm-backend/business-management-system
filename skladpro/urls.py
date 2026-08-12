from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import FileResponse
from pathlib import Path

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)


# Шапка админки: по умолчанию Django показывает «Django administration».
admin.site.site_header = 'SkladPro.Nod — панель управления'
admin.site.site_title = 'SkladPro.Nod'
admin.site.index_title = 'Управление системой'


def service_worker(request):
    """Serve sw.js from root so it has natural scope '/' for push notifications."""
    sw_path = Path(settings.STATICFILES_DIRS[0]) / 'sw.js'
    response = FileResponse(open(sw_path, 'rb'), content_type='application/javascript')
    # SW должен всегда проверять обновления
    response.headers['Cache-Control'] = 'no-cache, must-revalidate'
    return response


urlpatterns = [
    path("sw.js", service_worker, name='service-worker'),
    path("admin/", admin.site.urls),

    # API
    path("api/v1/accounts/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.companies.urls")),
    path("api/v1/core/", include("apps.core.urls")),
    path("api/v1/warehouse/", include("apps.warehouse.urls")),
    path("api/v1/audit/", include("apps.audit.urls")),
    path("api/v1/orders/", include("apps.orders.urls")),
    path("api/v1/production/", include("apps.production.urls")),
    path("api/v1/clients/", include("apps.clients.urls")),
    path("api/v1/finance/", include("apps.finance.urls")),
    path("api/v1/messaging/", include("apps.messaging.urls")),
    path("api/v1/reports/", include("apps.reports.urls")),
    path("api/v1/backup/", include("apps.backup.urls")),

    # OpenAPI
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/v1/swagger/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/v1/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),

    # Frontend
    path("", include("apps.accounts.template_urls")),
]

handler403 = "skladpro.error_views.error_403"
handler404 = "skladpro.error_views.error_404"
handler500 = "skladpro.error_views.error_500"

# static()/media-паттерны должны идти РАНЬШЕ SPA-fallback (re_path ^.*$ в
# template_urls): иначе fallback матчится первым и кидает 404, а файлы не
# раздаются ни в dev (DEBUG), ни на PaaS (MEDIA_SERVE).
if settings.DEBUG:
    urlpatterns = [
        *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
        *static(
            settings.STATIC_URL,
            document_root=(
                settings.STATICFILES_DIRS[0]
                if settings.STATICFILES_DIRS
                else settings.STATIC_ROOT
            ),
        ),
        *urlpatterns,
    ]
elif getattr(settings, 'MEDIA_SERVE', False):
    # PaaS без nginx/Caddy (Railway/Render): /media/ отдаёт Django.
    # Опция MEDIA_SERVE задаётся в production.py из переменной окружения.
    urlpatterns = [
        *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
        *urlpatterns,
    ]