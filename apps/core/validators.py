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
