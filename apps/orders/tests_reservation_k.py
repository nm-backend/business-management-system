"""
Резервирование склада под заказы (reserved_for_orders).

Заказ на товар из каталога резервирует количество на складе готовой продукции:
- создание заказа -> reserved_for_orders += quantity
- отмена / удаление / выдача -> reserved_for_orders -= quantity (резерв возвращается)
- смена товара или количества -> резерв пересчитывается

Раньше поле never заполнялось (всегда 0), несмотря на available_quantity =
quantity - reserved_for_orders. Эти тесты фиксируют полный жизненный цикл резерва.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct


class OrderReservationAPITests(TestCase):
    """Жизненный цикл резерва через API: create/update/cancel/deliver/destroy."""

    def setUp(self):
        self.company = Company.objects.create(name='ResCo', is_active=True)
        self.owner = User.objects.create_user(username='res_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.cli = Client.objects.create(company=self.company, name='РезКлиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Стул', quantity=Decimal('10'), unit='dona')
        self.other = FinishedProduct.objects.create(
            company=self.company, name='Стол', quantity=Decimal('20'), unit='dona')

    def api(self, user=None):
        c = APIClient()
        c.force_authenticate(user or self.owner)
        return c

    def _create_order(self, product, quantity, **kwargs):
        resp = self.api().post('/api/v1/orders/orders/', {
            'client': self.cli.id,
            'product': product.id,
            'quantity': str(quantity),
            'unit': 'dona',
            **kwargs,
        }, format='json')
        self.assertIn(resp.status_code, (200, 201), resp.content[:300])
        return resp.json()['id']

    def test_create_reserves_quantity(self):
        """Создание заказа резервирует количество товара."""
        order_id = self._create_order(self.product, '3')
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('3'))
        self.assertEqual(self.product.available_quantity, Decimal('7'))

        order = Order.objects.get(pk=order_id)
        self.assertEqual(order.status, Order.Status.NEW)

    def test_create_without_product_does_not_reserve(self):
        """Заказ на custom_product_name (без товара каталога) ничего не резервирует."""
        resp = self.api().post('/api/v1/orders/orders/', {
            'client': self.cli.id,
            'custom_product_name': 'Изделие на заказ',
            'quantity': '2',
            'unit': 'dona',
        }, format='json')
        self.assertIn(resp.status_code, (200, 201), resp.content[:300])
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('0'))

    def test_multiple_orders_reserve_sum(self):
        """Два заказа на один товар резервируют суммарное количество."""
        self._create_order(self.product, '2')
        self._create_order(self.product, '4')
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('6'))
        self.assertEqual(self.product.available_quantity, Decimal('4'))

    def test_cancel_releases_reservation(self):
        """Отмена заказа возвращает резерв на склад."""
        self._create_order(self.product, '5')
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('5'))

        order_id = self.product.orders.first().id
        resp = self.api().post(f'/api/v1/orders/orders/{order_id}/cancel/')
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('0'))
        self.assertEqual(self.product.available_quantity, Decimal('10'))

    def test_deliver_releases_reservation(self):
        """Выдача заказа снимает резерв (товар ушёл клиенту)."""
        self._create_order(self.product, '4')
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('4'))

        order_id = self.product.orders.first().id
        resp = self.api().post(f'/api/v1/orders/orders/{order_id}/deliver/')
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('0'))

    def test_destroy_releases_reservation(self):
        """Удаление заказа (архивация с отменой) возвращает резерв."""
        self._create_order(self.product, '3')
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('3'))

        order_id = self.product.orders.first().id
        resp = self.api().delete(f'/api/v1/orders/orders/{order_id}/')
        self.assertIn(resp.status_code, (200, 204), resp.content[:300])
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('0'))

    def test_update_quantity_resyncs_reservation(self):
        """Смена количества заказа пересчитывает резерв."""
        order_id = self._create_order(self.product, '2')
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('2'))

        resp = self.api().patch(f'/api/v1/orders/orders/{order_id}/',
                                {'quantity': '7'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('7'))

    def test_update_product_moves_reservation(self):
        """Смена товара переносит резерв с одного товара на другой."""
        order_id = self._create_order(self.product, '2')
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('2'))

        resp = self.api().patch(f'/api/v1/orders/orders/{order_id}/',
                                {'product': self.other.id}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self.product.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('0'))
        self.assertEqual(self.other.reserved_for_orders, Decimal('2'))

    def test_update_delivered_order_does_not_reserve_again(self):
        """
        Выданный заказ нельзя редактировать (БАГ 6) — 400, резерв не воскресает.
        """
        order_id = self._create_order(self.product, '2')
        self.api().post(f'/api/v1/orders/orders/{order_id}/deliver/')
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('0'))

        resp = self.api().patch(f'/api/v1/orders/orders/{order_id}/',
                                {'quantity': '5'}, format='json')
        self.assertEqual(resp.status_code, 400, resp.content[:300])
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('0'),
                         'выданный заказ не должен резервировать при правке')

    def test_update_cancelled_order_does_not_reserve_again(self):
        """Правка отменённого заказа тоже не воскрешает резерв."""
        order_id = self._create_order(self.product, '2')
        self.api().post(f'/api/v1/orders/orders/{order_id}/cancel/')
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('0'))

        resp = self.api().patch(f'/api/v1/orders/orders/{order_id}/',
                                {'quantity': '5'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('0'))

    def test_non_terminal_transition_keeps_reservation(self):
        """Переходы Kanban (например, в ready) резерв не трогают."""
        order_id = self._create_order(self.product, '3')
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('3'))

        # new -> ready напрямую запрещён конечным автоматом; берём разрешённый путь
        resp = self.api().patch(f'/api/v1/orders/orders/{order_id}/transition/',
                                {'status': Order.Status.AWAITING_MATERIAL}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('3'),
                         'не-терминальный переход не должен менять резерв')

    def test_worker_cannot_create_order(self):
        """Создание заказа — прерогатива owner/admin: worker получает 403."""
        worker = User.objects.create_user(username='res_worker', password='p',
                                          role=User.Role.WORKER, company=self.company)
        resp = self.api(worker).post('/api/v1/orders/orders/', {
            'client': self.cli.id, 'product': self.product.id,
            'quantity': '1', 'unit': 'dona',
        }, format='json')
        self.assertEqual(resp.status_code, 403)


class OrderReservationModelTests(TestCase):
    """Unit-тесты методов модели reserve_product/release_product."""

    def setUp(self):
        self.company = Company.objects.create(name='ModelCo', is_active=True)
        self.cli = Client.objects.create(company=self.company, name='М')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Модель', quantity=Decimal('8'), unit='dona')
        self.order = Order.objects.create(
            company=self.company, client=self.cli, product=self.product,
            quantity=Decimal('3'), unit='dona',
            deadline=datetime.datetime(2026, 12, 1, tzinfo=datetime.timezone.utc))

    def test_release_never_goes_below_zero(self):
        """Резерв не уходит в минус даже без предварительного резервирования."""
        self.order.release_product()
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('0'))

    def test_release_with_explicit_args(self):
        """release_product(product_id, quantity) снимает резерв по явным значениям."""
        self.order.reserve_product()
        self.order.release_product(product_id=self.product.id, quantity=Decimal('2'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_for_orders, Decimal('1'))
