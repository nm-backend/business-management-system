"""
URL configuration для HTML шаблонов клиентов.

Этот модуль содержит URL routing для HTML шаблонов управления клиентами.
"""
from django.urls import path
from . import template_views

urlpatterns = [
    path('clients/', template_views.clients_view, name='clients-page'),
]
