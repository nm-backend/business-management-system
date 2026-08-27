"""
Расследование: выдача при параллельных резервах, правка выданного заказа,
ложное «не оплатил», смена клиента заказа.

Воспроизведено до правки:
1. Выдача заказа A падала с not_enough_stock, если на товаре висел резерв
   заказа B (даже когда партия A физически на складе). Дополнительно резерв
   СЫРЬЯ снимался дважды: в confirm_work и повторно при выдаче — резерв
   параллельного заказа «крался» вдвое.
2. PATCH количества выданного заказа проходил: склад списан на 2, заказ «на 5».
3. Клиент, оплативший авансом без привязки к заказу, при выдаче получал
   ложное уведомление «Мижоз тўлов қилмади» и не архивировался.
4. Смена клиента заказа с оплатами: Payment оставался на старом клиенте,
   долг нового считался без уже принятых денег.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.messaging.models import Notification
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct, RawMaterial

ORDERS = '/api/v1/orders/orders/'


class _Base(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='InvCo', is_active=True)
        self.owner = User.objects.create_user(username='inv_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='inv_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.client = Client.objects.create(company=self.company, name='Клиент')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.worker_api = APIClient()
        self.worker_api.force_authenticate(self.worker)

    def deadline(self):
        return (timezone.now() + datetime.timedelta(days=5)).isoformat()

    def _order(self, product, quantity, total=None):
        resp = self.api.post(ORDERS, {
            'client': self.client.id, 'product': product.id, 'quantity': str(quantity),
            'unit': 'dona', 'total_amount': str(total or quantity * 1000),
            'deadline': self.deadline(),
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.json()['id']

    def _produce_and_confirm(self, order_id, product, quantity):
        resp = self.api.post('/api/v1/production/tasks/', {
            'order': order_id, 'worker': self.worker.id,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        task_id = resp.json()['id']
        resp = self.worker_api.post(f'/api/v1/production/tasks/{task_id}/accept/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        resp = self.worker_api.post('/api/v1/production/works/', {
            'task': task_id, 'product': product.id, 'operation': 'cutting',
            'quantity': str(quantity), 'unit': 'dona',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        resp = self.api.post(f'/api/v1/production/works/{resp.json()["id"]}/confirm/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)


class ParallelReservationTests(_Base):
    """Заказ B не должен блокировать выдачу заказа A и «красть» его резервы."""

    def setUp(self):
        super().setUp()
        self.material = RawMaterial.objects.create(
            company=self.company, name='Стекло', stone_type='стекло', unit='m2',
            quantity=Decimal('100'))
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Окно', quantity=Decimal('0'), unit='dona')
        resp = self.api.post('/api/v1/warehouse/recipes/', {
            'product': self.product.id, 'name': 'R', 'is_active': True,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        resp = self.api.post('/api/v1/warehouse/recipe-items/', {
            'recipe': resp.json()['id'], 'material': self.material.id,
            'quantity_required': '1', 'unit': 'm2',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        resp = self.api.post('/api/v1/finance/labor-rates/', {
            'product': self.product.id, 'operation': 'cutting',
            'rate_per_unit': '1000', 'unit': 'dona',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_deliver_passes_despite_other_order_reservation(self):
        order_a = self._order(self.product, 5, 500000)
        order_b = self._order(self.product, 10, 1000000)
        self.material.refresh_from_db()
        self.assertEqual(self.material.required_for_orders, Decimal('15.000'))

        self._produce_and_confirm(order_a, self.product, 5)
        self.material.refresh_from_db()
        self.assertEqual(self.material.required_for_orders, Decimal('10.000'),
                         'confirm снимает резерв только своей части')

        resp = self.api.post(f'{ORDERS}{order_a}/deliver/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)

        # Резерв заказа B не тронут: confirm снял 5, выдача НЕ снимает повторно.
        self.material.refresh_from_db()
        self.assertEqual(self.material.required_for_orders, Decimal('10.000'),
                         'резерв B не должен сниматься дважды')
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('0.000'), 'выдано 5 из произведённых 5')

    def test_deliver_fails_when_physical_stock_missing(self):
        order_a = self._order(self.product, 5, 500000)
        resp = self.api.post(f'{ORDERS}{order_a}/deliver/', {}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.json().get('code'), 'not_enough_stock')


class DeliveredOrderEditTests(_Base):
    def test_patch_delivered_order_rejected(self):
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Дверь', quantity=Decimal('10'), unit='dona')
        order_id = self._order(self.product, 2)
        resp = self.api.post(f'{ORDERS}{order_id}/deliver/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)

        resp = self.api.patch(f'{ORDERS}{order_id}/', {'quantity': '5'}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        order = Order.objects.get(pk=order_id)
        self.assertEqual(order.quantity, Decimal('2'), 'количество выданного заказа неизменно')


class AdvancePaymentNotificationTests(_Base):
    def test_no_unpaid_notification_when_fully_prepaid_by_advance(self):
        """Аванс без привязки к заказу: долг 0 — уведомления быть не должно."""
        product = FinishedProduct.objects.create(
            company=self.company, name='Дверь', quantity=Decimal('5'), unit='dona')
        order_id = self._order(product, 1, 100000)
        resp = self.api.post('/api/v1/clients/payments/', {
            'client': self.client.id, 'amount': '100000',
            'payment_method': 'cash', 'payment_date': timezone.localdate().isoformat(),
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.client.refresh_from_db()
        self.assertEqual(self.client.debt, Decimal('0'))

        resp = self.api.post(f'{ORDERS}{order_id}/deliver/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(Notification.objects.filter(
            type=Notification.NotificationType.UNPAID_CLIENT,
            related_order_id=order_id,
        ).exists(), 'ложное «не оплатил» не создаётся')

    def test_unpaid_notification_still_created_when_debt_exists(self):
        product = FinishedProduct.objects.create(
            company=self.company, name='Дверь', quantity=Decimal('5'), unit='dona')
        order_id = self._order(product, 1, 100000)
        resp = self.api.post(f'{ORDERS}{order_id}/deliver/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(Notification.objects.filter(
            type=Notification.NotificationType.UNPAID_CLIENT,
            related_order_id=order_id,
        ).exists())


class OrderClientChangeTests(_Base):
    def test_change_client_with_payments_rejected(self):
        other_client = Client.objects.create(company=self.company, name='Другой клиент')
        product = FinishedProduct.objects.create(
            company=self.company, name='Дверь', quantity=Decimal('5'), unit='dona')
        order_id = self._order(product, 1, 100000)
        resp = self.api.post('/api/v1/clients/payments/', {
            'client': self.client.id, 'order': order_id, 'amount': '50000',
            'payment_method': 'cash', 'payment_date': timezone.localdate().isoformat(),
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

        resp = self.api.patch(f'{ORDERS}{order_id}/', {'client': other_client.id}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(Order.objects.get(pk=order_id).client_id, self.client.id)

    def test_change_client_without_payments_allowed(self):
        other_client = Client.objects.create(company=self.company, name='Другой клиент')
        product = FinishedProduct.objects.create(
            company=self.company, name='Дверь', quantity=Decimal('5'), unit='dona')
        order_id = self._order(product, 1, 100000)
        resp = self.api.patch(f'{ORDERS}{order_id}/', {'client': other_client.id}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(Order.objects.get(pk=order_id).client_id, other_client.id)
