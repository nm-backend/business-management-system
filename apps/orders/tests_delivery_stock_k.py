"""
Заказ без товара и списание склада при выдаче.

Два замечания тестировщиков, оба воспроизведены до правки:

1. Заказ создавался вообще без товара: POST без product и без
   custom_product_name отвечал 201. Такой заказ ничего не резервирует
   (reserve_product выходит на `if not self.product_id`), не участвует в
   расчёте нехватки и не может быть корректно выдан.

2. Выдача заказа не списывала готовую продукцию и не писала движение склада.
   Товар уезжал к клиенту, а остаток продолжал его показывать; в журнале
   движений выдачи не было. Отсюда расхождение остатков, журнала и статистики.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct, StockMovement

ORDERS = '/api/v1/orders/orders/'


class _Base(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='DelivCo', is_active=True)
        self.owner = User.objects.create_user(username='dlv_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('10'), unit='dona')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def deadline(self):
        return (timezone.now() + datetime.timedelta(days=5)).isoformat()

    def create_order(self, **over):
        body = {'client': self.client_obj.id, 'product': self.product.id,
                'quantity': '3', 'unit': 'dona', 'deadline': self.deadline(),
                'total_amount': '1000'}
        body.update(over)
        return self.api.post(ORDERS, body, format='json')


class OrderMustHaveProductTests(_Base):
    def test_order_without_any_product_is_rejected(self):
        resp = self.api.post(ORDERS, {
            'client': self.client_obj.id, 'quantity': '2', 'unit': 'dona',
            'deadline': self.deadline(),
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('product', resp.json())

    def test_blank_custom_name_is_not_enough(self):
        resp = self.api.post(ORDERS, {
            'client': self.client_obj.id, 'quantity': '2', 'unit': 'dona',
            'custom_product_name': '   ', 'deadline': self.deadline(),
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_catalogue_product_is_accepted(self):
        self.assertEqual(self.create_order().status_code, 201)

    def test_custom_product_name_is_accepted(self):
        """Изделие «по описанию» каталожной позиции не имеет — это законно."""
        resp = self.api.post(ORDERS, {
            'client': self.client_obj.id, 'quantity': '2', 'unit': 'dona',
            'custom_product_name': 'Столешница по эскизу', 'deadline': self.deadline(),
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:200])

    def test_existing_order_cannot_lose_its_product(self):
        order_id = self.create_order().json()['id']
        resp = self.api.patch(f'{ORDERS}{order_id}/',
                              {'product': None, 'custom_product_name': ''}, format='json')
        self.assertEqual(resp.status_code, 400)


class DeliveryWritesOffStockTests(_Base):
    def deliver(self, order_id):
        return self.api.post(f'{ORDERS}{order_id}/deliver/')

    def test_delivery_reduces_stock_and_writes_movement(self):
        order_id = self.create_order().json()['id']
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('3.000'),
                         'заказ должен зарезервировать товар')

        resp = self.deliver(order_id)
        self.assertEqual(resp.status_code, 200, resp.content[:200])

        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('7.000'), 'остаток должен уменьшиться')
        self.assertEqual(self.product.reserved_for_orders, Decimal('0.000'), 'резерв снят')

        movement = StockMovement.objects.get(product=self.product,
                                             movement_type=StockMovement.MovementType.OUTGOING)
        self.assertEqual(movement.quantity, Decimal('3.000'))
        self.assertEqual(movement.company_id, self.company.id)
        self.assertEqual(movement.created_by, self.owner)
        self.assertIn(str(order_id), movement.reason)

    def test_cannot_deliver_more_than_in_stock(self):
        """Клиенту нельзя выдать то, чего на складе нет."""
        self.product.quantity = Decimal('2')
        self.product.save(update_fields=['quantity'])
        order_id = self.create_order(quantity='5').json()['id']

        resp = self.deliver(order_id)
        self.assertEqual(resp.status_code, 400, resp.content[:200])

        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('2.000'), 'остаток не должен меняться')
        self.assertEqual(self.product.reserved_for_orders, Decimal('5.000'),
                         'резерв возвращён — заказ всё ещё ждёт товар')
        order = Order.objects.get(pk=order_id)
        self.assertNotEqual(order.status, Order.Status.DELIVERED)
        self.assertFalse(StockMovement.objects.filter(
            product=self.product, movement_type=StockMovement.MovementType.OUTGOING).exists())

    def test_second_delivery_does_not_write_off_twice(self):
        order_id = self.create_order().json()['id']
        self.assertEqual(self.deliver(order_id).status_code, 200)
        self.assertEqual(self.deliver(order_id).status_code, 400)

        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('7.000'), 'списание ровно одно')
        self.assertEqual(StockMovement.objects.filter(
            product=self.product, movement_type=StockMovement.MovementType.OUTGOING).count(), 1)

    def test_custom_product_order_delivers_without_stock_movement(self):
        """У заказа «по описанию» каталожной позиции нет — списывать нечего."""
        resp = self.api.post(ORDERS, {
            'client': self.client_obj.id, 'quantity': '1', 'unit': 'dona',
            'custom_product_name': 'По эскизу', 'deadline': self.deadline(),
        }, format='json')
        order_id = resp.json()['id']
        self.assertEqual(self.deliver(order_id).status_code, 200)
        self.assertFalse(StockMovement.objects.filter(
            movement_type=StockMovement.MovementType.OUTGOING).exists())
