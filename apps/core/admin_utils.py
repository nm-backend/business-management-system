"""
Утилиты для Django Admin: цветные бейджи статусов и общие помощники,
чтобы админка выглядела как панель управления ERP, а не как дефолтный Django.
"""
from django.utils.html import format_html

# Пары (фон, текст) для светлых бейджей.
_COLORS = {
    'green': ('#e7f6ec', '#1a7f37'),
    'red': ('#fbe9e9', '#c9372c'),
    'amber': ('#fff4e5', '#9a5b00'),
    'blue': ('#e8f0fe', '#1c64d9'),
    'gray': ('#eef0f2', '#5a6472'),
    'purple': ('#f3ecfb', '#7a3ea8'),
    'teal': ('#e3f6f4', '#0f766e'),
}


def badge(text, color='gray'):
    """Возвращает HTML-бейдж (для использования в методах admin с @admin.display)."""
    bg, fg = _COLORS.get(color, _COLORS['gray'])
    return format_html(
        '<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
        'font-size:11px;font-weight:600;line-height:18px;background:{};color:{};'
        'white-space:nowrap;">{}</span>',
        bg, fg, text,
    )


def choice_badge(value, label, mapping):
    """Бейдж по значению choice: mapping = {value: color}."""
    return badge(label, mapping.get(value, 'gray'))


def bool_badge(value, true_text='Да', false_text='Нет'):
    """Зелёный/красный бейдж для булевых полей."""
    return badge(true_text if value else false_text, 'green' if value else 'red')
