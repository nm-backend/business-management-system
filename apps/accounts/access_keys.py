"""
Сервис Access Key — выпуск, проверка и активация кодов-приглашений сотрудников.

Публичной регистрации нет: аккаунт активируется вводом Access Key. Здесь —
вся бизнес-логика, чтобы и API, и админка, и тесты использовали один путь.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import AccessKey, User


@transaction.atomic
def issue_access_key(*, user, created_by=None, expires_in_days=None):
    """
    Выпускает новый Access Key для сотрудника.

    Перевыпуск: прежние активные ключи этого сотрудника отзываются (REVOKED),
    поэтому одновременно действует не более одного ключа.
    """
    if user.is_superadmin or user.company_id is None:
        raise ValueError('Access keys can be issued only to company employees.')

    # ГОНКА (воспроизведена: 16 потоков -> до 3 активных ключей одновременно).
    # Без блокировки два процесса успевали отозвать «всё активное» (каждый видел
    # пустой набор) и затем оба вставляли новый ключ. Блокируем строку сотрудника:
    # параллельные выдачи выстраиваются в очередь, активным остаётся ровно один ключ.
    User.objects.select_for_update().filter(pk=user.pk).first()

    AccessKey.objects.filter(
        user=user, status=AccessKey.Status.ACTIVE,
    ).update(status=AccessKey.Status.REVOKED, updated_at=timezone.now())

    expires_at = None
    if expires_in_days:
        expires_at = timezone.now() + timedelta(days=int(expires_in_days))

    return AccessKey.objects.create(
        company_id=user.company_id,
        user=user,
        created_by=created_by,
        expires_at=expires_at,
    )


def _lookup(code):
    normalized = (code or '').strip().upper()
    return AccessKey.objects.filter(key=normalized).select_related('user', 'company').first()


def verify_access_key(code):
    """Возвращает ключ, если он пригоден к активации, иначе None."""
    key = _lookup(code)
    if key is None or not key.is_redeemable or not key.company.is_active:
        return None
    return key


@transaction.atomic
def redeem_access_key(*, code, new_password):
    """
    Активирует аккаунт сотрудника по коду.

    Возвращает (user, None) при успехе или (None, reason) при ошибке
    (reason: 'invalid' | 'company_inactive').
    """
    normalized = (code or '').strip().upper()
    key = (
        AccessKey.objects.select_for_update()
        .filter(key=normalized)
        .select_related('user', 'company')
        .first()
    )
    if key is None or not key.is_redeemable:
        return None, 'invalid'
    if not key.company.is_active:
        return None, 'company_inactive'

    user = key.user
    user.set_password(new_password)
    user.is_active = True
    if user.status != User.Status.ACTIVE:
        user.status = User.Status.ACTIVE
    user.save()

    key.status = AccessKey.Status.USED
    key.used_at = timezone.now()
    key.save(update_fields=['status', 'used_at', 'updated_at'])
    return user, None


def revoke_access_key(key):
    """Отзывает ключ (сделать недействительным немедленно)."""
    key.status = AccessKey.Status.REVOKED
    key.save(update_fields=['status', 'updated_at'])
    return key
