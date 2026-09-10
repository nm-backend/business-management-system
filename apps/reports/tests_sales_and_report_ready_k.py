"""
Экран «Продажи» (ТЗ: список главных экранов хозяина) и уведомление
«Отчёт готов» (REPORT_READY).

* /reports/analytics/sales/ — выданные клиенту заказы за период, ТОЛЬКО
  владелец (деньги); админу/работнику — 403.
* Квартальный отчёт владельца создаёт уведомление REPORT_READY, причём
  одно на пару год/квартал — повторные открытия не спамят ленту.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.messaging.models import Notification
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct

SALES = '/api/v1/reports/analytics/sales/'
QUARTERLY = '/api/v1/reports/analytics/quarterly/'


def _delivered(company, client, product, *, total, paid, days_ago=0):
    """Выданный заказ с фиксированными суммами и датой выдачи."""
    now = timezone.now()
    delivered_at = now - timedelta(days=days_ago)
    order = Order.objects.create(
        company=company, client=client, product=product,
        quantity=Decimal('1'), unit='sht',
        total_amount=Decimal(total), paid_amount=Decimal(paid),
        status=Order.Status.DELIVERED, delivered_at=delivered_at,
        cost_price=Decimal('0'),
    )
    # delivered_at проставляется save() автоматически; для теста периода
    # сдвигаем выданные «задним числом» только через days_ago при создании.
    return order


class SalesHistoryViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='SalesCo')
        cls.owner = User.objects.create_user(
            username='s_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='s_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='s_worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )
        cls.customer = Client.objects.create(company=cls.company, name='Акбар')
        cls.product = FinishedProduct.objects.create(
            company=cls.company, name='Столешница', unit='sht', quantity=Decimal('5'),
        )
        cls.today_sale = _delivered(cls.company, cls.customer, cls.product, total='1000', paid='1000')
        cls.old_sale = _delivered(cls.company, cls.customer, cls.product, total='500', paid='200', days_ago=40)

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def test_owner_sees_today_sales(self):
        response = self.api_as(self.owner).get(SALES, {'period': 'today'})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(Decimal(str(response.data['total_amount'])), Decimal('1000'))
        self.assertEqual(Decimal(str(response.data['paid'])), Decimal('1000'))
        self.assertEqual(Decimal(str(response.data['debt'])), Decimal('0'))
        self.assertEqual(response.data['orders'][0]['client_name'], 'Акбар')
        # id клиента в payload — на него ведёт глубокая ссылка из UI (#/orders?client=…).
        self.assertEqual(response.data['orders'][0]['client'], self.customer.pk)

    def test_period_filter_excludes_old_sales(self):
        """Свежая выдача входит в «неделю», выдача 40-дневной давности — нет."""
        response = self.api_as(self.owner).get(SALES, {'period': 'week'})
        ids = [row['id'] for row in response.data['orders']]
        self.assertIn(self.today_sale.id, ids)
        self.assertNotIn(self.old_sale.id, ids)

    def test_debt_is_sum_of_unpaid(self):
        response = self.api_as(self.owner).get(SALES, {'date_from': '2020-01-01', 'date_to': '2030-01-01'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)
        self.assertEqual(Decimal(str(response.data['total_amount'])), Decimal('1500'))
        self.assertEqual(Decimal(str(response.data['debt'])), Decimal('300'))

    def test_admin_denied(self):
        """Админу и работнику экран недоступен целиком (там деньги)."""
        for user in (self.admin, self.worker):
            response = self.api_as(user).get(SALES)
            self.assertEqual(response.status_code, 403, user.username)

    def test_not_delivered_not_counted(self):
        """Только выданные заказы: новые/отменённые в продажах не считаются."""
        Order.objects.create(
            company=self.company, client=self.customer, product=self.product,
            quantity=Decimal('3'), unit='sht', total_amount=Decimal('9999'),
            status=Order.Status.NEW,
        )
        response = self.api_as(self.owner).get(SALES, {'date_from': '2020-01-01', 'date_to': '2030-01-01'})
        self.assertEqual(response.data['count'], 2)


class ReportReadyNotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='ReportCo')
        cls.owner = User.objects.create_user(
            username='q_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='q_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def test_first_quarterly_view_notifies_owner(self):
        response = self.api_as(self.owner).get(QUARTERLY, {'year': 2026, 'quarter': 3})
        self.assertEqual(response.status_code, 200, response.data)
        notes = Notification.objects.filter(
            user=self.owner, type=Notification.NotificationType.REPORT_READY,
        )
        self.assertEqual(notes.count(), 1)
        self.assertEqual(notes.get().params.get('year'), 2026)
        self.assertEqual(notes.get().params.get('quarter'), 3)

    def test_repeated_view_no_duplicate(self):
        for _ in range(3):
            response = self.api_as(self.owner).get(QUARTERLY, {'year': 2026, 'quarter': 3})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Notification.objects.filter(type=Notification.NotificationType.REPORT_READY).count(), 1,
        )

    def test_next_quarter_notifies_again(self):
        self.api_as(self.owner).get(QUARTERLY, {'year': 2026, 'quarter': 3})
        self.api_as(self.owner).get(QUARTERLY, {'year': 2026, 'quarter': 4})
        self.assertEqual(
            Notification.objects.filter(type=Notification.NotificationType.REPORT_READY).count(), 2,
        )

    def test_admin_operational_report_no_notification(self):
        """Операционный отчёт админа уведомление «отчёт готов» не создаёт
        (ТЗ: это уведомление владельца)."""
        response = self.api_as(self.admin).get(QUARTERLY, {'year': 2026, 'quarter': 3})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(Notification.objects.filter(type=Notification.NotificationType.REPORT_READY).exists())
