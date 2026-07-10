"""
URL configuration для HTML шаблонов производства.

Этот модуль содержит URL routing для HTML шаблонов управления производством.
"""
from django.urls import path
from . import template_views

urlpatterns = [
    path('production/', template_views.production_view, name='production-page'),
]
