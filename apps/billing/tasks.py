"""
Celery-задачи жизненного цикла подписок.

Расписание создаётся data-migration'ом в django_celery_beat (DatabaseScheduler):
  billing-check-expired     — каждые 60 минут: поиск истекающих и заморозка;
  billing-notify-expiring   — раз в день: напоминания об окончании.

Обе задачи идемпотентны: повторный запуск не создаёт дубликатов событий,
уведомлений и не «перезамораживает» уже замороженные компании.
"""
import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def check_expired_subscriptions():
    """
    Автоматическое определение истечения + заморозка компании.

    Берёт подписки со статусом ACTIVE и истёкшим сроком, для каждой вызывает
    freeze_subscription() под SELECT ... FOR UPDATE (внутри повторно проверяет
    срок — гонка с продлением безопасна). Пропускает уже замороженные.
    """
    from .models import Subscription
    from .services import freeze_subscription

    now = timezone.now()
    qs = Subscription.objects.filter(
        status=Subscription.Status.ACTIVE,
        expires_at__lt=now,
    )
    frozen = skipped = 0
    for sub in qs.iterator():
        try:
            if freeze_subscription(sub):
                frozen += 1
            else:
                skipped += 1
        except Exception:
            logger.exception('Freeze failed for subscription %s', sub.pk)
    logger.info('check_expired_subscriptions: frozen=%s skipped=%s', frozen, skipped)
    return {'frozen': frozen, 'skipped': skipped}


@shared_task
def notify_expiring_subscriptions():
    """
    Напоминания об окончании: компании, чей срок подходит к концу.

    Рассылка не чаще раза в день на компанию (см. send_expiry_reminders).
    """
    from .services import send_expiry_reminders

    sent = send_expiry_reminders()
    logger.info('notify_expiring_subscriptions: reminders=%s', sent)
    return {'reminders': sent}
