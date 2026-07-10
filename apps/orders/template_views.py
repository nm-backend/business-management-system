"""
Template views для заказов.

Этот модуль содержит view функции для рендеринга HTML шаблонов заказов.
"""
from django.shortcuts import render


def orders_view(request):
    """
    View для страницы заказов.

    Рендерит HTML шаблон с интерфейсом управления заказами.
    """
    return render(request, 'orders.html')
