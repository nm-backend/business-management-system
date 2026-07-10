"""
Template views для сообщений.

Этот модуль содержит view функции для рендеринга HTML шаблонов сообщений.
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required


@login_required
def messages_view(request):
    """
    View для страницы сообщений.

    Рендерит HTML шаблон с интерфейсом управления сообщениями.
    """
    return render(request, 'messages.html')
