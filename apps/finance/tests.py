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
