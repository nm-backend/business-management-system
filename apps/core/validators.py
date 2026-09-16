"""
Валидаторы загрузки файлов (защита от вредоносных/чрезмерных загрузок).

DRF ImageField уже открывает файл через Pillow и отклоняет не-изображения
(например, .exe, переименованный в .png). Здесь добавляем ограничение размера
(защита от DoS большими файлами) и белый список расширений/типов.
"""
import os

from django.core.exceptions import ValidationError

from core.utils import translate

MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 МБ
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
ALLOWED_IMAGE_CONTENT_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}

# Вложения чата и задач: картинки + офисные документы. Белый список, а не
# чёрный: любой .exe/.sh/.php/.html, переименованный в разрешённое расширение,
# всё равно отдаётся из /media/ как файл, но исполняемым содержимым не станет,
# а html/svg исключены намеренно — они выполняют скрипты в контексте домена
# (хранимый XSS через ссылку на вложение).
ALLOWED_ATTACHMENT_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.webp', '.gif',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.txt',
}


def parse_int_param(value, field_name, lang='uz_cyrl'):
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
        raise DRFValidationError({field_name: translate('errors.validators.numeric_expected', lang)})


def parse_date_param(value, field_name, lang='uz_cyrl'):
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
        raise DRFValidationError({field_name: translate('errors.validators.date_format', lang)})


def validate_image_upload(f, lang='uz_cyrl'):
    """Проверяет размер, расширение и content-type загружаемого изображения."""
    if not f:
        return f

    size = getattr(f, 'size', 0) or 0
    if size > MAX_IMAGE_SIZE:
        raise ValidationError(
            translate('errors.validators.file_too_large', lang, {'size': size // (1024 * 1024)})
        )

    ext = os.path.splitext(getattr(f, 'name', '') or '')[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError(translate('errors.validators.invalid_file_type', lang))

    content_type = getattr(f, 'content_type', None)
    if content_type and content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise ValidationError(translate('errors.validators.invalid_content_type', lang))

    return f


def validate_file_size(value, lang='uz_cyrl'):
    """Ограничение размера загружаемого файла до 10 МБ."""
    limit = 10 * 1024 * 1024  # 10 MB
    if value.size > limit:
        raise ValidationError(
            translate('errors.validators.file_size_limit', lang,
                      {'size': value.size // (1024 * 1024), 'limit': limit // (1024 * 1024)})
        )


def validate_attachment_extension(value, lang='uz_cyrl'):
    """
    Белый список расширений для вложений (чат, задачи).

    Размер проверяет validate_file_size; здесь отсекаем типы, которые опасно
    отдавать обратно браузеру (.html, .svg — хранимый XSS) или бессмысленно
    хранить (.exe, .sh).
    """
    ext = os.path.splitext(value.name)[1].lower()
    if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        allowed = ', '.join(sorted(ALLOWED_ATTACHMENT_EXTENSIONS))
        raise ValidationError(translate('errors.validators.unsupported_file_type', lang, {'allowed': allowed}))


def validate_not_future(value, lang='uz_cyrl'):
    """
    Запрещает даты «из будущего».

    Найдено проверкой боевых эндпоинтов: принимались расход от 2030 года,
    приход материала завтрашним днём и оплата будущей датой. Такие записи
    выпадают из отчётов за текущий период (выручка занижается, расход не
    виден), а склад показывает поступление, которого ещё не было.
    """
    from django.utils import timezone

    if value is None:
        return
    now = timezone.now()
    # Поле может быть как датой, так и датой-временем.
    current = now if hasattr(value, 'hour') else timezone.localdate()
    if value > current:
        raise ValidationError(translate('errors.validators.date_in_future', lang))


PHONE_ALLOWED = set('0123456789 +-()')


def validate_phone(value, lang='uz_cyrl'):
    """
    Мягкая проверка телефона: цифры и разделители, минимум 5 цифр.

    Строгий формат задавать нельзя — номера бывают разных стран и с добавочными.
    Но текст вроде «не телефон вообще» раньше сохранялся как номер, и позвонить
    по такому контакту невозможно.
    """
    if not value:
        return
    text = str(value).strip()
    if set(text) - PHONE_ALLOWED or sum(ch.isdigit() for ch in text) < 5:
        raise ValidationError(translate('errors.validators.phone_invalid', lang))
