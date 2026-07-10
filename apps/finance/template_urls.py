"""
URL configuration для HTML шаблонов финансов.

Этот модуль содержит URL routing для HTML шаблонов управления финансами.
"""
from django.urls import path
from . import template_views

urlpatterns = [
    path('finance/', template_views.finance_view, name='finance-page'),
]
