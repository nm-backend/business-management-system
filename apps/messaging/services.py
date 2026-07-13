"""
Messaging services - создание системных уведомлений.

Уведомления привязываются к компании получателя, а notify_staff уведомляет
владельца и администраторов ТОЛЬКО той компании, к которой относится событие
(иначе была бы утечка между компаниями).
"""
from .models import Notification


def notify(users, notification_type, title, message, order=None, task=None):
    """Создаёт уведомление каждому пользователю из users (одному или списку)."""
    if not users:
        return []
    if not hasattr(users, '__iter__'):
        users = [users]
    notifications = [
        Notification(
            company_id=user.company_id,
            user=user,
            type=notification_type,
            title=title,
            message=message,
            related_order=order,
            related_task=task,
        )
        for user in users
    ]
    return Notification.objects.bulk_create(notifications)


def notify_staff(company, notification_type, title, message, order=None, task=None):
    """Уведомляет владельца и администраторов указанной компании."""
    from apps.accounts.models import User
    if company is None:
        return []
    company_id = getattr(company, 'id', company)
    staff = User.objects.filter(
        role__in=('owner', 'admin'), is_active=True, company_id=company_id,
    )
    return notify(list(staff), notification_type, title, message, order=order, task=task)
