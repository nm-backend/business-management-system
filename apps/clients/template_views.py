"""
Template views для клиентов.

Этот модуль содержит view функции для рендеринга HTML шаблонов клиентов.
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required


@login_required
def clients_view(request):
    """
    View для страницы клиентов.

    Рендерит HTML шаблон с интерфейсом управления клиентами.
    """
    return render(request, 'clients.html')
