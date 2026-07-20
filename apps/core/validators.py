"""
Валидаторы загрузки файлов (защита от вредоносных/чрезмерных загрузок).

DRF ImageField уже открывает файл через Pillow и отклоняет не-изображения
(например, .exe, переименованный в .png). Здесь добавляем ограничение размера
(защита от DoS большими файлами) и белый список расширений/типов.
"""
import os

from django.core.exceptions import ValidationError

MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 МБ
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
ALLOWED_IMAGE_CONTENT_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}


def parse_int_param(value, field_name):
    """
    Приводит query-параметр к int или возвращает 400 вместо 500.

    Без этого нечисловое значение (?skill=abc) доходит до ORM и выбрасывает
    ValueError: Field 'id' expected a number → HTTP 500. Любой авторизованный
    пользователь мог уронить обработчик одним GET-запросом (отказ в обслуживании
    и мусор в логах). SQL-инъекции здесь нет — ORM параметризует запросы, —
    но контракт API нарушался.
    """
    from rest_framework.exceptions import ValidationError as DRFValidationError
    try:
        return int(value)
    except (TypeError, ValueError):
        raise DRFValidationError({field_name: 'Ожидается числовой идентификатор.'})


def parse_date_param(value, field_name):
    """
    Приводит query-параметр к date или возвращает 400 вместо 500.

    Без этого нечисловая/кривая дата (?date_from=abc) доходила до ORM и роняла
    обработчик: Django бросал ValidationError, а reports — ValueError
    (Invalid isoformat string) -> HTTP 500. Любой авторизованный пользователь мог
    вызвать 500 одним GET. SQL-инъекции здесь нет (ORM параметризует запросы),
    но контракт API нарушался.
    """
    import datetime

    from rest_framework.exceptions import ValidationError as DRFValidationError
    try:
        return datetime.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise DRFValidationError({field_name: 'Ожидается дата в формате ГГГГ-ММ-ДД.'})


def validate_image_upload(f):
    """Проверяет размер, расширение и content-type загружаемого изображения."""
    if not f:
        return f

    size = getattr(f, 'size', 0) or 0
    if size > MAX_IMAGE_SIZE:
        raise ValidationError(
            f'Файл слишком большой ({size // (1024 * 1024)} МБ). Максимум — 5 МБ.'
        )

    ext = os.path.splitext(getattr(f, 'name', '') or '')[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError('Недопустимый тип файла. Разрешены: JPG, PNG, WEBP, GIF.')

    content_type = getattr(f, 'content_type', None)
    if content_type and content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise ValidationError('Недопустимый тип содержимого файла.')

    return f


def validate_file_size(value):
    """Ограничение размера загружаемого файла до 10 МБ."""
    limit = 10 * 1024 * 1024  # 10 MB
    if value.size > limit:
        raise ValidationError(
            f'Файл хажми {limit // (1024 * 1024)} МБ дан ошмаслиги керак.'
        )
