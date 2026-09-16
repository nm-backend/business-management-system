"""
Квартальные отчёты Q1–Q4 (фича ТЗ).

Пробел (подтверждён): пресет 'quarter' был «последние 91 день» (скользящее
окно), явного выбора квартала не было. Теперь ?quarter=1..4[&year=YYYY] даёт
календарный квартал, а пресет 'quarter' = текущий календарный квартал.

Revenue = SUM(Order.total_amount) для выданных заказов (accrual).
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client, Payment
from apps.companies.models import Company
from apps.orders.models import Order

UTC = datetime.timezone.utc


class QuarterlyReportTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='QRep')
        self.owner = User.objects.create_user(username='qr_owner', password='p',
                                               role=User.Role.OWNER, company=self.company)
        self.cli = Client.objects.create(company=self.company, name='C')
        # Заказы с выдачей: 300 в Q1 (фев), 700 в Q2 (май) 2026.
        o1 = Order.objects.create(
            company=self.company, client=self.cli, custom_product_name='Изделие',
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('300'),
            deadline=datetime.datetime(2026, 2, 20, tzinfo=UTC),
        )
        o1.status = Order.Status.DELIVERED
        o1.save(update_fields=['status'])
        Order.objects.filter(pk=o1.pk).update(
            delivered_at=datetime.datetime(2026, 2, 15, tzinfo=UTC))
        Payment.objects.create(company=self.company, client=self.cli, amount=Decimal('300'),
                               payment_date=datetime.datetime(2026, 2, 15, 12, tzinfo=UTC),
                               payment_method='cash')
        o2 = Order.objects.create(
            company=self.company, client=self.cli, custom_product_name='Изделие',
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('700'),
            deadline=datetime.datetime(2026, 5, 25, tzinfo=UTC),
        )
        o2.status = Order.Status.DELIVERED
        o2.save(update_fields=['status'])
        Order.objects.filter(pk=o2.pk).update(
            delivered_at=datetime.datetime(2026, 5, 20, tzinfo=UTC))
        Payment.objects.create(company=self.company, client=self.cli, amount=Decimal('700'),
                               payment_date=datetime.datetime(2026, 5, 20, 12, tzinfo=UTC),
                               payment_method='cash')

    def _get(self, qs):
        c = APIClient()
        c.force_authenticate(self.owner)
        return c.get('/api/v1/reports/analytics/owner/' + qs)

    def test_q1_bounds_and_revenue(self):
        r = self._get('?quarter=1&year=2026')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['date_from'], '2026-01-01')
        self.assertEqual(r.json()['date_to'], '2026-03-31')
        self.assertEqual(Decimal(str(r.json()['revenue'])), Decimal('300'))

    def test_q2_bounds_and_revenue(self):
        r = self._get('?quarter=2&year=2026')
        self.assertEqual(r.json()['date_from'], '2026-04-01')
        self.assertEqual(r.json()['date_to'], '2026-06-30')
        self.assertEqual(Decimal(str(r.json()['revenue'])), Decimal('700'))

    def test_q4_bounds(self):
        r = self._get('?quarter=4&year=2026')
        self.assertEqual(r.json()['date_from'], '2026-10-01')
        self.assertEqual(r.json()['date_to'], '2026-12-31')

    def test_invalid_quarter_rejected(self):
        self.assertEqual(self._get('?quarter=5').status_code, 400)
        self.assertEqual(self._get('?quarter=0').status_code, 400)
        self.assertEqual(self._get('?quarter=abc').status_code, 400)
