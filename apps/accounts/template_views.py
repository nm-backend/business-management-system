from django.shortcuts import render, redirect
from .models import User


def _setup_done():
    """Первичная настройка завершена, когда создан супер-администратор платформы."""
    return User.objects.filter(role=User.Role.SUPERADMIN).exists()


def index_view(request):
    """
    Точка входа SPA. Аутентификация — на стороне SPA (JWT), поэтому здесь
    не завязываемся на Django-сессию (иначе возможен цикл редиректов).
    """
    if not _setup_done():
        return redirect('setup-page')
    return render(request, 'index.html')

def login_view(request):
    """
    Страница входа. Всегда рендерится (SPA сам решает, авторизован ли
    пользователь по JWT); не редиректим по Django-сессии.
    """
    if not _setup_done():
        return redirect('setup-page')
    return render(request, 'accounts/login.html')

def setup_view(request):
    """Initial setup page (создание супер-администратора платформы)."""
    if _setup_done():
        return redirect('login-page')
    return render(request, 'accounts/setup.html')
