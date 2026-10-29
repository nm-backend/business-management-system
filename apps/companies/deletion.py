"""
Единственный сервис полного удаления компании (платформенное действие).

Это осознанное исключение из правила «удаление = архивация»: приложение в
основном архивирует бизнес-объекты, но тестовые компании нужно удалять целиком.
Сервис вызывается только из API супер-администратора; Django-админка прямое
удаление компании закрывает.

Что важно для безопасности:
  * строка компании блокируется (select_for_update), чтобы двойной клик и два
    параллельных запроса не удаляли одну компанию дважды;
  * подтверждение — точное имя компании (Unicode NFC, пробелы схлопываются,
    регистр учитывается); проверка повторяется на сервере, а не только в UI;
  * действующая платная подписка и системная компания удалить нельзя;
  * аудит платформенный: company=None, иначе запись каскадно исчезнет вместе
    с тенантом; бизнес-данные в запись не попадают;
  * медиафайлы и WebSocket-соединения трогаются только после успешного
    коммита — при откате транзакции ничего не удаляется и не закрывается.
"""
import logging
import unicodedata

from django.db import transaction

from apps.audit.models import AuditLog
from apps.audit.services import write_audit_log

from .models import Company

logger = logging.getLogger(__name__)


class CompanyDeletionError(Exception):
    """Ожидаемый отказ удаления: код переводит view, статус — HTTP."""

    def __init__(self, code, status_code):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def normalize_company_name(value):
    """Нормализует имя для сравнения: NFC, trim и схлопывание пробелов."""
    if not isinstance(value, str):
        return ''
    return ' '.join(unicodedata.normalize('NFC', value).split())


def _is_active_paid_subscription(company):
    """
    Действующая платная подписка: active/grace, не триал и цена тарифа > 0.

    История продлений намеренно не блокирует: отдельной модели платежей нет,
    а записи SubscriptionChange — это журнал изменений, а не подтверждение
    оплаты. Иначе нельзя было бы удалить тестовые компании, на которых
    проверяли продление подписки.
    """
    if company.is_trial:
        return False
    plan = company.plan
    if plan is None or plan.price <= 0:
        return False
    return company.effective_subscription_status in (
        Company.SubscriptionStatus.ACTIVE,
        Company.SubscriptionStatus.GRACE,
    )


def _collect_media_files(company):
    """
    Собирает (storage, name) всех файлов, которые исчезнут вместе с компанией.

    Обходим ровно те модели, у которых есть FileField/ImageField внутри
    каскада Company. Делаем это до удаления: после CASCADE путей уже нет.
    """
    from apps.accounts.models import User
    from apps.finance.models import Expense
    from apps.messaging.models import ChatMessage
    from apps.orders.models import Order
    from apps.production.models import Task, WorkPhoto, WorkRecord
    from apps.warehouse.models import FinishedProduct, RawMaterial

    files = []

    def add(instance, *field_names):
        for field_name in field_names:
            uploaded = getattr(instance, field_name)
            if uploaded and uploaded.name:
                files.append((instance._meta.get_field(field_name).storage, uploaded.name))

    add(company, 'logo')
    for user in User.objects.filter(company=company).only('id', 'avatar'):
        add(user, 'avatar')
    for expense in Expense.objects.filter(company=company).only('id', 'receipt_photo'):
        add(expense, 'receipt_photo')
    for message in ChatMessage.objects.filter(company=company).only('id', 'attachment'):
        add(message, 'attachment')
    for order in Order.objects.filter(company=company).only('id', 'photo'):
        add(order, 'photo')
    for task in Task.objects.filter(company=company).only(
        'id', 'attachment', 'refusal_attachment',
    ):
        add(task, 'attachment', 'refusal_attachment')
    for work in WorkRecord.objects.filter(company=company).only('id', 'photo'):
        add(work, 'photo')
    for photo in WorkPhoto.objects.filter(work__company=company).only('id', 'image'):
        add(photo, 'image')
    for material in RawMaterial.objects.filter(company=company).only('id', 'photo'):
        add(material, 'photo')
    for product in FinishedProduct.objects.filter(company=company).only('id', 'photo'):
        add(product, 'photo')

    # Один и тот же файл теоретически может быть привязан к двум записям.
    unique = []
    seen = set()
    for storage, name in files:
        if name in seen:
            continue
        seen.add(name)
        unique.append((storage, name))
    return unique


def _delete_media_files(files):
    """Удаляет файлы после коммита. Ошибка storage не откатывает удаление."""
    for storage, name in files:
        try:
            storage.delete(name)
        except Exception:  # noqa: BLE001 — файл уже не вернуть, но и 500 не нужен
            logger.exception('Не удалось удалить медиафайл компании: %s', name)


def _delete_refresh_tokens(company):
    """
    Удаляет refresh-токены сотрудников до удаления пользователей.

    SimpleJWT хранит OutstandingToken.user с SET_NULL: после CASCADE пользователя
    токены остались бы сиротами. Удаление строк делает refresh недействительным;
    BlacklistedToken уходит каскадом.
    """
    try:
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
    except Exception:  # noqa: BLE001 — приложение blacklist может быть не установлено
        return
    OutstandingToken.objects.filter(user__company=company).delete()


def _close_user_sockets(user_ids):
    """Закрывает активные чат-сокеты сотрудников после коммита."""
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    layer = get_channel_layer()
    if layer is None or not user_ids:
        return
    for user_id in user_ids:
        try:
            async_to_sync(layer.group_send)(
                f'chat_user_{user_id}',
                {'type': 'force_disconnect'},
            )
        except Exception:  # noqa: BLE001 — Redis/канал недоступен, компания уже удалена
            logger.exception('Не удалось закрыть WebSocket пользователя %s', user_id)


def _after_commit(files, user_ids):
    _delete_media_files(files)
    _close_user_sockets(user_ids)


def delete_company(*, company_id, actor, confirm_name, request=None):
    """
    Полностью удаляет компанию и все её данные одной транзакцией.

    Args:
        company_id: pk компании.
        actor: супер-администратор, выполняющий удаление.
        confirm_name: введённое имя компании (проверяется здесь повторно).
        request: HttpRequest для IP/User-Agent платформенного аудита.

    Raises:
        CompanyDeletionError: ожидаемый отказ с кодом для перевода.
    """
    with transaction.atomic():
        try:
            # select_related('plan') здесь нельзя: plan nullable, и PostgreSQL
            # запрещает FOR UPDATE на nullable стороне outer join. Тариф
            # загружаем отдельным запросом внутри транзакции.
            company = Company.objects.select_for_update().get(pk=company_id)
        except (Company.DoesNotExist, TypeError, ValueError) as error:
            # ValueError — некорректный pk в URL (например, /companies/abc/).
            raise CompanyDeletionError('not_found', 404) from error

        if company.is_system:
            raise CompanyDeletionError('delete_system_company', 409)

        if actor is not None and getattr(actor, 'company_id', None) == company.pk:
            raise CompanyDeletionError('delete_own_company', 403)

        if _is_active_paid_subscription(company):
            raise CompanyDeletionError('delete_paid_subscription', 409)

        if normalize_company_name(confirm_name) != normalize_company_name(company.name):
            raise CompanyDeletionError('delete_name_mismatch', 400)

        user_ids = list(
            company.users.values_list('id', flat=True)
        )
        files = _collect_media_files(company)

        # Отзываем refresh-токены, пока пользователи ещё существуют.
        _delete_refresh_tokens(company)

        # Платформенный след: company=None обязателен, иначе CASCADE удалит
        # запись вместе с компанией. Бизнес-данные сюда не попадают.
        write_audit_log(
            action=AuditLog.Action.DELETE,
            actor=actor,
            target=company,
            request=request,
            company=None,
            as_platform=True,
            metadata={
                'company_id': company.pk,
                'company_name': company.name,
            },
        )

        company.delete()

        # Только после успешного коммита: при откате файлы и сокеты не трогаем.
        transaction.on_commit(lambda: _after_commit(files, user_ids))
