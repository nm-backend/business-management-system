from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/accounts/', include('apps.accounts.urls')),
    path('api/v1/core/', include('apps.core.urls')),
    path('api/v1/warehouse/', include('apps.warehouse.urls')),
    path('api/v1/audit/', include('apps.audit.urls')),
    # Future API endpoints
    # path('api/v1/orders/', include('apps.orders.urls')),
    # path('api/v1/production/', include('apps.production.urls')),
    # path('api/v1/clients/', include('apps.clients.urls')),
    # path('api/v1/finance/', include('apps.finance.urls')),
    # path('api/v1/messaging/', include('apps.messaging.urls')),
    # path('api/v1/reports/', include('apps.reports.urls')),
    
    # Frontend (Django Templates)
    path('', include('apps.accounts.template_urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0] if settings.STATICFILES_DIRS else settings.STATIC_ROOT)
