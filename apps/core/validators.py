"""
File upload validators for SkladPro.

Валидирует загружаемые файлы по типу содержимого (не по расширению)
и размеру. Предотвращает загрузку вредоносных файлов.
"""
import io
import struct
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


# Магические байты для валидации типов файлов
# (первые байты файла, уникальные для каждого формата)
MAGIC_BYTES = {
    # Изображения
    b'\xff\xd8\xff': 'image/jpeg',
    b'\x89PNG\r\n\x1a\n': 'image/png',
    b'GIF87a': 'image/gif',
    b'GIF89a': 'image/gif',
    b'RIFF': 'image/webp',  # .webp
    b'BM': 'image/bmp',
    # PDF
    b'%PDF': 'application/pdf',
    # Office
    b'PK\x03\x04': 'application/zip',  # .docx, .xlsx, .pptx
}

ALLOWED_IMAGE_MIMES = {
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp',
    'image/bmp',
}

ALLOWED_DOCUMENT_MIMES = {
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp',
    'application/pdf',
    'application/zip',  # .docx, .xlsx (они внутри ZIP)
}

# Максимальный размер файла: 10MB
MAX_UPLOAD_SIZE = 10 * 1024 * 1024


def get_mime_from_bytes(file_bytes):
    """
    Определяет MIME-тип по содержимому файла (магические байты).

    Аргументы:
        file_bytes: bytes - первые байты файла (хотя бы 8)

    Возвращает:
        str или None - MIME-тип если определён, иначе None
    """
    for magic, mime_type in MAGIC_BYTES.items():
        if file_bytes.startswith(magic):
            return mime_type
    return None


def validate_file_type(file_obj, allowed_mimes=None):
    """
    Валидирует тип файла по его содержимому (не по расширению).

    Аргументы:
        file_obj: UploadedFile - загруженный файл
        allowed_mimes: set - разрешённые MIME-типы

    Исключения:
        ValidationError - если тип файла не разрешён
    """
    if allowed_mimes is None:
        allowed_mimes = ALLOWED_IMAGE_MIMES

    # Читаем первые 32 байта для определения типа
    file_bytes = file_obj.read(32)
    file_obj.seek(0)  # Возвращаем указатель в начало

    mime_type = get_mime_from_bytes(file_bytes)

    if mime_type is None or mime_type not in allowed_mimes:
        raise ValidationError(
            _(f'Unsupported file type. Allowed types: {", ".join(allowed_mimes)}'),
            code='invalid_file_type',
        )


def validate_file_size(file_obj, max_size=None):
    """
    Валидирует размер файла.

    Аргументы:
        file_obj: UploadedFile - загруженный файл
        max_size: int - максимальный размер в байтах

    Исключения:
        ValidationError - если файл слишком большой
    """
    if max_size is None:
        max_size = MAX_UPLOAD_SIZE

    if file_obj.size > max_size:
        raise ValidationError(
            _(f'File size exceeds {max_size // (1024 * 1024)}MB limit.'),
            code='file_too_large',
        )


def validate_image_upload(file_obj):
    """
    Композитная валидация для загрузки изображений.

    Проверяет и тип, и размер файла одновременно.

    Аргументы:
        file_obj: UploadedFile - загруженный файл

    Исключения:
        ValidationError - если файл не проходит проверки
    """
    validate_file_size(file_obj)
    validate_file_type(file_obj, ALLOWED_IMAGE_MIMES)


def validate_document_upload(file_obj):
    """
    Композитная валидация для загрузки документов.

    Проверяет и тип, и размер файла одновременно.

    Аргументы:
        file_obj: UploadedFile - загруженный файл

    Исключения:
        ValidationError - если файл не проходит проверки
    """
    validate_file_size(file_obj)
    validate_file_type(file_obj, ALLOWED_DOCUMENT_MIMES)
