"""
Template views для финансов.

Этот модуль содержит view функции для рендеринга HTML шаблонов финансов.
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required


@login_required
def finance_view(request):
    """
    View для страницы финансов.

    Рендерит HTML шаблон с интерфейсом управления финансами.
    """
    return render(request, 'finance.html')
