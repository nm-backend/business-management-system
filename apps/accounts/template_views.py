from django.shortcuts import render, redirect
from .models import User


def _setup_done():
    """Первичная настройка завершена, когда создан супер-администратор платформы."""
    return User.objects.filter(role=User.Role.SUPERADMIN).exists()


def index_view(request):
    """Main entry point."""
    if not _setup_done():
        return redirect('setup-page')
    return render(request, 'index.html')

def login_view(request):
    """Login page."""
    if not _setup_done():
        return redirect('setup-page')
    if request.user.is_authenticated:
        return redirect('index')
    return render(request, 'accounts/login.html')

def setup_view(request):
    """Initial setup page (создание супер-администратора платформы)."""
    if _setup_done():
        return redirect('login-page')
    return render(request, 'accounts/setup.html')
