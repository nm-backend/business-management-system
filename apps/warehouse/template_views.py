"""
Template views для склада.

Этот модуль содержит view функции для рендеринга HTML шаблонов
страниц склада сырья и готовой продукции.
"""
from django.shortcuts import render


def warehouse_view(request):
    """
    View для страницы склада сырья.

    Рендерит HTML шаблон с интерфейсом управления складом сырья.
    """
    return render(request, 'warehouse.html')


def finished_products_view(request):
    """
    View для страницы готовой продукции.

    Рендерит HTML шаблон с интерфейсом управления готовой продукцией.
    """
    return render(request, 'finished_products.html')


def settings_view(request):
    """
    View для страницы настроек.

    Рендерит HTML шаблон с интерфейсом настроек профиля и пользователей.
    """
    return render(request, 'settings.html')
