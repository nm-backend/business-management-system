"""
Monkey-patch для совместимости Django 5.1.15 с Python 3.14.

Проблема:
  Python 3.14 убрал __dict__ у super() объектов.
  Django 5.1 использует copy(super()) в BaseContext.__copy__
  и RenderContext.__copy__, что ломается с ошибкой:
    AttributeError: 'super' object has no attribute 'dicts'

Фикс:
  Заменяем __copy__ методы, чтобы они копировали все атрибуты
  экземпляра через __dict__.update, а не через copy(super()).
"""


def _patched_base_context_copy(self):
    """
    BaseContext.__copy__ — без copy(super()).

    Создаёт новый экземпляр через __new__, копирует все атрибуты
    из __dict__ оригинала, затем заменяет dicts на свежую копию
    списка (чтобы мутация в копии не затронула оригинал).
    """
    duplicate = self.__class__.__new__(self.__class__)
    duplicate.__dict__.update(self.__dict__)
    # dicts — mutable-список, нужна отдельная копия
    duplicate.dicts = self.dicts[:]
    return duplicate


def apply():
    """
    Применить патчи. Вызови один раз при старте (до запуска тестов).
    Безопасно вызывать многократно — повторные вызовы ничего не делают.
    """
    from django.template import context as context_mod

    BaseContext = context_mod.BaseContext
    RenderContext = context_mod.RenderContext

    if getattr(BaseContext, '_skladpro_patched', False):
        return  # уже заплачено

    BaseContext.__copy__ = _patched_base_context_copy
    # RenderContext наследует BaseContext — логика та же, переиспользуем
    RenderContext.__copy__ = _patched_base_context_copy

    BaseContext._skladpro_patched = True
    RenderContext._skladpro_patched = True
