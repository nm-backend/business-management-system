"""
URL configuration для HTML шаблонов заказов.

Этот модуль содержит URL routing для HTML шаблонов управления заказами.
"""
from django.urls import path
from . import template_views

urlpatterns = [
    path('orders/', template_views.orders_view, name='orders-page'),
]
