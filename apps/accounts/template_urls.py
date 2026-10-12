from django.urls import path, re_path

from . import template_views

urlpatterns = [
    path('', template_views.index_view, name='index'),
    path('accounts/login/', template_views.login_view, name='login-page'),
    path('accounts/setup/', template_views.setup_view, name='setup-page'),
    # SPA-fallback последним, НО исключаем /admin/ (regex negative lookahead)
    re_path(r'^(?!admin/).*$', template_views.spa_fallback_view),
]