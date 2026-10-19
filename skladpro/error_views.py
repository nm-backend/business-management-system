"""HTML-страницы ошибок.

Страницы рендерятся на сервере, без JavaScript: при ошибке 500 скрипты могут
быть недоступны, а локализация не должна от них зависеть. Тексты берутся из
locale/*.json через тот же translate(), что и API/уведомления.
"""
from django.shortcuts import render

from core.utils import translate

DEFAULT_LANGUAGE = 'uz_cyrl'
SUPPORTED_LANGUAGES = ('uz_cyrl', 'ru', 'ky')
HTML_LANG = {'uz_cyrl': 'uz-Cyrl', 'ru': 'ru', 'ky': 'ky'}


def _language(request) -> str:
    """Язык страницы: выбор пользователя, затем Accept-Language, затем uz_cyrl."""
    user = getattr(request, 'user', None)
    lang = getattr(user, 'language', None) if user is not None else None
    if lang in SUPPORTED_LANGUAGES:
        return lang

    header = (request.META.get('HTTP_ACCEPT_LANGUAGE') or '').lower()
    for part in header.split(','):
        code = part.split(';')[0].strip()
        if code.startswith('ru'):
            return 'ru'
        if code.startswith(('ky', 'kir')):
            return 'ky'
        if code.startswith('uz'):
            return 'uz_cyrl'
    return DEFAULT_LANGUAGE


def _render(request, template: str, status: int):
    lang = _language(request)
    keys = (
        'forbidden_title', 'forbidden_detail',
        'not_found_title', 'not_found_detail',
        'server_error_title', 'server_error_detail',
        'back_to_home',
    )
    copy = {key: translate(f'errors.pages.{key}', lang) for key in keys}
    response = render(
        request,
        template,
        {'copy': copy, 'html_lang': HTML_LANG[lang]},
        status=status,
    )
    response['Content-Language'] = lang
    return response


def error_403(request, exception=None):
    return _render(request, 'errors/403.html', 403)


def error_404(request, exception=None):
    return _render(request, 'errors/404.html', 404)


def error_500(request):
    return _render(request, 'errors/500.html', 500)
