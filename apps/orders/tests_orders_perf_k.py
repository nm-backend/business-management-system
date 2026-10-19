"""
Список заказов: число запросов не зависит от количества строк.

Сериализатор считает нехватку сырья и товара по каждому заказу. Без
select_related/prefetch это давало запрос на рецепт, позиции рецепта и материал
для каждого заказа (N+1). Тест измеряет реальные запросы на двух размерах
списка и требует одинакового числа — предел не «магическая константа», а
отсутствие роста.
"""
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.orders.models import Order
from apps.warehouse.models import (
    FinishedProduct, RawMaterial, Recipe, RecipeItem,
)

ORDERS = '/api/v1/orders/orders/'


class OrdersListQueryCountTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='OrdersPerfCo', is_active=True)
        self.owner = User.objects.create_user(
            username='op_owner', password='p',
            role=User.Role.OWNER, company=self.company,
        )
        self.admin = User.objects.create_user(
            username='op_admin', password='p',
            role=User.Role.ADMIN, company=self.company,
        )
        self.worker = User.objects.create_user(
            username='op_worker', password='p',
            role=User.Role.WORKER, company=self.company,
        )
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.material = RawMaterial.objects.create(
            company=self.company, name='Мрамор', quantity=Decimal('1000'), unit='m2',
        )
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница',
            quantity=Decimal('1000'), unit='sht',
        )
        recipe = Recipe.objects.create(
            company=self.company, product=self.product, name='Основной', is_active=True,
        )
        RecipeItem.objects.create(
            recipe=recipe, material=self.material,
            quantity_required=Decimal('2'), unit='m2',
        )

    def _api(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def _create_orders(self, count, start=0):
        Order.objects.bulk_create([
            Order(
                company=self.company, client=self.client_obj, product=self.product,
                quantity=Decimal('1'), unit='sht',
                total_amount=Decimal('100'), paid_amount=Decimal('0'),
                worker=self.worker,
            )
            for _ in range(start, start + count)
        ])

    def _queries(self, user):
        with CaptureQueriesContext(connection) as captured:
            response = self._api(user).get(ORDERS)
        self.assertEqual(response.status_code, 200)
        return len(captured)

    def test_query_count_does_not_grow_with_order_count(self):
        self._create_orders(3)
        small = self._queries(self.owner)
        self._create_orders(12, start=3)
        large = self._queries(self.owner)

        self.assertEqual(
            small, large,
            f'Число запросов выросло с {small} до {large}: в списке заказов N+1',
        )
        # Список из 15 заказов с рецептами не должен стоить десятков запросов.
        self.assertLessEqual(large, 8, f'{large} запросов на список заказов')

    def test_admin_and_worker_do_not_receive_financial_fields(self):
        self._create_orders(3)
        for user in (self.admin, self.worker):
            response = self._api(user).get(ORDERS)
            self.assertEqual(response.status_code, 200)
            rows = response.json().get('results', response.json())
            self.assertTrue(rows, 'список пуст — проверка бессмысленна')
            for row in rows:
                for field in ('total_amount', 'paid_amount', 'refundable_amount'):
                    self.assertNotIn(field, row,
                                     f'{user.role} получил финансовое поле {field}')

    def test_owner_receives_financial_fields(self):
        self._create_orders(1)
        response = self._api(self.owner).get(ORDERS)
        rows = response.json().get('results', response.json())
        self.assertIn('total_amount', rows[0])
        self.assertIn('paid_amount', rows[0])
        self.assertIn('refundable_amount', rows[0])
