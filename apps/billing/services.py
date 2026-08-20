"""
Бизнес-логика жизненного цикла подписки.

Все переходы состояния выполняются под SELECT ... FOR UPDATE на строке
Subscription: параллельные renew/freeze (owner + Celery + супер-админ)
иначе читали бы один статус и писали поверх друг друга (потерянное
обновление / двойное продление).

Каждое изменение фиксируется в ТРЁХ местах:
  SubscriptionEvent  — история подписки (owner видит через API);
  AuditLog           — журнал действий (неизменяемый);
  Notification       — уведомление владельцу/персоналу (+ Web Push).
"""
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.audit.services import write_audit_log
from apps.messaging.models import Notification
from apps.messaging.services import notify, notify_staff

from .models import Invoice, Subscription, SubscriptionEvent
from .payments import get_provider

# audit-действие для каждого типа события продления.
_AUDIT_ACTION = {
    SubscriptionEvent.Action.RENEWED: AuditLog.Action.SUBSCRIPTION_RENEWED,
    SubscriptionEvent.Action.EXTENDED: AuditLog.Action.SUBSCRIPTION_EXTENDED,
    SubscriptionEvent.Action.ACTIVATED: AuditLog.Action.SUBSCRIPTION_ACTIVATED,
}


def _sync_company_fields(sub):
    """Sync billing subscription status to Company model fields."""
    from apps.companies.models import Company

    _STATUS_MAP = {
        Subscription.Status.ACTIVE: Company.SubscriptionStatus.ACTIVE,
        Subscription.Status.EXPIRED: Company.SubscriptionStatus.EXPIRED,
        Subscription.Status.FROZEN: Company.SubscriptionStatus.FROZEN,
    }
    company_status = _STATUS_MAP.get(sub.status, Company.SubscriptionStatus.ACTIVE)
    Company.objects.filter(pk=sub.company_id).update(
        subscription_status=company_status,
        subscription_start=sub.started_at,
        subscription_end=sub.expires_at,
        is_trial=False if sub.status != Subscription.Status.ACTIVE or sub.last_renewed_at else True,
    )
    sub.company.subscription_status = company_status
    sub.company.subscription_start = sub.started_at
    sub.company.subscription_end = sub.expires_at


def plan_price(plan):
    """Стоимость тарифа из каталога настроек (0 — пока оплата не подключена)."""
    for item in getattr(settings, 'SUBSCRIPTION_PLANS', []):
        if item.get('key') == plan:
            return item.get('price', 0)
    return 0


def _snapshot(sub):
    """(status, expires_at) до изменения — для истории и audit."""
    return sub.status, sub.expires_at


def _record_event(sub, action, old_status='', old_expires=None, *, actor=None, note=''):
    SubscriptionEvent.objects.create(
        subscription=sub,
        company=sub.company,
        action=action,
        actor=actor if (actor is not None and getattr(actor, 'is_authenticated', False)) else None,
        actor_role=getattr(actor, 'role', '') if (actor is not None and getattr(actor, 'is_authenticated', False)) else 'system',
        from_status=old_status,
        to_status=sub.status,
        old_expires_at=old_expires,
        new_expires_at=sub.expires_at,
        note=note,
    )


def _write_audit(sub, action, *, actor=None, request=None, changes=None, metadata=None):
    """Пишет запись в журнал аудита.

    Действия пользователей идут через write_audit_log (компания берётся из
    actor). Системные события (Celery) — напрямую с явной привязкой компании:
    иначе запись с company=None выпадает из всех фильтров админки по компании.
    """
    if actor is not None and getattr(actor, 'is_authenticated', False):
        return write_audit_log(
            action=action, actor=actor, target=sub.company,
            changes=changes, metadata=metadata, request=request,
        )
    return AuditLog.objects.create(
        company=sub.company,
        actor=None,
        actor_username='system',
        actor_role='',
        action=action,
        object_type='billing.Subscription',
        object_id=str(sub.pk),
        object_repr=f'{sub.company.name} · {sub.get_plan_display()}',
        changes=changes or {},
        metadata=metadata or {},
    )


def _notify_owner(sub, notification_type, title, message):
    """Уведомление владельцу компании (+ Web Push, если подписан)."""
    owner = User.objects.filter(
        company_id=sub.company_id, role=User.Role.OWNER, is_active=True,
    ).first()
    if owner is None:
        return
    notify(owner, notification_type, title, message)
    try:
        from apps.accounts.push_service import send_push_to_user
        send_push_to_user(owner, title, message, data={'url': '#/settings'})
    except Exception:
        pass  # push не должен ронять продление/заморозку


def create_subscription(company, *, days=None, actor=None, request=None):
    """Создаёт подписку на 30 дней при создании компании (сигнал/бэкфилл)."""
    days = days or settings.SUBSCRIPTION_DAYS
    now = timezone.now()
    try:
        with transaction.atomic():
            sub, created = Subscription.objects.get_or_create(
                company=company,
                defaults={
                    'status': Subscription.Status.ACTIVE,
                    'started_at': now,
                    'expires_at': now + timedelta(days=days),
                },
            )
    except IntegrityError:
        sub = Subscription.objects.get(company=company)
        created = False
    if created:
        _record_event(sub, SubscriptionEvent.Action.CREATED, actor=actor)
        _write_audit(
            sub, AuditLog.Action.SUBSCRIPTION_ACTIVATED, actor=actor, request=request,
            changes={'expires_at': {'new': sub.expires_at.isoformat()}},
            metadata={'source': 'creation'},
        )
    return sub


def _extend(sub, days, action, *, actor=None, request=None, note=''):
    """
    Продлевает период от max(now, expires_at) — оставшиеся дни не сгорают.

    Единственная точка перехода в ACTIVE с новым сроком: используется
    продлением по счёту (renew), продлением супер-админом (extend) и
    активацией (activate).
    """
    now = timezone.now()
    old_status, old_expires = _snapshot(sub)
    sub.status = Subscription.Status.ACTIVE
    sub.started_at = now
    sub.expires_at = max(now, sub.expires_at) + timedelta(days=days)
    sub.last_renewed_at = now
    sub.frozen_at = None
    sub.save(update_fields=[
        'plan', 'status', 'started_at', 'expires_at',
        'last_renewed_at', 'frozen_at', 'updated_at',
    ])
    _record_event(sub, action, old_status, old_expires, actor=actor, note=note)
    _write_audit(
        sub, _AUDIT_ACTION[action], actor=actor, request=request,
        changes={
            'status': {'old': old_status, 'new': sub.status},
            'expires_at': {
                'old': old_expires.isoformat() if old_expires else None,
                'new': sub.expires_at.isoformat(),
            },
        },
    )
    _sync_company_fields(sub)
    _notify_owner(
        sub, Notification.NotificationType.SUBSCRIPTION_RENEWED,
        'Подписка продлена',
        f'Подписка действует до {sub.expires_at:%d.%m.%Y}.',
    )
    return sub


def renew_subscription(sub, *, days=None, actor=None, request=None, note=''):
    """Продление по оплаченному счёту: новый период +30 дней (или остаток + 30)."""
    days = days or settings.SUBSCRIPTION_DAYS
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().get(pk=sub.pk)
        return _extend(sub, days, SubscriptionEvent.Action.RENEWED,
                       actor=actor, request=request, note=note)


def extend_subscription(sub, *, days, actor=None, request=None, note=''):
    """Продление супер-админом: от max(now, expires_at) + days."""
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().get(pk=sub.pk)
        return _extend(sub, days, SubscriptionEvent.Action.EXTENDED,
                       actor=actor, request=request, note=note)


def activate_subscription(sub, *, days=None, actor=None, request=None, note=''):
    """Активация супер-админом: свежий период ровно days от сейчас."""
    days = days or settings.SUBSCRIPTION_DAYS
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().get(pk=sub.pk)
        return _extend(sub, days, SubscriptionEvent.Action.ACTIVATED,
                       actor=actor, request=request, note=note)


def quick_renew_subscription(sub, *, actor=None, request=None, note=''):
    """
    Быстрое продление одним кликом из админки (+30 дней).

    Решение «активировать свежий период / продлить от текущего срока»
    принимается ПОД блокировкой строки: между чтением статуса и записью
    не может вклиниться Celery-заморозка. Раньше выбор делался в view по
    is_blocked вне select_for_update — гонка с check_expired_subscriptions
    могла привести к EXTENDED-событию вместо ACTIVATED (безобидно по сроку,
    но сбивало историю). Возвращает (sub, action).
    """
    days = settings.SUBSCRIPTION_DAYS
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().get(pk=sub.pk)
        if sub.is_blocked:
            _extend(sub, days, SubscriptionEvent.Action.ACTIVATED,
                    actor=actor, request=request, note=note)
            return sub, SubscriptionEvent.Action.ACTIVATED
        _extend(sub, days, SubscriptionEvent.Action.EXTENDED,
                actor=actor, request=request, note=note)
        return sub, SubscriptionEvent.Action.EXTENDED


def freeze_subscription(sub, *, actor=None, request=None):
    """
    Заморозка: active → expired → frozen (два события, одна транзакция).

    Идемпотентна и безопасна в гонке с продлением: под блокировкой ещё раз
    проверяем expires_at — если подписку уже успели продлить, не морозим.
    Возвращает True, если компания реально заморожена.
    """
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().get(pk=sub.pk)
        if sub.status != Subscription.Status.ACTIVE:
            return False  # уже заморожена/истекла
        if timezone.now() < sub.expires_at:
            return False  # продлили до прогона задачи — пропускаем
        old_status, old_expires = _snapshot(sub)

        # Шаг 1: срок истёк.
        sub.status = Subscription.Status.EXPIRED
        sub.save(update_fields=['status', 'updated_at'])
        _record_event(sub, SubscriptionEvent.Action.EXPIRED, old_status, old_expires,
                      actor=actor)
        _write_audit(
            sub, AuditLog.Action.SUBSCRIPTION_EXPIRED, actor=actor, request=request,
            changes={'status': {'old': old_status, 'new': sub.status}},
        )

        # Шаг 2: заморозка бизнес-функций (вход остаётся доступным — whitelist).
        sub.status = Subscription.Status.FROZEN
        sub.frozen_at = timezone.now()
        sub.save(update_fields=['status', 'frozen_at', 'updated_at'])
        _record_event(sub, SubscriptionEvent.Action.FROZEN,
                      Subscription.Status.EXPIRED, old_expires, actor=actor)
        _write_audit(
            sub, AuditLog.Action.SUBSCRIPTION_FROZEN, actor=actor, request=request,
            changes={'status': {'old': Subscription.Status.EXPIRED, 'new': sub.status}},
        )
        _sync_company_fields(sub)
        notify_staff(
            sub.company, Notification.NotificationType.SUBSCRIPTION_FROZEN,
            'Подписка истекла',
            'Срок подписки компании истёк — бизнес-функции приостановлены '
            'до продления. Вход в систему доступен.',
        )
    return True


def unfreeze_subscription(sub, *, actor=None, request=None, note=''):
    """
    Ручная разморозка супер-админом. Только если срок ещё не истёк —
    иначе сначала продлите (activate/extend), иначе компания вернётся
    в работу с просроченной подпиской.
    """
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().get(pk=sub.pk)
        if timezone.now() >= sub.expires_at:
            raise ValidationError(
                {'detail': 'Срок подписки истёк. Сначала продлите её (extend или activate).'}
            )
        if sub.status != Subscription.Status.FROZEN:
            return sub
        old_status, old_expires = _snapshot(sub)
        sub.status = Subscription.Status.ACTIVE
        sub.frozen_at = None
        sub.save(update_fields=['status', 'frozen_at', 'updated_at'])
        _record_event(sub, SubscriptionEvent.Action.UNFROZEN, old_status, old_expires,
                      actor=actor, note=note)
        _write_audit(
            sub, AuditLog.Action.SUBSCRIPTION_UNFROZEN, actor=actor, request=request,
            changes={'status': {'old': old_status, 'new': sub.status}},
        )
        _sync_company_fields(sub)
        _notify_owner(
            sub, Notification.NotificationType.SUBSCRIPTION_RENEWED,
            'Подписка возобновлена',
            f'Компания снова в работе. Подписка действует до {sub.expires_at:%d.%m.%Y}.',
        )
    return sub


def create_invoice(sub, *, plan=None, actor, request=None):
    """
    Создаёт счёт на продление через payment adapter.

    Повторный запрос при уже висящем pending-счёте возвращает ЕГО (без
    дубликатов) — параллельные клики по «Продлить» не плодят счета.
    """
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().get(pk=sub.pk)
        pending = Invoice.objects.filter(
            subscription=sub, status=Invoice.Status.PENDING,
        ).first()
        if pending is not None:
            return pending, False
        plan = plan or sub.plan
        if plan not in Subscription.Plan.values:
            raise ValidationError({'plan': 'Неизвестный тариф.'})
        invoice = Invoice.objects.create(
            company=sub.company,
            subscription=sub,
            amount=plan_price(plan),
            currency=getattr(settings, 'SUBSCRIPTION_CURRENCY', 'UZS'),
            provider=get_provider().key,
            metadata={'plan': plan},
            created_by=actor,
        )
    # Вне транзакции: провайдер может ходить во внешний API.
    get_provider(invoice.provider).create_payment(invoice, request=request)
    return invoice, True


def confirm_invoice_paid(invoice, *, actor=None, request=None):
    """
    Подтверждение оплаты счёта (супер-админ / вебхук провайдера).

    Счёт → paid, подписка → renew (активная, срок +30 дней), компания
    автоматически возвращается в работу. Всё в одной транзакции под
    блокировкой счёта и подписки.
    """
    with transaction.atomic():
        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.status == Invoice.Status.PAID:
            return invoice  # идемпотентно: повторный confirm ничего не ломает
        if invoice.status != Invoice.Status.PENDING:
            raise ValidationError(
                {'detail': f'Счёт в статусе «{invoice.get_status_display()}» — оплатить нельзя.'}
            )
        sub = Subscription.objects.select_for_update().get(pk=invoice.subscription_id)
        old_status, old_expires = _snapshot(sub)

        invoice.status = Invoice.Status.PAID
        invoice.paid_at = timezone.now()
        invoice.save(update_fields=['status', 'paid_at', 'updated_at'])

        metadata = invoice.metadata if isinstance(invoice.metadata, dict) else {}
        plan = metadata.get('plan')
        # plan_changed — только при реальной смене тарифа: продление на тот же
        # тариф не должно писать «Тариф изменён» в историю (воспроизведено:
        # счёт на free записывал plan_changed, хотя тариф не менялся).
        if plan in Subscription.Plan.values and plan != sub.plan:
            sub.plan = plan
            _record_event(sub, SubscriptionEvent.Action.PLAN_CHANGED, old_status, old_expires,
                          actor=actor, note=f'Тариф → {plan} (счёт #{invoice.pk})')

        _extend(sub, settings.SUBSCRIPTION_DAYS, SubscriptionEvent.Action.RENEWED,
                actor=actor, request=request, note=f'Оплата счёта #{invoice.pk}')
        _record_event(sub, SubscriptionEvent.Action.INVOICE_PAID, old_status, old_expires,
                      actor=actor, note=f'Счёт #{invoice.pk} оплачен')
        _write_audit(
            sub, AuditLog.Action.INVOICE_PAID, actor=actor, request=request,
            metadata={'invoice_id': invoice.pk, 'amount': str(invoice.amount)},
        )
    return invoice


def send_expiry_reminders():
    """
    Рассылает предупреждения об окончании подписки (раз в день на компанию).

    Гонкозащита без блокировки: атомарный условный UPDATE last_reminder_at
    выигрывает ровно один воркер; параллельный запуск задачи ничего не
    продублирует.
    """
    now = timezone.now()
    horizon = now + timedelta(days=settings.SUBSCRIPTION_GRACE_NOTIFY_DAYS)
    start_of_day = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)

    qs = Subscription.objects.filter(
        status=Subscription.Status.ACTIVE,
        expires_at__lte=horizon,
        expires_at__gt=now,
    )
    sent = 0
    for sub in qs.iterator():
        updated = Subscription.objects.filter(pk=sub.pk).filter(
            Q(last_reminder_at__isnull=True) | Q(last_reminder_at__lt=start_of_day),
        ).update(last_reminder_at=now)
        if not updated:
            continue
        days_left = max(1, sub.days_left)
        _notify_owner(
            sub, Notification.NotificationType.SUBSCRIPTION_EXPIRING,
            'Подписка скоро истечёт',
            f'До окончания подписки осталось {days_left} дн. Продлите, '
            'чтобы компания продолжила работу без перерыва.',
        )
        sent += 1
    return sent
