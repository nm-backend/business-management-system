"""
Регрессионные тесты N+1 для списка клиентов.

Было: свойство Client.has_active_orders делало .exists() по заказам на КАЖДОГО
клиента (n=12 -> 15 запросов). Стало: один подзапрос Exists -> константа (3).
Тесты фиксируют и число запросов, и то, что значения полей не изменились.
"""
import datetime
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.clients.models import Client
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct


def _client_row(resp, name):
    rows = resp.data['results'] if isinstance(resp.data, dict) else resp.data
    return next(c for c in rows if c['name'] == name)


class ClientsQueryCountTests(TestCase):
    def _seed(self, n, active=True):
        company = Company.objects.create(name=f'CQ{n}')
        owner = User.objects.create_user(username=f'cq_o{n}', password='p',
                                         role=User.Role.OWNER, company=company)
        prod = FinishedProduct.objects.create(company=company, name='P', quantity=Decimal('5'))
        for i in range(n):
            cl = Client.objects.create(company=company, name=f'Cl{i}', debt=Decimal('10'))
            Order.objects.create(
                company=company, client=cl, product=prod, quantity=Decimal('1'),
                unit='izdelie', status='in_progress' if active else 'delivered',
                deadline=datetime.date(2026, 1, 1),
            )
        return owner

    def _count(self, n):
        Company.objects.all().delete()
        User.objects.all().delete()
        owner = self._seed(n)
        api = APIClient()
        api.force_authenticate(user=owner)
        with CaptureQueriesContext(connection) as ctx:
            resp = api.get('/api/v1/clients/clients/')
        self.assertEqual(resp.status_code, 200)
        return len(ctx)

    def test_no_n_plus_one(self):
        """Число запросов не растёт с количеством клиентов."""
        self.assertEqual(self._count(3), self._count(12))

    def test_query_budget(self):
        Company.objects.all().delete()
        User.objects.all().delete()
        owner = self._seed(12)
        api = APIClient()
        api.force_authenticate(user=owner)
        with self.assertNumQueries(3):
            api.get('/api/v1/clients/clients/')


class ClientsPayloadUnchangedTests(TestCase):
    """Оптимизация не изменила значения has_active_orders / has_debt."""

    def setUp(self):
        self.company = Company.objects.create(name='CPay')
        self.owner = User.objects.create_user(username='cpay_o', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.prod = FinishedProduct.objects.create(company=self.company, name='P', quantity=Decimal('5'))
        self.api = APIClient()
        self.api.force_authenticate(user=self.owner)

    def test_active_order_makes_has_active_orders_true(self):
        cl = Client.objects.create(company=self.company, name='WithActive', debt=Decimal('5'))
        Order.objects.create(company=self.company, client=cl, product=self.prod,
                             quantity=Decimal('1'), unit='izdelie', status='in_progress',
                             deadline=datetime.date(2026, 1, 1))
        row = _client_row(self.api.get('/api/v1/clients/clients/'), 'WithActive')
        self.assertTrue(row['has_active_orders'])
        self.assertTrue(row['has_debt'])
        # значение совпадает со свойством модели (источник истины)
        cl.refresh_from_db()
        self.assertEqual(row['has_active_orders'], cl.has_active_orders)

    def test_delivered_order_makes_has_active_orders_false(self):
        cl = Client.objects.create(company=self.company, name='NoActive', debt=Decimal('0'))
        Order.objects.create(company=self.company, client=cl, product=self.prod,
                             quantity=Decimal('1'), unit='izdelie', status='delivered',
                             deadline=datetime.date(2026, 1, 1))
        row = _client_row(self.api.get('/api/v1/clients/clients/'), 'NoActive')
        self.assertFalse(row['has_active_orders'])
        self.assertFalse(row['has_debt'])
        cl.refresh_from_db()
        self.assertEqual(row['has_active_orders'], cl.has_active_orders)

    def test_archived_order_not_counted_active(self):
        cl = Client.objects.create(company=self.company, name='Archived', debt=Decimal('0'))
        Order.objects.create(company=self.company, client=cl, product=self.prod,
                             quantity=Decimal('1'), unit='izdelie', status='in_progress',
                             is_archived=True, deadline=datetime.date(2026, 1, 1))
        row = _client_row(self.api.get('/api/v1/clients/clients/'), 'Archived')
        self.assertFalse(row['has_active_orders'])
