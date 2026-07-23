"""
Уведомление о просроченном долге (тип OVERDUE_DEBT).

Тип уведомления был объявлен в модели, но нигде не создавался. Эта команда
находит заказы с просроченным неоплаченным долгом и уведомляет владельца и
администраторов компании. Идемпотентна: на один заказ создаётся не более одного
OVERDUE_DEBT-уведомления (повторные запуски не спамят).

Запускать по расписанию (cron / Render Cron Job), например раз в сутки:
    python manage.py notify_overdue_debts
"""
from django.core.management.base import BaseCommand
from django.db.models import F
from django.utils import timezone

from apps.messaging.models import Notification
from apps.messaging.services import notify_staff
from apps.orders.models import Order


class Command(BaseCommand):
    help = ('Создаёт уведомления OVERDUE_DEBT по заказам с просроченным '
            'неоплаченным долгом (идемпотентно). Запускать по расписанию.')

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Только показать количество, ничего не создавать.')

    def handle(self, *args, **options):
        now = timezone.now()
        # Просроченный долг: срок прошёл, оплачено меньше суммы, заказ не отменён,
        # компания активна. paid_amount < total_amount гарантирует реальный долг.
        overdue = list(
            Order.objects.filter(
                company__is_active=True,
                deadline__lt=now,
                paid_amount__lt=F('total_amount'),
            )
            .exclude(status=Order.Status.CANCELLED)
            .select_related('client')
        )
        overdue_ids = [o.id for o in overdue]
        already = set(
            Notification.objects.filter(
                type=Notification.NotificationType.OVERDUE_DEBT,
                related_order_id__in=overdue_ids,
            ).values_list('related_order_id', flat=True)
        )
        to_notify = [o for o in overdue if o.id not in already]

        created = 0
        if not options['dry_run']:
            for order in to_notify:
                # Без суммы: тип уже сигнализирует о долге, а суммы — только owner.
                recipients = notify_staff(
                    order.company_id,
                    Notification.NotificationType.OVERDUE_DEBT,
                    'Қарз муддати ўтди',
                    f'Буюртма #{order.id}, мижоз: {order.client.name}',
                    order=order,
                )
                created += len(recipients)

        suffix = ' [dry-run]' if options['dry_run'] else ''
        self.stdout.write(
            f'overdue={len(overdue_ids)} new={len(to_notify)} '
            f'notifications_created={created}{suffix}'
        )
