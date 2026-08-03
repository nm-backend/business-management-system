"""
Периоды статистики на главной (баги тестеров 1 и 17).

Баг 17: «неделя» была скользящим окном в 7 дней, пересекала границу месяца,
и в начале месяца «неделя» показывала БОЛЬШЕ, чем «месяц» — тестер видел
поломанную математику. Теперь неделя = календарная (понедельник → сегодня).

Баг 1: «другие периоды показывают 0» — регрессия на каждый пресет.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client, Payment
from apps.companies.models import Company

UTC = datetime.timezone.utc
ANALYTICS = '/api/v1/reports/analytics/owner/'


class PeriodPresetsTests(TestCase):
    """Каждый пресет даёт ожидаемые границы и выручку (баг 1)."""

    def setUp(self):
        self.company = Company.objects.create(name='PeriodCo')
        self.owner = User.objects.create_user(
            username='per_owner', password='p',
            role=User.Role.OWNER, company=self.company,
        )
        self.cli = Client.objects.create(company=self.company, name='C')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.today = timezone.localdate()

    def _pay(self, days_ago, amount):
        day = self.today - datetime.timedelta(days=days_ago)
        Payment.objects.create(
            company=self.company, client=self.cli, amount=Decimal(amount),
            payment_date=datetime.datetime.combine(day, datetime.time(12, 0), tzinfo=UTC),
            payment_method='cash',
        )

    def _analytics(self, period):
        resp = self.api.get(ANALYTICS, {'period': period})
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        return resp.json()

    def test_today_yesterday_week_month_year_presets(self):
        # Оплаты: сегодня, вчера, 5 дней назад, 12 дней назад, 250 дней назад.
        amounts = {0: 100, 1: 200, 5: 400, 12: 800, 250: 1600}
        for days_ago, amount in amounts.items():
            self._pay(days_ago, amount)

        monday = self.today - datetime.timedelta(days=self.today.weekday())

        def in_window(days_ago, start):
            return self.today - datetime.timedelta(days=days_ago) >= start

        d = self._analytics('today')
        self.assertEqual(d['date_from'], str(self.today))
        self.assertEqual(d['date_to'], str(self.today))
        self.assertEqual(Decimal(str(d['revenue'])), Decimal('100'))

        d = self._analytics('yesterday')
        self.assertEqual(d['date_from'], str(self.today - datetime.timedelta(days=1)))
        self.assertEqual(Decimal(str(d['revenue'])), Decimal('200'))

        d = self._analytics('week')
        self.assertEqual(d['date_from'], str(monday))
        self.assertEqual(
            Decimal(str(d['revenue'])),
            Decimal(str(sum(v for k, v in amounts.items() if in_window(k, monday)))),
        )

        first_of_month = self.today.replace(day=1)
        d = self._analytics('month')
        self.assertEqual(d['date_from'], str(first_of_month))
        self.assertEqual(
            Decimal(str(d['revenue'])),
            Decimal(str(sum(v for k, v in amounts.items() if in_window(k, first_of_month)))),
        )

        jan_1 = self.today.replace(month=1, day=1)
        d = self._analytics('year')
        self.assertEqual(d['date_from'], str(jan_1))
        self.assertEqual(
            Decimal(str(d['revenue'])),
            Decimal(str(sum(v for k, v in amounts.items() if in_window(k, jan_1)))),
        )

    def test_calendar_week_excludes_previous_sunday(self):
        """Баг 17: воскресенье прошлой недели НЕ попадает в «неделю»."""
        monday = self.today - datetime.timedelta(days=self.today.weekday())
        prev_sunday = monday - datetime.timedelta(days=1)
        self._pay(0, 100)

        Payment.objects.create(
            company=self.company, client=self.cli, amount=Decimal('999'),
            payment_date=datetime.datetime.combine(
                prev_sunday, datetime.time(12, 0), tzinfo=UTC,
            ),
            payment_method='cash',
        )
        d = self._analytics('week')
        self.assertEqual(d['date_from'], str(monday))
        self.assertEqual(Decimal(str(d['revenue'])), Decimal('100'))

    def test_week_window_inside_month_when_started_in_month(self):
        """
        Когда неделя началась в текущем месяце, её окно строго внутри окна
        месяца (неделя никогда не «обгоняет» месяц).
        """
        monday = self.today - datetime.timedelta(days=self.today.weekday())
        first_of_month = self.today.replace(day=1)
        if monday < first_of_month:
            self.skipTest('Неделя пересекает границу месяца — семантика календаря.')
        d_week = self._analytics('week')
        d_month = self._analytics('month')
        self.assertGreaterEqual(d_week['date_from'], d_month['date_from'])
        self.assertEqual(d_week['date_to'], d_month['date_to'])
