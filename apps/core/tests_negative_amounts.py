"""
Финальный адверсариал — отрицательные/нулевые суммы (финансовая манипуляция).

В моделях НЕТ MinValueValidator, в сериализаторах нет validate_amount. Значит
можно завести отрицательный платёж (уменьшит paid_amount заказа и долг клиента),
отрицательный расход (исказит кассу), отрицательную выплату/ставку/количество.

До фикса тесты падают (негативы принимаются, 201), после — 400.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.clients.models import Client
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct


class NegativeAmountTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='NegCo')
        self.owner = User.objects.create_user(username='n_o', password='p',
                                               role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='n_w', password='p',
                                                role=User.Role.WORKER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='C')
        self.product = FinishedProduct.objects.create(company=self.company, name='P',
                                                      quantity=Decimal('1'))
        self.api = APIClient()
        self.api.force_authenticate(user=self.owner)

    def test_negative_payment_amount_rejected(self):
        resp = self.api.post('/api/v1/clients/payments/', {
            'client': self.client_obj.id, 'amount': '-100',
            'payment_method': 'cash', 'payment_date': '2026-01-15T10:00:00Z',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_zero_payment_amount_rejected(self):
        resp = self.api.post('/api/v1/clients/payments/', {
            'client': self.client_obj.id, 'amount': '0',
            'payment_method': 'cash', 'payment_date': '2026-01-15T10:00:00Z',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_negative_expense_amount_rejected(self):
        resp = self.api.post('/api/v1/finance/expenses/', {
            'category': 'rent', 'amount': '-500', 'date': '2026-01-15',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_negative_worker_payment_rejected(self):
        resp = self.api.post('/api/v1/finance/worker-payments/', {
            'worker': self.worker.id, 'amount': '-300',
            'payment_date': '2026-01-15', 'payment_type': 'salary',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_negative_order_total_amount_rejected(self):
        resp = self.api.post('/api/v1/orders/orders/', {
            'client': self.client_obj.id, 'product': self.product.id,
            'quantity': '1', 'unit': 'sht', 'deadline': '2026-01-01',
            'total_amount': '-1000',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_negative_order_quantity_rejected(self):
        resp = self.api.post('/api/v1/orders/orders/', {
            'client': self.client_obj.id, 'product': self.product.id,
            'quantity': '-5', 'unit': 'sht', 'deadline': '2026-01-01',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_positive_payment_still_works(self):
        resp = self.api.post('/api/v1/clients/payments/', {
            'client': self.client_obj.id, 'amount': '100',
            'payment_method': 'cash', 'payment_date': '2026-01-15T10:00:00Z',
        }, format='json')
        self.assertEqual(resp.status_code, 201)
