"""
Unit-тесты для приложения finance: строковые представления моделей
Expense, LaborRate, WorkerPayment.
"""
import datetime
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import User
from apps.finance.models import Expense, LaborRate, WorkerPayment
from apps.warehouse.models import FinishedProduct


class ExpenseTests(TestCase):
    def test_str_shows_category_and_amount(self):
        expense = Expense(category='rent', amount=Decimal('500'))
        self.assertEqual(str(expense), 'Ижара - 500')


class LaborRateTests(TestCase):
    def test_str_shows_product_operation_and_rate(self):
        product = FinishedProduct.objects.create(name='Slab')
        rate = LaborRate.objects.create(
            product=product,
            operation=LaborRate.OperationType.CUTTING,
            rate_per_unit=Decimal('12.50'),
            unit='sht',
        )
        self.assertEqual(str(rate), 'Slab - Кесиш: 12.50 / sht')


class WorkerPaymentTests(TestCase):
    def test_str_shows_worker_amount_and_type(self):
        worker = User.objects.create_user(username='joe', role=User.Role.WORKER)
        payment = WorkerPayment(
            worker=worker,
            amount=Decimal('1000'),
            payment_date=datetime.date(2024, 1, 1),
            payment_type=WorkerPayment.PaymentType.SALARY,
        )
        self.assertEqual(str(payment), 'joe - 1000 (Иш ҳақи)')


class FinanceCreateAPITests(TestCase):
    """Создание расхода/выплаты/ставки через API (owner), с проставлением company."""

    def setUp(self):
        from rest_framework.test import APIClient
        from apps.companies.models import Company
        self.company = Company.objects.create(name='FinCo')
        self.owner = User.objects.create_user(
            username='fin_owner', password='pw', role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(
            username='fin_worker', password='pw', role=User.Role.WORKER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(user=self.owner)

    def test_owner_creates_expense(self):
        resp = self.api.post('/api/v1/finance/expenses/', {
            'category': 'rent', 'amount': '500000', 'date': '2026-07-13', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        exp = Expense.objects.get()
        self.assertEqual(exp.company, self.company)
        self.assertEqual(exp.created_by, self.owner)

    def test_owner_creates_worker_payment(self):
        resp = self.api.post('/api/v1/finance/worker-payments/', {
            'worker': self.worker.id, 'amount': '300000',
            'payment_date': '2026-07-13', 'payment_type': 'salary',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        pay = WorkerPayment.objects.get()
        self.assertEqual(pay.company, self.company)
        self.assertEqual(pay.created_by, self.owner)

    def test_owner_creates_labor_rate(self):
        product = FinishedProduct.objects.create(name='Slab', company=self.company)
        resp = self.api.post('/api/v1/finance/labor-rates/', {
            'product': product.id, 'operation': 'cutting', 'rate_per_unit': '15000', 'unit': 'sht',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(LaborRate.objects.get().company, self.company)
