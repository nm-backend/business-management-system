"""
Regression tests for accrual-based financial semantics.

A. Sale 100k / payment 30k → Revenue=100k, Cash=30k (accrual ≠ cash)
B. Sale 100k / no payment → Revenue=100k, Cash=0, Debt=100k
C. Salary expense reduces Net Profit
D. 3 identical months = quarterly total (sum(monthly) == quarterly)
E. SalesHistory Revenue == OwnerAnalytics Revenue (both accrual)
F. S3 direct URL → private ACL (settings test)
"""
import datetime
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client, Payment
from apps.companies.models import Company
from apps.finance.models import Expense, ExpenseCategory, WorkerPayment
from apps.orders.models import Order

OWNER = '/api/v1/reports/analytics/owner/'
QUARTERLY = '/api/v1/reports/analytics/quarterly/'
SALES = '/api/v1/reports/analytics/sales/'


class AccrualVsCashTests(TestCase):
    """A. Revenue (accrual) ≠ Cash (payments) when partial payment."""

    def setUp(self):
        self.company = Company.objects.create(name='ACo', is_active=True)
        self.owner = User.objects.create_user(username='a_owner', password='p',
                                               role=User.Role.OWNER, company=self.company)
        self.client = Client.objects.create(company=self.company, name='К')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

        # Delivered order for 100k, only 30k paid
        order = Order.objects.create(
            company=self.company, client=self.client, custom_product_name='Изделие',
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('100000'),
            deadline=timezone.now() + datetime.timedelta(days=3),
        )
        order.status = Order.Status.DELIVERED
        order.save(update_fields=['status'])
        Payment.objects.create(company=self.company, client=self.client, order=order,
                               amount=Decimal('30000'), payment_date=timezone.now(),
                               payment_method='cash')

    def test_revenue_is_accrual(self):
        d = self.api.get(OWNER, {'period': 'month'}).json()
        self.assertEqual(Decimal(str(d['revenue'])), Decimal('100000'),
                         'Revenue = sum of delivered order totals (accrual)')

    def test_cash_is_payments_based(self):
        d = self.api.get(OWNER, {'period': 'month'}).json()
        self.assertEqual(Decimal(str(d['cash'])), Decimal('30000'),
                         'Cash = payments received')

    def test_revenue_differs_from_cash(self):
        d = self.api.get(OWNER, {'period': 'month'}).json()
        self.assertNotEqual(Decimal(str(d['revenue'])), Decimal(str(d['cash'])),
                            'Accrual revenue ≠ cash when partial payment')


class ZeroPaymentTests(TestCase):
    """B. Sale 100k / no payment → Revenue=100k, Cash=0, Debt=100k."""

    def setUp(self):
        self.company = Company.objects.create(name='BCo', is_active=True)
        self.owner = User.objects.create_user(username='b_owner', password='p',
                                               role=User.Role.OWNER, company=self.company)
        self.client = Client.objects.create(company=self.company, name='К')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

        order = Order.objects.create(
            company=self.company, client=self.client, custom_product_name='Изделие',
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('100000'),
            deadline=timezone.now() + datetime.timedelta(days=3),
        )
        order.status = Order.Status.DELIVERED
        order.save(update_fields=['status'])

    def test_revenue_with_zero_payment(self):
        d = self.api.get(OWNER, {'period': 'month'}).json()
        self.assertEqual(Decimal(str(d['revenue'])), Decimal('100000'))

    def test_cash_with_zero_payment(self):
        d = self.api.get(OWNER, {'period': 'month'}).json()
        self.assertEqual(Decimal(str(d['cash'])), Decimal('0'))

    def test_client_debt_equals_order(self):
        d = self.api.get(OWNER, {'period': 'month'}).json()
        self.client.refresh_from_db()
        self.assertEqual(Decimal(str(d['client_debts'])), Decimal(str(self.client.debt)))


class SalaryReducesNetProfitTests(TestCase):
    """C. Salary expenses reduce Net Profit."""

    def setUp(self):
        self.company = Company.objects.create(name='CCo', is_active=True)
        self.owner = User.objects.create_user(username='c_owner', password='p',
                                               role=User.Role.OWNER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

        # Revenue 100k, no other expenses
        order = Order.objects.create(
            company=self.company, client=Client.objects.create(company=self.company, name='К'),
            custom_product_name='Изделие', quantity=Decimal('1'), unit='sht',
            total_amount=Decimal('100000'),
            deadline=timezone.now() + datetime.timedelta(days=3),
        )
        order.status = Order.Status.DELIVERED
        order.save(update_fields=['status'])

    def _get(self):
        return self.api.get(OWNER, {'period': 'month'}).json()

    def test_no_salary(self):
        d = self._get()
        self.assertEqual(Decimal(str(d['salaries'])), Decimal('0'))
        self.assertEqual(Decimal(str(d['net_profit'])), Decimal('100000'))

    def test_salary_reduces_profit(self):
        Expense.objects.create(
            company=self.company, category=ExpenseCategory.SALARY,
            amount=Decimal('20000'), date=timezone.localdate(),
            created_by=self.owner,
        )
        d = self._get()
        self.assertEqual(Decimal(str(d['salaries'])), Decimal('20000'))
        self.assertEqual(Decimal(str(d['net_profit'])), Decimal('80000'))


class QuarterlyConsistencyTests(TestCase):
    """D. sum(monthly net_profit) == quarterly net_profit."""

    def setUp(self):
        self.company = Company.objects.create(name='DCo', is_active=True)
        self.owner = User.objects.create_user(username='d_owner', password='p',
                                               role=User.Role.OWNER, company=self.company)
        self.client = Client.objects.create(company=self.company, name='К')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

        # Create delivered orders in Jan, Feb, Mar 2026
        for month, amount in ((1, '100'), (2, '200'), (3, '300')):
            order = Order.objects.create(
                company=self.company, client=self.client, custom_product_name='X',
                quantity=Decimal('1'), unit='sht', total_amount=Decimal(amount),
                deadline=datetime.datetime(2026, month, 20, tzinfo=datetime.timezone.utc),
            )
            order.status = Order.Status.DELIVERED
            order.save(update_fields=['status'])
            Order.objects.filter(pk=order.pk).update(
                delivered_at=datetime.datetime(2026, month, 15, tzinfo=datetime.timezone.utc))

    def test_quarterly_equals_sum_of_months(self):
        resp = self.api.get(QUARTERLY, {'quarter': 1, 'year': 2026})
        self.assertEqual(resp.status_code, 200)
        q = resp.json()

        monthly_profits = [Decimal(str(m['net_profit'])) for m in q['months']]
        quarterly_profit = Decimal(str(q['total_net_profit']))
        self.assertEqual(sum(monthly_profits), quarterly_profit,
                         f'sum(monthly)={sum(monthly_profits)} != quarterly={quarterly_profit}')

    def test_quarterly_revenue_equals_sum(self):
        resp = self.api.get(QUARTERLY, {'quarter': 1, 'year': 2026})
        q = resp.json()
        monthly_rev = [Decimal(str(m['revenue'])) for m in q['months']]
        self.assertEqual(sum(monthly_rev), Decimal(str(q['total_revenue'])))


class SalesHistoryConsistencyTests(TestCase):
    """E. SalesHistory total_amount matches OwnerAnalytics revenue (both accrual)."""

    def setUp(self):
        self.company = Company.objects.create(name='ECo', is_active=True)
        self.owner = User.objects.create_user(username='e_owner', password='p',
                                               role=User.Role.OWNER, company=self.company)
        self.client = Client.objects.create(company=self.company, name='К')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

        order = Order.objects.create(
            company=self.company, client=self.client, custom_product_name='Изделие',
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('50000'),
            deadline=timezone.now() + datetime.timedelta(days=3),
        )
        order.status = Order.Status.DELIVERED
        order.save(update_fields=['status'])
        Payment.objects.create(company=self.company, client=self.client, order=order,
                               amount=Decimal('30000'), payment_date=timezone.now(),
                               payment_method='cash')

    def test_sales_total_matches_owner_revenue(self):
        sales = self.api.get(SALES, {'period': 'month'}).json()
        owner = self.api.get(OWNER, {'period': 'month'}).json()
        self.assertEqual(Decimal(str(sales['total_amount'])),
                         Decimal(str(owner['revenue'])),
                         'SalesHistory total == OwnerAnalytics revenue (both accrual)')


class S3SecurityTests(TestCase):
    """F. S3 bucket configured with private ACL + signed URLs."""

    def test_private_acl_in_settings(self):
        import pathlib
        prod = pathlib.Path(__file__).resolve().parent.parent.parent / 'skladpro' / 'settings' / 'production.py'
        content = prod.read_text(encoding='utf-8')
        self.assertIn("'default_acl': 'private'", content)
        self.assertIn("'querystring_auth': True", content)
