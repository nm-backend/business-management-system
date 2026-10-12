from django.urls import path, re_path

from . import template_views

urlpatterns = [
    path('', template_views.index_view, name='index'),
    path('accounts/login/', template_views.login_view, name='login-page'),
    path('accounts/setup/', template_views.setup_view, name='setup-page'),
    # Служебные маршруты не должны попадать в SPA fallback.
    re_path(r'^(?!api/|admin/|static/|media/).*$', template_views.spa_fallback_view),
]