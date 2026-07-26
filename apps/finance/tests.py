"""
API tests for finance app.

Coverage:
- Expense CRUD (owner only)
- LaborRate CRUD (owner only)
- WorkerPayment CRUD (owner only)
- Analytics endpoint (owner only, correct formulas)
- RBAC: admin/worker cannot access finance endpoints
"""
from decimal import Decimal
from datetime import date, timedelta
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.warehouse.models import FinishedProduct
from apps.orders.models import Order, OrderStatus, PaymentStatus
from apps.finance.models import Expense, ExpenseCategory, LaborRate, WorkerPayment, PaymentMethod


def _create_users():
    owner = User.objects.create_user(
        username='owner', password='owner123', role=User.Role.OWNER
    )
    admin = User.objects.create_user(
        username='admin', password='admin123', role=User.Role.ADMIN
    )
    worker = User.objects.create_user(
        username='worker', password='worker123', role=User.Role.WORKER
    )
    return owner, admin, worker


class ExpenseCRUDTests(TestCase):
    """Tests for Expense CRUD - owner only."""

    def setUp(self):
        self.api = APIClient()
        self.owner, self.admin, self.worker = _create_users()

    def test_owner_can_create_expense(self):
        self.api.force_authenticate(user=self.owner)
        response = self.api.post('/api/v1/finance/expenses/', {
            'category': ExpenseCategory.RENT,
            'amount': 1000,
            'date': '2026-07-01',
            'comment': 'Office rent',
            'payment_method': PaymentMethod.CASH,
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Expense.objects.count(), 1)
        self.assertEqual(response.data['category'], ExpenseCategory.RENT)

    def test_admin_cannot_create_expense(self):
        self.api.force_authenticate(user=self.admin)
        response = self.api.post('/api/v1/finance/expenses/', {
            'category': ExpenseCategory.RENT,
            'amount': 500,
            'date': '2026-07-01',
        })
        self.assertEqual(response.status_code, 403)

    def test_worker_cannot_create_expense(self):
        self.api.force_authenticate(user=self.worker)
        response = self.api.post('/api/v1/finance/expenses/', {
            'category': ExpenseCategory.RENT,
            'amount': 500,
            'date': '2026-07-01',
        })
        self.assertEqual(response.status_code, 403)

    def test_owner_can_list_expenses(self):
        self.api.force_authenticate(user=self.owner)
        Expense.objects.create(
            category=ExpenseCategory.RENT, amount=1000, date='2026-07-01',
            created_by=self.owner,
        )
        Expense.objects.create(
            category=ExpenseCategory.ELECTRICITY, amount=200, date='2026-07-01',
            created_by=self.owner,
        )
        response = self.api.get('/api/v1/finance/expenses/')
        self.assertEqual(response.status_code, 200)
        data = response.json() if hasattr(response, 'content') else response.data
        results = data.get('results', data) if isinstance(data, dict) else data
        self.assertEqual(len(results), 2)

    def test_filter_by_category(self):
        self.api.force_authenticate(user=self.owner)
        Expense.objects.create(
            category=ExpenseCategory.RENT, amount=1000, date='2026-07-01',
            created_by=self.owner,
        )
        Expense.objects.create(
            category=ExpenseCategory.TAXES, amount=500, date='2026-07-01',
            created_by=self.owner,
        )
        response = self.api.get(f'/api/v1/finance/expenses/?category={ExpenseCategory.RENT}')
        self.assertEqual(response.status_code, 200)
        data = response.json() if hasattr(response, 'content') else response.data
        results = data.get('results', data) if isinstance(data, dict) else data
        self.assertEqual(len(results), 1)

    def test_unauthenticated_cannot_create(self):
        response = self.api.post('/api/v1/finance/expenses/', {
            'category': ExpenseCategory.RENT,
            'amount': 100,
            'date': '2026-07-01',
        })
        self.assertEqual(response.status_code, 401)


class LaborRateCRUDTests(TestCase):
    """Tests for LaborRate CRUD - owner only."""

    def setUp(self):
        self.api = APIClient()
        self.owner, self.admin, self.worker = _create_users()
        self.product = FinishedProduct.objects.create(
            name='Granite', unit='m2', quantity=10
        )

    def test_owner_can_create_labor_rate(self):
        self.api.force_authenticate(user=self.owner)
        response = self.api.post('/api/v1/finance/labor-rates/', {
            'product': self.product.id,
            'operation': LaborRate.OperationType.CUTTING,
            'rate_per_unit': 150,
            'unit': 'm2',
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(LaborRate.objects.count(), 1)

    def test_admin_cannot_create_labor_rate(self):
        self.api.force_authenticate(user=self.admin)
        response = self.api.post('/api/v1/finance/labor-rates/', {
            'product': self.product.id,
            'operation': LaborRate.OperationType.CUTTING,
            'rate_per_unit': 150,
            'unit': 'm2',
        })
        self.assertEqual(response.status_code, 403)

    def test_unique_constraint(self):
        self.api.force_authenticate(user=self.owner)
        self.api.post('/api/v1/finance/labor-rates/', {
            'product': self.product.id,
            'operation': LaborRate.OperationType.CUTTING,
            'rate_per_unit': 150,
            'unit': 'm2',
        })
        response = self.api.post('/api/v1/finance/labor-rates/', {
            'product': self.product.id,
            'operation': LaborRate.OperationType.CUTTING,
            'rate_per_unit': 200,
            'unit': 'm2',
        })
        self.assertEqual(response.status_code, 400)


class WorkerPaymentCRUDTests(TestCase):
    """Tests for WorkerPayment CRUD - owner only."""

    def setUp(self):
        self.api = APIClient()
        self.owner, self.admin, self.worker = _create_users()

    def test_owner_can_create_payment(self):
        self.api.force_authenticate(user=self.owner)
        response = self.api.post('/api/v1/finance/worker-payments/', {
            'worker': self.worker.id,
            'amount': 5000,
            'payment_date': '2026-07-15',
            'payment_type': 'salary',
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(WorkerPayment.objects.count(), 1)

    def test_admin_cannot_create_payment(self):
        self.api.force_authenticate(user=self.admin)
        response = self.api.post('/api/v1/finance/worker-payments/', {
            'worker': self.worker.id,
            'amount': 5000,
            'payment_date': '2026-07-15',
        })
        self.assertEqual(response.status_code, 403)


class AnalyticsTests(TestCase):
    """Tests for finance analytics endpoint."""

    def setUp(self):
        self.api = APIClient()
        self.owner, self.admin, self.worker = _create_users()
        self.client_obj = Client.objects.create(name='Test Client')
        self.product = FinishedProduct.objects.create(
            name='Product', unit='m2', quantity=10,
            cost_price=Decimal('300'), sale_price=Decimal('800'),
        )

    def test_owner_can_access_analytics(self):
        self.api.force_authenticate(user=self.owner)
        response = self.api.get('/api/v1/finance/analytics/?period=month')
        self.assertEqual(response.status_code, 200)
        self.assertIn('revenue', response.data)
        self.assertIn('net_profit', response.data)
        self.assertIn('cash_in_register', response.data)

    def test_admin_cannot_access_analytics(self):
        self.api.force_authenticate(user=self.admin)
        response = self.api.get('/api/v1/finance/analytics/?period=month')
        self.assertEqual(response.status_code, 403)

    def test_worker_cannot_access_analytics(self):
        self.api.force_authenticate(user=self.worker)
        response = self.api.get('/api/v1/finance/analytics/?period=month')
        self.assertEqual(response.status_code, 403)

    def test_analytics_returns_zeroes_without_data(self):
        self.api.force_authenticate(user=self.owner)
        response = self.api.get('/api/v1/finance/analytics/?period=month')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['revenue'], '0')
        self.assertEqual(response.data['net_profit'], '0')
        self.assertEqual(response.data['gross_profit'], '0')

    def test_analytics_with_orders(self):
        self.api.force_authenticate(user=self.owner)
        Order.objects.create(
            client=self.client_obj, product=self.product, quantity=2, unit='m2',
            deadline=date.today(), status=OrderStatus.DELIVERED,
            total_amount=Decimal('1600'), paid_amount=Decimal('1600'),
            payment_status=PaymentStatus.PAID,
        )
        response = self.api.get('/api/v1/finance/analytics/?period=month')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['revenue'], '1600')

    def test_analytics_periods(self):
        self.api.force_authenticate(user=self.owner)
        for period in ['today', 'yesterday', 'week', 'month', 'quarter', 'year']:
            response = self.api.get(f'/api/v1/finance/analytics/?period={period}')
            self.assertEqual(response.status_code, 200, f"Period {period} failed")
            self.assertIn('period', response.data)

    def test_custom_period(self):
        self.api.force_authenticate(user=self.owner)
        response = self.api.get(
            '/api/v1/finance/analytics/?period=custom&date_from=2026-01-01&date_to=2026-12-31'
        )
        self.assertEqual(response.status_code, 200)
