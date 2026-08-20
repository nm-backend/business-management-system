import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def check_expired_subscriptions():
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
    from .services import send_expiry_reminders

    sent = send_expiry_reminders()
    logger.info('notify_expiring_subscriptions: reminders=%s', sent)
    return {'reminders': sent}
