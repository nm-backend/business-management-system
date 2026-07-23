"""
Уведомление о просроченном долге OVERDUE_DEBT (фича ТЗ).

Пробел (подтверждён): тип OVERDUE_DEBT объявлен, но нигде не создавался и
механизма (cron/команды) не было. Проверяем команду notify_overdue_debts:
уведомляет только по реально просроченным неоплаченным заказам, идемпотентна.
"""
import datetime
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.messaging.models import Notification
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct


class OverdueDebtCommandTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='ODbt', is_active=True)
        self.owner = User.objects.create_user(username='od_owner', password='p',
                                               role=User.Role.OWNER, company=self.company)
        self.admin = User.objects.create_user(username='od_admin', password='p',
                                               role=User.Role.ADMIN, company=self.company)
        self.worker = User.objects.create_user(username='od_worker', password='p',
                                                role=User.Role.WORKER, company=self.company)
        self.cli = Client.objects.create(company=self.company, name='Debtor')
        self.product = FinishedProduct.objects.create(company=self.company, name='P', quantity=Decimal('10'))
        self.past = timezone.now() - datetime.timedelta(days=5)
        self.future = timezone.now() + datetime.timedelta(days=5)

    def _order(self, deadline, total, paid, status=Order.Status.DELIVERED):
        return Order.objects.create(
            company=self.company, client=self.cli, product=self.product,
            quantity=Decimal('1'), unit='dona', deadline=deadline,
            total_amount=Decimal(total), paid_amount=Decimal(paid), status=status)

    def _run(self, *args):
        out = StringIO()
        call_command('notify_overdue_debts', *args, stdout=out)
        return out.getvalue()

    def test_notifies_only_overdue_unpaid_and_is_idempotent(self):
        overdue = self._order(self.past, '1000', '0')          # должен уведомить
        self._order(self.future, '1000', '0')                  # срок не прошёл
        self._order(self.past, '1000', '1000')                 # полностью оплачен
        self._order(self.past, '1000', '0', Order.Status.CANCELLED)  # отменён

        self._run()
        notes = Notification.objects.filter(type=Notification.NotificationType.OVERDUE_DEBT)
        # Уведомлены owner + admin (не worker), ровно по просроченному заказу.
        self.assertEqual(notes.count(), 2)
        self.assertEqual(set(notes.values_list('user__username', flat=True)), {'od_owner', 'od_admin'})
        self.assertTrue(all(n.related_order_id == overdue.id for n in notes))

        # Идемпотентность: повторный запуск не плодит новые уведомления.
        self._run()
        self.assertEqual(
            Notification.objects.filter(type=Notification.NotificationType.OVERDUE_DEBT).count(), 2)

    def test_dry_run_creates_nothing(self):
        self._order(self.past, '1000', '0')
        out = self._run('--dry-run')
        self.assertIn('dry-run', out)
        self.assertEqual(
            Notification.objects.filter(type=Notification.NotificationType.OVERDUE_DEBT).count(), 0)
