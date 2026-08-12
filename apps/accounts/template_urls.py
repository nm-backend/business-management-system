from django.urls import path, re_path

from . import template_views

urlpatterns = [
    path('', template_views.index_view, name='index'),
    path('accounts/login/', template_views.login_view, name='login-page'),
    path('accounts/setup/', template_views.setup_view, name='setup-page'),
    # SPA-fallback последним: всё, что не сматчили api/admin/static/media и
    # страницы выше, отдаётся index.html (GET только; см. spa_fallback_view).
    re_path(r'^.*$', template_views.spa_fallback_view),
]
