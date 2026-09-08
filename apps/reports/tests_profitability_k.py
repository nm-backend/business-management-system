"""
Рентабельность квартала (макет «Кварталлик ҳисобот»: «Рентабеллик 71.2 %»).

Семантика однозначная: доля чистой прибыли в выручке. Именно поэтому
показатель считается, а не подставляется. При нулевой выручке отдаём null, а
не «0 %»: ноль означал бы убыточность, хотя продаж просто не было.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client, Payment
from apps.companies.models import Company
from apps.finance.models import Expense, ExpenseCategory
from apps.orders.models import Order

QUARTERLY = '/api/v1/reports/analytics/quarterly/'


class QuarterProfitabilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='ProfitCo')
        cls.owner = User.objects.create_user(
            username='pf_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='pf_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )
        cls.client_obj = Client.objects.create(company=cls.company, name='Акбаров')

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def current_quarter(self):
        today = timezone.localdate()
        return {'year': today.year, 'quarter': (today.month - 1) // 3 + 1}

    def _revenue(self, amount):
        order = Order.objects.create(
            company=self.company, client=self.client_obj, custom_product_name='Столешница',
            quantity=Decimal('1'), unit='sht', total_amount=Decimal(amount),
            deadline=timezone.now() + timezone.timedelta(days=1),
        )
        Payment.objects.create(
            company=self.company, client=self.client_obj, order=order,
            amount=Decimal(amount), payment_date=timezone.now(),
        )

    def _expense(self, amount):
        Expense.objects.create(
            company=self.company, category=ExpenseCategory.RENT, amount=Decimal(amount),
            created_by=self.owner, date=timezone.localdate(),
        )

    def test_profitability_matches_manual_calculation(self):
        self._revenue('1000.00')
        self._expense('300.00')

        data = self.api_as(self.owner).get(QUARTERLY, self.current_quarter()).data
        revenue = Decimal(str(data['total_revenue']))
        net = Decimal(str(data['total_net_profit']))
        expected = (net / revenue * 100).quantize(Decimal('0.1'))
        self.assertEqual(Decimal(str(data['profitability_percent'])), expected)
        self.assertEqual(Decimal(str(data['profitability_percent'])), Decimal('70.0'))

    def test_zero_revenue_gives_null_not_zero(self):
        """Продаж не было — это не «0 % рентабельности», а отсутствие данных."""
        self._expense('500.00')
        data = self.api_as(self.owner).get(QUARTERLY, self.current_quarter()).data
        self.assertEqual(Decimal(str(data['total_revenue'])), Decimal('0'))
        self.assertIsNone(data['profitability_percent'])

    def test_loss_gives_negative_percent(self):
        self._revenue('1000.00')
        self._expense('1500.00')
        data = self.api_as(self.owner).get(QUARTERLY, self.current_quarter()).data
        self.assertLess(Decimal(str(data['profitability_percent'])), 0)

    def test_admin_quarter_has_no_profitability(self):
        """Рентабельность — финансовый показатель, администратору не отдаётся."""
        self._revenue('1000.00')
        data = self.api_as(self.admin).get(QUARTERLY, self.current_quarter()).data
        self.assertEqual(data['kind'], 'operational')
        self.assertNotIn('profitability_percent', data)
        self.assertNotIn('total_revenue', data)

    def test_value_is_decimal_not_float(self):
        self._revenue('1000.00')
        data = self.api_as(self.owner).get(QUARTERLY, self.current_quarter()).data
        self.assertNotIsInstance(data['profitability_percent'], float)
