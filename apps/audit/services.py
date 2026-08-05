"""
Audit services - функции для записи и обработки audit logs.

Этот модуль содержит сервисные функции для:
- Извлечения IP адреса из request
- Определения типа объекта для аудита
- Нормализации значений для JSON
- Сбора изменений модели
- Записи audit log entries

ВАЖНО: Эти функции используются в views для явной записи действий.
Не используются signals для сохранения контекста бизнес-сценариев.
"""
from decimal import Decimal
from django.forms.models import model_to_dict
from django.utils.encoding import force_str
from .models import AuditLog


def get_client_ip(request):
    """
    Извлекает IP адрес клиента из HTTP request.

    Учитывает прокси-серверы (nginx, load balancers) проверяя заголовок
    X-Forwarded-For перед REMOTE_ADDR. Это необходимо в production среде.

    Аргументы:
        request: HttpRequest - объект запроса Django

    Возвращает:
        str или None - IP адрес клиента или None если request=None
    """
    if request is None:
        return None

    def _valid_ip(value):
        # Поле AuditLog.ip_address — inet-колонка Postgres, и «unknown» (типичный
        # ответ nginx, не распознавшего клиента) или мусор в X-Forwarded-For
        # роняли сохранение в DataError — 500 на любом аудируемом эндпоинте,
        # а на оплате откатывался весь платёж.
        try:
            import ipaddress
            ipaddress.ip_address(value)
            return True
        except ValueError:
            return False

    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        candidate = forwarded_for.split(',')[0].strip()
        if _valid_ip(candidate):
            return candidate

    remote_addr = request.META.get('REMOTE_ADDR')
    if remote_addr and _valid_ip(remote_addr):
        return remote_addr

    return None


def get_audit_object_type(instance):
    """
    Возвращает стабильное строковое представление типа модели для аудита.

    Использует формат "app_label.model_name" (например: "warehouse.RawMaterial").
    Не использует ContentType/GFK для сохранения читаемости при удалении моделей.

    Аргументы:
        instance: Model - экземпляр модели Django

    Возвращает:
        str - строка в формате "app_label.model_name"

    Пример:
        get_audit_object_type(raw_material) -> "warehouse.RawMaterial"
    """
    meta = instance._meta
    return f'{meta.app_label}.{meta.model_name}'


def normalize_audit_value(value):
    """
    Нормализует значение для безопасного хранения в JSONField.

    Преобразует сложные типы данных (Decimal, ForeignKey, FileField)
    в JSON-совместимые типы. Это предотвращает ошибки при сохранении
    и сохраняет читаемость audit logs.

    Аргументы:
        value: any - значение для нормализации

    Возвращает:
        any - нормализованное значение (str, int, None и т.д.)

    Преобразования:
        - Decimal -> str (сохраняет точность)
        - Model instance -> pk (для ForeignKey)
        - None/bool/int/float/str -> без изменений
        - остальные -> str (через force_str)
    """
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, 'pk'):
        return value.pk
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return force_str(value)


def collect_model_changes(instance, validated_data):
    """
    Собирает изменения полей модели перед сохранением.

    Сравнивает текущие значения модели с новыми данными из serializer.
    Записывает только реально изменившиеся поля для чистоты audit log.

    Аргументы:
        instance: Model - экземпляр модели до сохранения
        validated_data: dict - валидированные данные из serializer

    Возвращает:
        dict - словарь изменений в формате {field: {old: value, new: value}}

    Используется:
        - В perform_update() ViewSets для отслеживания изменений
    """
    changes = {}

    for field_name, new_value in validated_data.items():
        old_value = getattr(instance, field_name, None)
        if old_value != new_value:
            changes[field_name] = {
                'old': normalize_audit_value(old_value),
                'new': normalize_audit_value(new_value),
            }

    return changes


def collect_safe_request_changes(instance, data, allowed_fields):
    """
    Собирает изменения из request.data для безопасных полей.

    Используется для действий не проходящих через ModelViewSet.
    Явно указывает allowed_fields для предотвращения записи чувствительных
    данных (пароли, токены) в audit logs.

    Аргументы:
        instance: Model - экземпляр модели
        data: dict - данные из request.data
        allowed_fields: list - список безопасных для записи полей

    Возвращает:
        dict - словарь изменений в формате {field: {old: value, new: value}}

    Используется:
        - В обычных API views (не ViewSets)
        - Когда нужно контролировать какие поля записывать
    """
    changes = {}
    current_values = model_to_dict(instance, fields=allowed_fields)

    for field_name in allowed_fields:
        if field_name not in data:
            continue

        old_value = current_values.get(field_name)
        new_value = data.get(field_name)
        if str(old_value) != str(new_value):
            changes[field_name] = {
                'old': normalize_audit_value(old_value),
                'new': normalize_audit_value(new_value),
            }

    return changes


def write_audit_log(
    *,
    action,
    actor=None,
    target=None,
    object_type='system',
    object_id='',
    object_repr='',
    changes=None,
    metadata=None,
    request=None,
):
    """
    Создает запись в audit log.

    Единая точка записи всех действий в системе. Используется явно из views
    вместо signals для сохранения контекста бизнес-сценариев (кто, с какого IP,
    какой сценарий выполнялся).

    Аргументы:
        action: str - тип действия (из AuditLog.Action.choices)
        actor: User - пользователь, выполнивший действие (опционально)
        target: Model - объект, над которым выполнено действие (опционально)
        object_type: str - тип объекта (автоматически из target)
        object_id: str - ID объекта (автоматически из target)
        object_repr: str - строковое представление (автоматически из target)
        changes: dict - изменения полей (опционально)
        metadata: dict - дополнительная информация (опционально)
        request: HttpRequest - объект запроса для IP и User Agent (опционально)

    Возвращает:
        AuditLog - созданная запись аудита

    Особенности:
        - Автоматически извлекает object_type/object_id/object_repr из target
        - Сохраняет actor_username и actor_role для истории при удалении
        - Извлекает IP адрес и User Agent из request
        - Использует keyword-only аргументы для безопасности
    """
    if target is not None:
        object_type = get_audit_object_type(target)
        object_id = str(target.pk or '')
        object_repr = force_str(target)

    actor_is_authenticated = bool(
        actor and getattr(actor, 'is_authenticated', False)
    )

    return AuditLog.objects.create(
        company=getattr(actor, 'company', None) if actor_is_authenticated else None,
        actor=actor if actor_is_authenticated else None,
        actor_username=getattr(actor, 'username', '') if actor_is_authenticated else '',
        actor_role=getattr(actor, 'role', '') if actor_is_authenticated else '',
        action=action,
        object_type=object_type,
        object_id=object_id,
        object_repr=object_repr,
        changes=changes or {},
        metadata=metadata or {},
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '') if request else '',
    )
