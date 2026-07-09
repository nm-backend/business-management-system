from decimal import Decimal
from django.forms.models import model_to_dict
from django.utils.encoding import force_str
from .models import AuditLog


def get_client_ip(request):
    """
    Возвращает IP пользователя из request.

    В production Django часто стоит за proxy/nginx. В таком случае реальный IP
    может приходить в X-Forwarded-For, поэтому сначала проверяем этот заголовок,
    а потом обычный REMOTE_ADDR.
    """
    if request is None:
        return None

    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()

    return request.META.get('REMOTE_ADDR')


def get_audit_object_type(instance):
    """
    Даёт стабильное имя модели для журнала, например warehouse.RawMaterial.

    Мы не используем ContentType/GFK на этом этапе, потому что для аудита важнее
    неизменяемая строка-след: даже если объект потом архивируют или удалят в
    будущем, запись останется читаемой.
    """
    meta = instance._meta
    return f'{meta.app_label}.{meta.model_name}'


def normalize_audit_value(value):
    """
    Приводит значения моделей к JSON-безопасному виду.

    JSONField не умеет сохранять Decimal, файлы и связанные модели напрямую,
    поэтому сложные значения превращаются в строки. Это сохраняет аудит
    читаемым и не ломает запись лога.
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
    Собирает изменения перед serializer.save().

    DRF Serializer уже провалидировал данные, но объект ещё не сохранён.
    Поэтому можно сравнить старое значение модели с новым и записать в аудит
    только реально изменённые поля, без лишнего шума.
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
    Собирает изменения из обычного request.data для безопасных полей.

    Используется там, где действие не проходит через ModelViewSet. Мы явно
    передаём allowed_fields, чтобы случайно не записать пароль, токен или другие
    чувствительные данные в audit_logs.
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
    Единая точка записи audit_logs.

    Мы пишем аудит явно из views, а не через signal. Signal видит только факт
    сохранения модели, но не знает, кто пришёл через API, какой был IP и какой
    бизнес-сценарий выполнялся: создание аккаунта, блокировка, архивирование и
    т.д. Явный сервис делает журнал понятнее для владельца и разработчика.
    """
    if target is not None:
        object_type = get_audit_object_type(target)
        object_id = str(target.pk or '')
        object_repr = force_str(target)

    actor_is_authenticated = bool(
        actor and getattr(actor, 'is_authenticated', False)
    )

    return AuditLog.objects.create(
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
