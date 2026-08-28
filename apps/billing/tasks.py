"""
Celery-задачи подписок (billing).

САМИ ЭТИ ЗАДАЧИ БОЛЬШЕ НЕ ПЛАНИРУЮТСЯ (см. billing/migrations/0004): жизненный
цикл ведётся контуром companies (apps.companies.tasks), который учитывает
льготный период (grace) и является единственным источником истины.

Функции оставлены как ТОНКИЕ ДЕЛЕГАТЫ на companies-задачи, чтобы любой прямой
вызов (ручной, тесты, пережитки расписания) был grace-aware и не мог перевести
компанию в состояние, противоречащее Company lifecycle.
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, name='apps.billing.tasks.check_expired_subscriptions')
def check_expired_subscriptions(self):
    """
    Делегат на companies-задачу автозаморозки (grace-aware).

    Прежняя реализация шла по billing.Subscription и замораживала подписку
    сразу после истечения срока, минуя льготный период (Company=GRACE,
    billing=FROZEN). Теперь переход active -> grace -> expired выполняет
    единая companies-задача, а billing.Subscription — лишь проекция.
    """
    from apps.companies.tasks import auto_freeze_expired_subscriptions

    processed = auto_freeze_expired_subscriptions.run()
    logger.info('check_expired_subscriptions: processed=%s (grace-aware)', processed)
    return {'frozen': processed, 'skipped': 0}


@shared_task(bind=True, name='apps.billing.tasks.notify_expiring_subscriptions')
def notify_expiring_subscriptions(self):
    """
    Напоминания об окончании (без изменения состояния подписки).

    Задача снята с расписания (billing/migrations/0004): предупреждения в
    проде рассылает companies-задача notify_subscription_expiry (7/1 день),
    чтобы не было двух систем уведомлений. Функция оставлена для прямых
    вызовов и тестов; она не меняет ни статус, ни срок подписки.
    """
    from .services import send_expiry_reminders

    sent = send_expiry_reminders()
    logger.info('notify_expiring_subscriptions: reminders=%s', sent)
    return {'reminders': sent}
