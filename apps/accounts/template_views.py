from django.http import Http404
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt


def index_view(request):
    """
    Точка входа SPA. Аутентификация — на стороне SPA (JWT), поэтому здесь
    не завязываемся на Django-сессию (иначе возможен цикл редиректов).
    """
    return render(request, 'index.html')


# Префиксы, которые fallback НЕ обслуживает, даже если они не сматчились
# раньше (API-мусор, отсутствующие статические файлы и т.п.) — для них
# остаётся честная 404.
SPA_FALLBACK_EXCLUDED_PREFIXES = ('/api/', '/admin/', '/static/', '/media/', '/sw.js')


@csrf_exempt
def spa_fallback_view(request):
    """
    SPA-fallback: любой неизвестный GET-путь отдаёт index.html.

    csrf_exempt обязателен: CSRF-проверка middleware срабатывает раньше
    нашей вьюхи, и POST-мусор по несуществующему пути (например,
    /api/v1/whatever/) возвращал простыню «CSRF cookie not set» вместо
    честной 404. Сама вьюха обрабатывает только GET, поэтому CSRF-защита
    тут не нужна — защищённые операции живут в DRF (csrf_exempt там
    тоже, но со своими проверками прав).
    """
    if request.method != 'GET':
        raise Http404
    if request.path.startswith(SPA_FALLBACK_EXCLUDED_PREFIXES):
        raise Http404
    return render(request, 'index.html')


def login_view(request):
    """
    Страница входа: логин/пароль ИЛИ активация по коду доступа.

    Рендерится ВСЕГДА. Раньше здесь стояла проверка «есть ли супер-админ», и на
    пустой базе вход редиректил на /accounts/setup/, откуда войти было нельзя
    (кода доступа ещё никто не выдал) — свежий деплой оказывался недоступен.
    Платформенный супер-администратор создаётся командой
    `python manage.py createsuperuser` (менеджер сам ставит role=superadmin,
    is_staff и is_superuser), дальше коды доступа сотрудникам выдаются из
    админки.
    """
    return render(request, 'accounts/login.html')


def setup_view(request):
    """
    Активация аккаунта по коду доступа, выданному в админке.

    Нужна не только при первой настройке: новые сотрудники активируются так же
    в любой момент, поэтому страница доступна всегда.
    """
    return render(request, 'accounts/setup.html')
