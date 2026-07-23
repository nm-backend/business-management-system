"""
Квартальные отчёты Q1–Q4 (фича ТЗ).

Пробел (подтверждён): пресет 'quarter' был «последние 91 день» (скользящее
окно), явного выбора квартала не было. Теперь ?quarter=1..4[&year=YYYY] даёт
календарный квартал, а пресет 'quarter' = текущий календарный квартал.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client, Payment
from apps.companies.models import Company

UTC = datetime.timezone.utc


class QuarterlyReportTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='QRep')
        self.owner = User.objects.create_user(username='qr_owner', password='p',
                                               role=User.Role.OWNER, company=self.company)
        self.cli = Client.objects.create(company=self.company, name='C')
        # Выручка: 300 в Q1 (фев), 700 в Q2 (май) 2026.
        Payment.objects.create(company=self.company, client=self.cli, amount=Decimal('300'),
                               payment_date=datetime.datetime(2026, 2, 15, 12, tzinfo=UTC),
                               payment_method='cash')
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
