"""
URL configuration для HTML шаблонов сообщений.

Этот модуль содержит URL routing для HTML шаблонов управления сообщениями.
"""
from django.urls import path
from . import template_views

urlpatterns = [
    path('messages/', template_views.messages_view, name='messages-page'),
]
