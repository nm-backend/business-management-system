"""
Произвольный период отчёта (ТЗ §18, макет «хусусий»).

Сервер — источник границ: date_from + date_to. Один конец без другого
раньше молча подставлял «месяц» и врал цифры. Здесь — 400.
Границы включительные, в TIME_ZONE компании (Asia/Bishkek).
Экспорт finance использует тот же _parse_period.
"""
import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client, Payment
from apps.companies.models import Company

BISHKEK = ZoneInfo('Asia/Bishkek')
ANALYTICS = '/api/v1/reports/analytics/owner/'
EXPORT = '/api/v1/reports/export/finance/'


class CustomReportPeriodTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='CustomPeriodCo')
        self.other = Company.objects.create(name='OtherCo')
        self.owner = User.objects.create_user(
            username='cp_owner', password='p',
            role=User.Role.OWNER, company=self.company,
        )
        self.admin = User.objects.create_user(
            username='cp_admin', password='p',
            role=User.Role.ADMIN, company=self.company,
        )
        self.worker = User.objects.create_user(
            username='cp_worker', password='p',
            role=User.Role.WORKER, company=self.company,
        )
        self.other_owner = User.objects.create_user(
            username='cp_other', password='p',
            role=User.Role.OWNER, company=self.other,
        )
        self.cli = Client.objects.create(company=self.company, name='Клиент A')
        self.cli_b = Client.objects.create(company=self.other, name='Клиент B')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _pay(self, when, amount, client=None, company=None):
        if isinstance(when, datetime.date) and not isinstance(when, datetime.datetime):
            when = datetime.datetime(when.year, when.month, when.day, 12, 0, tzinfo=BISHKEK)
        Payment.objects.create(
            company=company or self.company,
            client=client or self.cli,
            amount=Decimal(str(amount)),
            payment_method='cash',
            payment_date=when,
        )

    def _get(self, params, user=None):
        api = self.api
        if user is not None:
            api = APIClient()
            api.force_authenticate(user)
        return api.get(ANALYTICS, params)

    def test_custom_range_returns_exact_bounds_and_revenue(self):
        self._pay(datetime.date(2026, 7, 31), 100)
        self._pay(datetime.date(2026, 8, 1), 200)
        self._pay(datetime.date(2026, 8, 10), 300)
        self._pay(datetime.date(2026, 8, 11), 400)
        resp = self._get({'date_from': '2026-08-01', 'date_to': '2026-08-10'})
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        data = resp.json()
        self.assertEqual(data['date_from'], '2026-08-01')
        self.assertEqual(data['date_to'], '2026-08-10')
        self.assertEqual(Decimal(str(data['revenue'])), Decimal('500'))

    def test_same_day_range_is_inclusive(self):
        self._pay(datetime.date(2026, 8, 5), 77)
        self._pay(datetime.date(2026, 8, 6), 11)
        resp = self._get({'date_from': '2026-08-05', 'date_to': '2026-08-05'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['date_from'], '2026-08-05')
        self.assertEqual(data['date_to'], '2026-08-05')
        self.assertEqual(Decimal(str(data['revenue'])), Decimal('77'))

    def test_date_from_after_date_to_is_400(self):
        resp = self._get({'date_from': '2026-08-10', 'date_to': '2026-08-01'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('date_from', resp.data)

    def test_invalid_iso_is_400(self):
        resp = self._get({'date_from': '2026-13-40', 'date_to': '2026-08-01'})
        self.assertEqual(resp.status_code, 400)
        resp = self._get({'date_from': 'not-a-date', 'date_to': '2026-08-01'})
        self.assertEqual(resp.status_code, 400)

    def test_only_one_bound_is_400(self):
        only_from = self._get({'date_from': '2026-08-01'})
        self.assertEqual(only_from.status_code, 400)
        self.assertIn('date_to', only_from.data)
        only_to = self._get({'date_to': '2026-08-10'})
        self.assertEqual(only_to.status_code, 400)
        self.assertIn('date_from', only_to.data)

    def test_presets_still_work_without_custom_dates(self):
        today = timezone.localdate()
        self._pay(today, 55)
        resp = self._get({'period': 'today'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['date_from'], str(today))
        self.assertEqual(data['date_to'], str(today))
        self.assertEqual(Decimal(str(data['revenue'])), Decimal('55'))

    def test_admin_and_worker_forbidden_with_custom_dates(self):
        params = {'date_from': '2026-08-01', 'date_to': '2026-08-10'}
        self.assertEqual(self._get(params, user=self.admin).status_code, 403)
        self.assertEqual(self._get(params, user=self.worker).status_code, 403)
        export_api = APIClient()
        export_api.force_authenticate(self.admin)
        self.assertEqual(export_api.get(EXPORT, params).status_code, 403)
        export_api.force_authenticate(self.worker)
        self.assertEqual(export_api.get(EXPORT, params).status_code, 403)

    def test_tenant_isolation_on_custom_range(self):
        self._pay(datetime.date(2026, 8, 3), 40)
        self._pay(
            datetime.date(2026, 8, 3), 999,
            client=self.cli_b, company=self.other,
        )
        resp = self._get({'date_from': '2026-08-01', 'date_to': '2026-08-10'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Decimal(str(resp.json()['revenue'])), Decimal('40'))

    def test_bishkek_calendar_day_not_utc(self):
        """23:59 1 августа по Бишкеку входит в 1 августа, 00:01 2-го — нет."""
        inside = datetime.datetime(2026, 8, 1, 23, 59, tzinfo=BISHKEK)
        outside = datetime.datetime(2026, 8, 2, 0, 1, tzinfo=BISHKEK)
        # 18:01 UTC 1 августа = 00:01 2 августа в Бишкеке — уже другой день.
        utc_next_local = datetime.datetime(2026, 8, 1, 18, 1, tzinfo=datetime.timezone.utc)
        self._pay(inside, 10)
        self._pay(outside, 20)
        self._pay(utc_next_local, 40)
        resp = self._get({'date_from': '2026-08-01', 'date_to': '2026-08-01'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Decimal(str(resp.json()['revenue'])), Decimal('10'))

    def test_finance_export_csv_uses_same_custom_range(self):
        self._pay(datetime.date(2026, 8, 2), 123)
        self._pay(datetime.date(2026, 7, 1), 9)
        resp = self.api.get(EXPORT, {
            'date_from': '2026-08-01',
            'date_to': '2026-08-10',
            'format': 'csv',
        })
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        self.assertEqual(resp['Content-Type'], 'text/csv; charset=utf-8')
        body = resp.content.decode('utf-8-sig')
        self.assertIn('2026-08-01 - 2026-08-10', body)
        self.assertIn('123', body)
        self.assertNotIn('2026-07-01', body)
