"""
Формат csv в экспортах отчётов и валидация периода.

1. ?format=csv раньше молча отдавал xlsx (иного формата не было) — теперь
   каждый экспорт честно отдаёт text/csv с разделителем «;».
2. date_from позже date_to — бессмысленный период: раньше тихо отдавал
   пустой отчёт, теперь 400 с понятным сообщением.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.warehouse.models import RawMaterial

STOCK_URL = '/api/v1/reports/export/stock/'
ANALYTICS_URL = '/api/v1/reports/analytics/owner/'


class ExportCsvFormatTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='CsvCo', is_active=True)
        self.owner = User.objects.create_user(username='csv_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        RawMaterial.objects.create(
            company=self.company, name='Мрамор', stone_type='мрамор',
            quantity=Decimal('5'), unit='dona', min_stock=Decimal('10'))
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_csv_format_returns_csv_content_type(self):
        resp = self.api.get(STOCK_URL + '?format=csv')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('stock-report.csv', resp['Content-Disposition'])

    def test_csv_contains_rows(self):
        resp = self.api.get(STOCK_URL + '?format=csv')
        body = resp.content.decode('utf-8-sig')
        self.assertIn('Мрамор', body)
        self.assertIn(';', body)  # разделитель «;» для Excel

    def test_pdf_format_still_works(self):
        resp = self.api.get(STOCK_URL + '?format=pdf')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')

    def test_default_is_xlsx(self):
        resp = self.api.get(STOCK_URL)
        self.assertEqual(resp['Content-Type'],
                         'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


class ParsePeriodValidationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='PerCo', is_active=True)
        self.owner = User.objects.create_user(username='per_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_date_from_after_date_to_rejected(self):
        resp = self.api.get(ANALYTICS_URL + '?date_from=2026-08-10&date_to=2026-08-01')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('date_from', resp.data)

    def test_normal_period_ok(self):
        resp = self.api.get(ANALYTICS_URL + '?date_from=2026-08-01&date_to=2026-08-10')
        self.assertEqual(resp.status_code, 200)

    def test_bad_date_format_rejected(self):
        resp = self.api.get(ANALYTICS_URL + '?date_from=not-a-date')
        self.assertEqual(resp.status_code, 400)
