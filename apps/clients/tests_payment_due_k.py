"""
Срок оплаты и бакеты просрочки (макет «Қарз назорати»).

В макете долги разложены по возрасту: «Муддати ўтган қарзлар» с подписями
«15 кундан ошган / 10 кундан ошган / 7 кундан ошган» и отдельно «Муддати бор».
Раньше просрочка считалась по сроку ИЗГОТОВЛЕНИЯ: заказ, сданный вовремя с
отсрочкой платежа на месяц, немедленно попадал в просроченные.

Обратная совместимость обязательна: заказ без payment_due_date ведёт себя
ровно как раньше.
"""
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.messaging.models import Notification
from apps.orders.models import Order

SUMMARY = '/api/v1/clients/clients/debt_summary/'


class PaymentDueDateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='DueCo')
        cls.owner = User.objects.create_user(
            username='due_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='due_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )
        cls.client_obj = Client.objects.create(company=cls.company, name='Акбаров')

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _order(self, *, days_ago_due=None, days_ahead_due=None, paid='0', total='1000.00',
               deadline_days=-30):
        due = None
        if days_ago_due is not None:
            due = timezone.now() - timezone.timedelta(days=days_ago_due)
        elif days_ahead_due is not None:
            due = timezone.now() + timezone.timedelta(days=days_ahead_due)
        return Order.objects.create(
            company=self.company, client=self.client_obj, custom_product_name='Столешница',
            quantity=Decimal('1'), unit='sht', total_amount=Decimal(total),
            paid_amount=Decimal(paid),
            deadline=timezone.now() + timezone.timedelta(days=deadline_days),
            payment_due_date=due,
        )

    # ── Модель ──────────────────────────────────────────────────────────────

    def test_overdue_days_counted_from_payment_due_date(self):
        order = self._order(days_ago_due=20)
        self.assertEqual(order.payment_overdue_days, 20)

    def test_future_payment_due_is_not_overdue(self):
        """Срок изготовления прошёл, но отсрочка платежа ещё действует."""
        order = self._order(days_ahead_due=10)
        self.assertEqual(order.payment_overdue_days, 0)

    def test_falls_back_to_deadline(self):
        """Без срока оплаты поведение прежнее — по сроку изготовления."""
        order = self._order(deadline_days=-12)
        self.assertEqual(order.payment_overdue_days, 12)

    def test_paid_order_never_overdue(self):
        order = self._order(days_ago_due=30, paid='1000.00')
        self.assertEqual(order.payment_overdue_days, 0)

    def test_cancelled_and_archived_not_overdue(self):
        order = self._order(days_ago_due=30)
        order.status = Order.Status.CANCELLED
        self.assertEqual(order.payment_overdue_days, 0)

        order.status = Order.Status.NEW
        order.is_archived = True
        self.assertEqual(order.payment_overdue_days, 0)

    # ── Сводка долгов ───────────────────────────────────────────────────────

    def test_buckets_split_by_age(self):
        self._order(days_ago_due=3, total='100.00')     # 1–7
        self._order(days_ago_due=10, total='200.00')    # 8–14
        self._order(days_ago_due=40, total='300.00')    # 15+
        self._order(days_ahead_due=5, total='400.00')   # срок не вышел

        data = self.api.get(SUMMARY).data
        buckets = data['buckets']
        self.assertEqual(buckets['overdue_1_7']['count'], 1)
        self.assertEqual(buckets['overdue_8_14']['count'], 1)
        self.assertEqual(buckets['overdue_15_plus']['count'], 1)
        self.assertEqual(buckets['not_due']['count'], 1)
        self.assertEqual(Decimal(str(data['overdue_total'])), Decimal('600.00'))

    def test_bucket_rows_carry_days_and_debt(self):
        self._order(days_ago_due=21, total='500.00', paid='200.00')
        rows = self.api.get(SUMMARY).data['buckets']['overdue_15_plus']['orders']
        self.assertEqual(rows[0]['days_overdue'], 21)
        self.assertEqual(Decimal(str(rows[0]['debt'])), Decimal('300.00'))
        self.assertEqual(rows[0]['client_name'], 'Акбаров')

    def test_paid_orders_absent_from_buckets(self):
        self._order(days_ago_due=30, total='100.00', paid='100.00')
        buckets = self.api.get(SUMMARY).data['buckets']
        self.assertEqual(sum(b['count'] for b in buckets.values()), 0)

    def test_admin_still_denied(self):
        """Сводка долгов остаётся владельческой — права не ослабли."""
        api = APIClient()
        api.force_authenticate(self.admin)
        self.assertEqual(api.get(SUMMARY).status_code, 403)

    def test_other_company_orders_not_counted(self):
        other = Company.objects.create(name='OtherDueCo')
        other_client = Client.objects.create(company=other, name='Чужой')
        Order.objects.create(
            company=other, client=other_client, custom_product_name='Чужой',
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('9999.00'),
            deadline=timezone.now() - timezone.timedelta(days=60),
        )
        data = self.api.get(SUMMARY).data
        self.assertEqual(Decimal(str(data['overdue_total'])), Decimal('0'))

    # ── Уведомления ─────────────────────────────────────────────────────────

    def test_notification_uses_payment_due_date(self):
        self._order(days_ahead_due=10)   # платить ещё рано
        call_command('notify_overdue_debts')
        self.assertEqual(Notification.objects.filter(
            type=Notification.NotificationType.OVERDUE_DEBT,
        ).count(), 0)

        self._order(days_ago_due=5)
        call_command('notify_overdue_debts')
        self.assertGreater(Notification.objects.filter(
            type=Notification.NotificationType.OVERDUE_DEBT,
        ).count(), 0)

    def test_notification_still_has_no_amounts(self):
        """Уведомление уходит и администратору — сумм в нём быть не должно."""
        self._order(days_ago_due=5, total='123456.78')
        call_command('notify_overdue_debts')
        for notification in Notification.objects.filter(
            type=Notification.NotificationType.OVERDUE_DEBT,
        ):
            self.assertNotIn('123456', notification.message)
