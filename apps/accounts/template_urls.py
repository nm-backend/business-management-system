from django.urls import path
from . import template_views

urlpatterns = [
    path('', template_views.index_view, name='index'),
    path('accounts/login/', template_views.login_view, name='login-page'),
    path('accounts/setup/', template_views.setup_view, name='setup-page'),
]
