import json
from pathlib import Path
from django.conf import settings

def deep_merge(base, override):
    """Deep merge two dictionaries. Override values take precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result

def get_locale(lang_code='uz_cyrl'):
    """Load locale JSON file and return as dict."""
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

def format_currency(amount, currency_symbol='сом', decimal_places=0):
    """Format a number as currency string."""
    if amount is None:
        return ''
    if decimal_places == 0:
        formatted = f'{int(amount):,}'.replace(',', ' ')
    else:
        formatted = f'{amount:,.{decimal_places}f}'.replace(',', ' ')
    return f'{formatted} {currency_symbol}'
