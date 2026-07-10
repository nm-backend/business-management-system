"""
Template views для клиентов.

Этот модуль содержит view функции для рендеринга HTML шаблонов клиентов.
"""
from django.shortcuts import render


def clients_view(request):
    """
    View для страницы клиентов.

    Рендерит HTML шаблон с интерфейсом управления клиентами.
    """
    return render(request, 'clients.html')
