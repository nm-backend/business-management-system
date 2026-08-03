"""
Транслитерация для поиска (узбекский: латиница <-> кириллица).

Замечание тестировщика: клиента «Гулнора» не находили поиском «Gulnora» —
имя в базе кириллицей, а вводят латиницей (и наоборот). Здесь одна пара
функций: перевод строки в кириллицу/латиницу. Ищем по обоим вариантам
запроса через icontains — работает и на SQLite, и на PostgreSQL, без
расширений БД.

Пары длинные (sh/ch/o'/g'/ng) подставляются раньше одиночных букв,
иначе «sh» разобралось бы как «s»+«h».
"""
from django.db.models import Q

# длинные пары — до одиночных
LATIN_TO_CYRILLIC = [
    ('ng', 'нг'), ('ch', 'ч'), ('sh', 'ш'),
    ("o'", 'ў'), ("g'", 'ғ'),
    ('ya', 'я'), ('yu', 'ю'), ('yo', 'ё'), ('ts', 'ц'),
    ('a', 'а'), ('b', 'б'), ('d', 'д'), ('e', 'е'), ('f', 'ф'),
    ('g', 'г'), ('h', 'ҳ'), ('i', 'и'), ('j', 'ж'), ('k', 'к'),
    ('l', 'л'), ('m', 'м'), ('n', 'н'), ('o', 'о'), ('p', 'п'),
    ('q', 'қ'), ('r', 'р'), ('s', 'с'), ('t', 'т'), ('u', 'у'),
    ('v', 'в'), ('x', 'х'), ('y', 'й'), ('z', 'з'), ("'", 'ъ'),
]

CYRILLIC_TO_LATIN = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e',
    'ё': 'yo', 'ж': 'j', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k',
    'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
    'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'x', 'ц': 'ts',
    'ч': 'ch', 'ш': 'sh', 'щ': 'sh', 'ъ': "'", 'ы': 'i', 'ь': '',
    'э': 'e', 'ю': 'yu', 'я': 'ya',
    'ў': "o'", 'қ': 'q', 'ғ': "g'", 'ҳ': 'h', 'нг': 'ng',
}


def to_cyrillic(text):
    """Переводит латинскую строку в кириллицу (длинные пары первыми)."""
    lower = (text or '').lower()
    for pair in LATIN_TO_CYRILLIC:
        lower = lower.replace(pair[0], pair[1])
    return lower


def to_latin(text):
    """Переводит кириллическую строку в латиницу."""
    out = []
    for char in (text or '').lower():
        out.append(CYRILLIC_TO_LATIN.get(char, char))
    return ''.join(out)


def translit_variants(query):
    """
    Варианты запроса для поиска: исходный + латиница->кириллица +
    кириллица->латиница (уникальные, непустые).
    """
    q = (query or '').strip()
    if not q:
        return []
    variants = [q, to_cyrillic(q), to_latin(q)]
    return list(dict.fromkeys(v for v in variants if v))


def translit_search_qs(queryset, query, fields):
    """
    Фильтрует queryset по fields, матча хотя бы один вариант транслита.

    Исходный вариант тоже остаётся в OR: поле может быть уже латиницей,
    а запрос кириллицей — обратный вариант ловит это.

    Сравнение делаем в Python: LIKE в SQLite нечувствителен к регистру
    только для ASCII, а lower() тоже ASCII-only, поэтому «Гулнора» не
    матчится по «гулнора». Для масштаба ERP (сотни строк) Python-фильтр
    после первичного ограничения queryset — приемлемая цена за корректность.
    """
    variants = translit_variants(query)
    if not variants:
        return queryset
    lowered = [v.lower() for v in variants]
    rows = queryset.values('pk', *fields)
    keep = [
        row['pk']
        for row in rows
        if any(
            lv in str(row.get(field) or '').lower()
            for lv in lowered
            for field in fields
        )
    ]
    return queryset.filter(pk__in=keep)
