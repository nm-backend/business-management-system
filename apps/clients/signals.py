"""
Signals for clients app.

Автоматически архивирует клиента, когда все заказы завершены
и оплачены. Сигнал подключается через @receiver декоратор
(он поддерживает строковый sender, в отличие от connect()).
"""
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender='orders.Order')
def auto_archive_client_on_order_update(sender, instance, **kwargs):
    """
    Автоматически архивирует клиента после обновления заказа.

    Когда заказ обновляется (статус, оплата), проверяется,
    можно ли архивировать клиента. Если все заказы клиента
    завершены и оплачены — клиент архивируется.
    """
    try:
        client = instance.client
        if client and not client.is_archived:
            client.auto_archive()
    except Exception as e:
        logger.error(f"Auto-archive check failed for order #{instance.id}: {e}")
