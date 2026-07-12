"""
Messaging services - создание системных уведомлений.
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


def notify_staff(notification_type, title, message, order=None, task=None):
    """Уведомляет владельца и всех активных администраторов."""
    from apps.accounts.models import User
    staff = User.objects.filter(role__in=('owner', 'admin'), is_active=True)
    return notify(list(staff), notification_type, title, message, order=order, task=task)
