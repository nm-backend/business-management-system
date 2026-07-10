"""
URL configuration для HTML шаблонов склада.

Этот модуль содержит URL routing для HTML шаблонов управления складом,
готовой продукцией и настроек.
"""
from django.urls import path
from . import template_views

urlpatterns = [
    path('warehouse/', template_views.warehouse_view, name='warehouse-page'),
    path('finished-products/', template_views.finished_products_view, name='finished-products-page'),
    path('settings/', template_views.settings_view, name='settings-page'),
]
