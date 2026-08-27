"""
Глубокая ревизия: атомарность создания, блокировка строки при правке,
пересчёт старого клиента при смене клиента, transition под блокировкой.

Сценарии:
- сбой после создания заказа (уведомление) откатывает заказ и резерв целиком
- PATCH client переносит суммы: старый клиент пересчитывается сразу
- transition отменённого заказа отклоняется (не «воскресает»)
- смена товара под блокировкой корректно переносит резерв (регрессия)
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct


class OrderDeepFixTests(TestCase):
    """Атомарность create и пересчёт клиентов при смене client."""

    def setUp(self):
        self.company = Company.objects.create(name='DeepCo', is_active=True)
        self.owner = User.objects.create_user(username='deep_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.client_a = Client.objects.create(company=self.company, name='Клиент А')
        self.client_b = Client.objects.create(company=self.company, name='Клиент Б')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Стул', quantity=Decimal('10'), unit='dona')

    def api(self, user=None):
        c = APIClient()
        c.force_authenticate(user or self.owner)
        return c

    def _create_order(self, client, **kwargs):
        resp = self.api().post('/api/v1/orders/orders/', {
            'client': client.id,
            'product': self.product.id,
            'quantity': '2',
            'unit': 'dona',
            'total_amount': '100',
            **kwargs,
        }, format='json')
        self.assertIn(resp.status_code, (200, 201), resp.content[:300])
        return resp.json()['id']

    def test_create_failure_rolls_back_order_and_reserve(self):
        """Сбой после сохранения (уведомление) не оставляет заказ без резерва."""
        from apps.orders.views import notify_staff

        client = APIClient(raise_request_exception=False)
        client.force_authenticate(self.owner)
        with patch('apps.orders.views.notify_staff', side_effect=RuntimeError('boom')):
            resp = client.post('/api/v1/orders/orders/', {
                'client': self.client_a.id,
                'product': self.product.id,
                'quantity': '2',
                'unit': 'dona',
                'total_amount': '100',
            }, format='json')
        self.assertEqual(resp.status_code, 500, resp.content[:200])
        self.assertEqual(Order.objects.count(), 0, 'заказ откатывается целиком')
        self.product.refresh_from_db()
        self.assertEqual(self.product.required_for_orders, Decimal('0'),
                         'резерв не остаётся после отката')

    def test_update_client_recalculates_old_client(self):
        """Смена клиента сразу пересчитывает финансовые суммы старого."""
        order_id = self._create_order(self.client_a)
        self.client_a.refresh_from_db()
        self.assertGreater(self.client_a.total_orders_amount, 0)

        resp = self.api().patch(f'/api/v1/orders/orders/{order_id}/',
                                {'client': self.client_b.id}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content[:300])

        self.client_a.refresh_from_db()
        self.client_b.refresh_from_db()
        self.assertEqual(self.client_a.total_orders_amount, Decimal('0'),
                         'ушедший заказ снят со старого клиента сразу')
        self.assertGreater(self.client_b.total_orders_amount, 0)

    def test_transition_cancelled_order_is_rejected(self):
        """Отменённый заказ не «воскресает» через transition."""
        order_id = self._create_order(self.client_a)
        self.assertEqual(self.api().post(f'/api/v1/orders/orders/{order_id}/cancel/').status_code, 200)

        resp = self.api().patch(f'/api/v1/orders/orders/{order_id}/transition/',
                                {'status': Order.Status.AWAITING_MATERIAL}, format='json')
        self.assertEqual(resp.status_code, 400)
        order = Order.objects.get(pk=order_id)
        self.assertEqual(order.status, Order.Status.CANCELLED)

    def test_update_changes_product_under_lock(self):
        """Смена товара при правке корректно переносит резерв (регрессия)."""
        other = FinishedProduct.objects.create(
            company=self.company, name='Стол', quantity=Decimal('20'), unit='dona')
        order_id = self._create_order(self.client_a)
        self.product.refresh_from_db()
        self.assertEqual(self.product.required_for_orders, Decimal('2'))

        resp = self.api().patch(f'/api/v1/orders/orders/{order_id}/',
                                {'product': other.id}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self.product.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.product.required_for_orders, Decimal('0'))
        self.assertEqual(other.required_for_orders, Decimal('2'))

    def test_transition_parallel_status_flow(self):
        """Обычный рабочий переход Kanban продолжает работать."""
        order_id = self._create_order(self.client_a)
        resp = self.api().patch(f'/api/v1/orders/orders/{order_id}/transition/',
                                {'status': Order.Status.SENT_TO_WORKER}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        order = Order.objects.get(pk=order_id)
        self.assertEqual(order.status, Order.Status.SENT_TO_WORKER)
