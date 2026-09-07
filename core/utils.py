"""
Core utility functions.

Этот модуль содержит вспомогательные функции, используемые
в различных частях приложения для работы с локализацией,
форматирования данных и манипуляций со словарями.
"""
import json
from pathlib import Path
from django.conf import settings

# Кэш с проверкой mtime: словарь перезагружается, когда файл локали меняется.
# Раньше здесь был lru_cache — после правки перевода приходилось
# перезапускать сервер, иначе браузеры продолжали получать старый словарь.
_locale_cache = {}


def deep_merge(base, override):
    """
    Рекурсивно объединяет два словаря.

    Значения из override имеют приоритет над значениями из base.
    Если оба значения являются словарями, они объединяются рекурсивно.

    Аргументы:
        base: dict - базовый словарь
        override: dict - словарь с переопределяющими значениями

    Возвращает:
        dict - объединенный словарь

    Пример:
        base = {'a': 1, 'b': {'x': 10}}
        override = {'b': {'y': 20}, 'c': 3}
        result = {'a': 1, 'b': {'x': 10, 'y': 20}, 'c': 3}
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _read_locale_file(path):
    """Читает файл локали, переиспользуя кэш, пока файл не изменился."""
    key = str(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    cached = _locale_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    _locale_cache[key] = (mtime, data)
    return data


def get_locale(lang_code='uz_cyrl'):
    """
    Загружает файл локализации и возвращает как словарь.

    Использует uz_cyrl.json как fallback (резервный) язык.
    Если запрошенный язык отличается от fallback и файл существует,
    выполняется глубокое слияние для перевода только недостающих ключей.

    Аргументы:
        lang_code: str - код языка (например: 'uz_cyrl', 'ru')

    Возвращает:
        dict - словарь с переводами

    Логика:
        1. Загружает fallback файл (uz_cyrl.json) как базу
        2. Если запрошенный язык не fallback, загружает его файл
        3. Выполняет deep_merge для объединения переводов
    """
    locale_dir = Path(settings.BASE_DIR) / 'locale'
    locale_file = locale_dir / f'{lang_code}.json'
    fallback_file = locale_dir / 'uz_cyrl.json'

    data = _read_locale_file(fallback_file) or {}

    if lang_code != 'uz_cyrl':
        lang_data = _read_locale_file(locale_file)
        if lang_data is not None:
            data = deep_merge(data, lang_data)

    return data


def translate(key, lang_code='uz_cyrl', params=None):
    """
    Серверный аналог фронтового i18n.translate: точечный ключ + плейсхолдеры.

    Нужен уведомлениям и отчётам: их текст формирует сервер, а по ТЗ он должен
    быть на языке получателя. Раньше тексты уведомлений были захардкожены
    (узбекские в бизнес-событиях, русские в подписках), и язык пользователя
    вообще не учитывался.

    Соглашение для параметров: значение ключа-параметра, имя которого
    оканчивается на «_key», само считается ключом локали и переводится
    (например reason_key='refusal_reasons.no_time' подставится в {reason}).

    Аргументы:
        key: str - точечный ключ, например 'notifications.new_order'
        lang_code: str - язык получателя ('uz_cyrl', 'ru', 'ky')
        params: dict - подстановки вида {'id': 5} для шаблона «#{id}»

    Возвращает:
        str - переведённая строка; если ключа нет ни в языке, ни в uz_cyrl,
        возвращается сам ключ (как на фронтенде — видно, что перевод забыт).
    """
    if not key:
        return ''
    data = get_locale(lang_code or 'uz_cyrl')
    value = data
    for part in str(key).split('.'):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return key
    if not isinstance(value, str):
        return key

    if params:
        resolved = {}
        for name, val in params.items():
            if name.endswith('_key') and isinstance(val, str):
                resolved[name[:-4]] = translate(val, lang_code)
            else:
                resolved[name] = val
        for name, val in resolved.items():
            value = value.replace('{%s}' % name, '' if val is None else str(val))
    return value


def format_currency(amount, currency_symbol='som', decimal_places=0):
    """
    Форматирует число как строку валюты.

    Использует пробел как разделитель тысяч (согласно локали).
    Округляет до указанного количества десятичных знаков.

    Аргументы:
        amount: decimal/float/int - сумма для форматирования
        currency_symbol: str - символ валюты (по умолчанию 'som')
        decimal_places: int - количество десятичных знаков (по умолчанию 0)

    Возвращает:
        str - отформатированная строка валюты или пустая строка если amount=None

    Примеры:
        format_currency(12345.67) -> '12 346 som'
        format_currency(12345.67, '$', 2) -> '12 345.67 $'
        format_currency(None) -> ''
    """
    if amount is None:
        return ''
    if decimal_places == 0:
        formatted = f'{int(amount):,}'.replace(',', ' ')
    else:
        formatted = f'{amount:,.{decimal_places}f}'.replace(',', ' ')
    return f'{formatted} {currency_symbol}'
