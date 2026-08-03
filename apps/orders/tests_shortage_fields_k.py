"""
Поле product_shortage у заказа: предупреждение о нехватке готового товара.

Замечание тестировщика: «создаёшь заказ на товар, которого на складе нет
(или меньше, чем заказано) — никакого предупреждения, узнаёшь только при
выдаче, когда сервер отвечает 400». Воспроизведено: ответ API содержал
только material_shortages (нехватка сырья по рецепту) и ничего про сам
товар.

После правки сериализатор отдаёт has_product_shortage/product_shortage:
- при заказе больше, чем available_quantity (quantity - reserved_for_orders);
- собственный резерв заказа при этом не считается «нехваткой» (при выдаче
  он снимается, и доступное количество вырастает ровно на величину заказа);
- у заказа на ручное название (custom_product_name) поля всегда пустые.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.warehouse.models import FinishedProduct

ORDERS = '/api/v1/orders/orders/'


class ProductShortageFieldTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='ShortCo', is_active=True)
        self.owner = User.objects.create_user(username='short_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('10'), unit='dona')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def create_order(self, quantity='3'):
        resp = self.api.post(ORDERS, {
            'client': self.client_obj.id, 'product': self.product.id,
            'quantity': quantity, 'unit': 'dona',
            'deadline': (timezone.now() + datetime.timedelta(days=5)).isoformat(),
            'total_amount': '1000',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        return resp.json()

    def get_order(self, order_id):
        resp = self.api.get(f'{ORDERS}{order_id}/')
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_enough_stock_no_shortage(self):
        o = self.get_order(self.create_order('3')['id'])
        self.assertFalse(o['has_product_shortage'])
        self.assertIsNone(o['product_shortage'])

    def test_order_more_than_stock_is_flagged(self):
        o = self.get_order(self.create_order('15')['id'])
        self.assertTrue(o['has_product_shortage'])
        self.assertEqual(o['product_shortage']['required'], Decimal('15'))
        self.assertEqual(o['product_shortage']['available'], Decimal('10'))
        self.assertEqual(o['product_shortage']['unit'], 'dona')

    def test_order_equals_stock_is_not_flagged(self):
        o = self.get_order(self.create_order('10')['id'])
        self.assertFalse(o['has_product_shortage'])

    def test_own_reservation_is_not_counted_as_shortage(self):
        # Заказ резервирует 10 из 10: при выдаче резерв снимается и всё
        # доступно — выдавать такой заказ можно, нехватки нет.
        o = self.get_order(self.create_order('10')['id'])
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('10'))
        self.assertFalse(o['has_product_shortage'])

    def test_other_order_reservation_reduces_available(self):
        # Первый заказ зарезервировал 8 из 10 — второй на 3 уже нехватка,
        # хотя физически товара хватает.
        self.create_order('8')
        second = self.get_order(self.create_order('3')['id'])
        self.assertTrue(second['has_product_shortage'])
        self.assertEqual(second['product_shortage']['available'], Decimal('2'))

    def test_custom_product_order_has_no_product_shortage(self):
        resp = self.api.post(ORDERS, {
            'client': self.client_obj.id, 'custom_product_name': 'По эскизу',
            'quantity': '3', 'unit': 'dona',
            'deadline': (timezone.now() + datetime.timedelta(days=5)).isoformat(),
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        o = self.get_order(resp.json()['id'])
        self.assertFalse(o['has_product_shortage'])
        self.assertIsNone(o['product_shortage'])
