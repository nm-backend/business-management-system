from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import User

def index_view(request):
    """Main entry point."""
    if not User.objects.filter(role='owner').exists():
        return redirect('setup-page')
    return render(request, 'index.html')

def login_view(request):
    """Login page."""
    if not User.objects.filter(role='owner').exists():
        return redirect('setup-page')
    if request.user.is_authenticated:
        return redirect('index')
    return render(request, 'accounts/login.html')

def setup_view(request):
    """Initial setup page."""
    if User.objects.filter(role='owner').exists():
        return redirect('login-page')
    return render(request, 'accounts/setup.html')
