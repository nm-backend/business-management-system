"""
Core utility functions.

Этот модуль содержит вспомогательные функции, используемые
в различных частях приложения для работы с локализацией,
форматирования данных и манипуляций со словарями.
"""
import json
from pathlib import Path
from django.conf import settings


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

    data = {}
    if fallback_file.exists():
        with open(fallback_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

    if lang_code != 'uz_cyrl' and locale_file.exists():
        with open(locale_file, 'r', encoding='utf-8') as f:
            lang_data = json.load(f)
            data = deep_merge(data, lang_data)

    return data


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
