"""
Push notification service for VAPID Web Push.

Позволяет отправлять push-уведомления всем подписанным клиентам
пользователя. Использует pywebpush для шифрования и отправки.
"""
import json
import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)


def _get_vapid_keys():
    """
    Возвращает VAPID ключи из настроек или переменных окружения.

    Ключи генерируются командой:
      python manage.py generate_vapid_keys

    И должны быть установлены в переменные окружения:
      VAPID_PUBLIC_KEY
      VAPID_PRIVATE_KEY
    """
    public_key = os.environ.get('VAPID_PUBLIC_KEY') or getattr(settings, 'VAPID_PUBLIC_KEY', '')
    private_key = os.environ.get('VAPID_PRIVATE_KEY') or getattr(settings, 'VAPID_PRIVATE_KEY', '')
    return public_key, private_key


def send_push_notification(subscription, title, body, data=None):
    """
    Отправляет push-уведомление на одну подписку.

    Args:
        subscription: PushSubscription instance
        title: str - заголовок уведомления
        body: str - текст уведомления
        data: dict - дополнительные данные (url и т.д.)

    Returns:
        bool - True если успешно, False если подписка невалидна
    """
    public_key, private_key = _get_vapid_keys()
    if not public_key or not private_key:
        logger.warning('VAPID keys not configured. Run: python manage.py generate_vapid_keys')
        return False

    try:
        from pywebpush import webpush, WebPushException

        payload = json.dumps({
            'title': title,
            'body': body,
            'data': data or {},
            'tag': 'skladpro_notification',
        })

        response = webpush(
            subscription_info={
                'endpoint': subscription.endpoint,
                'keys': {
                    'p256dh': subscription.p256dh_key,
                    'auth': subscription.auth_key,
                },
            },
            data=payload,
            vapid_private_key=private_key,
            vapid_claims={
                'sub': 'mailto:admin@skladpro.nod',
            },
        )
        return True

    except WebPushException as e:
        if e.response and e.response.status_code in (410, 404):
            # Подписка истекла или удалена — деактивируем
            subscription.is_active = False
            subscription.save(update_fields=['is_active'])
            logger.info(f'Push subscription {subscription.id} deactivated (410/404)')
        else:
            logger.warning(f'Push send failed for {subscription.id}: {e}')
        return False
    except Exception as e:
        logger.error(f'Push error for {subscription.id}: {e}')
        return False


def send_push_to_user(user, title, body, data=None):
    """
    Отправляет push-уведомление всем активным подпискам пользователя.

    Args:
        user: User instance
        title: str - заголовок
        body: str - текст
        data: dict - доп. данные (url и т.д.)
    """
    from .models import PushSubscription

    subscriptions = PushSubscription.objects.filter(
        user=user,
        is_active=True,
    )
    if not subscriptions.exists():
        return

    for sub in subscriptions:
        send_push_notification(sub, title, body, data)


def send_push_to_company(company_id, title, body, data=None, exclude_user=None):
    """
    Отправляет push-уведомление всем пользователям компании.

    Args:
        company_id: int
        title: str
        body: str
        data: dict
        exclude_user: User instance - не отправлять этому пользователю
    """
    from .models import PushSubscription

    qs = PushSubscription.objects.filter(
        company_id=company_id,
        is_active=True,
    )
    if exclude_user:
        qs = qs.exclude(user=exclude_user)

    for sub in qs:
        send_push_notification(sub, title, body, data)
