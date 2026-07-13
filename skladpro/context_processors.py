"""Контекст-процессоры проекта."""
from django.conf import settings


def asset_version(request):
    """
    Отдаёт версию статики в шаблоны для cache-busting (?v=...).

    Бампните ASSET_VERSION в settings при изменении CSS/JS, чтобы браузеры
    гарантированно получили свежие файлы, а не закешированные.
    """
    return {'ASSET_VERSION': getattr(settings, 'ASSET_VERSION', '1')}
