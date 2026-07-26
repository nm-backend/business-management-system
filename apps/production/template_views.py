"""
Template views для производства.

Этот модуль содержит view функции для рендеринга HTML шаблонов производства.
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required


@login_required
def production_view(request):
    """
    View для страницы производства.

    Рендерит HTML шаблон с интерфейсом управления производством.
    """
    return render(request, 'production.html')
