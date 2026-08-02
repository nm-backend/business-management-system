"""
Отмена уже выданного заказа должна возвращать товар на склад.

Пока выдача склад не трогала, отмена после выдачи была безобидна. С момента,
как выдача начала списывать готовую продукцию, отмена без обратного прихода
означает потерю товара на бумаге: физически клиент его вернул, а в системе
остаток остался уменьшенным и в журнале нет ни одной записи о возврате.
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


class CancelAfterDeliveryTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='CancelCo', is_active=True)
        self.owner = User.objects.create_user(username='cnl_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('10'), unit='dona')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.order_id = self.api.post(ORDERS, {
            'client': self.client_obj.id, 'product': self.product.id,
            'quantity': '3', 'unit': 'dona', 'total_amount': '1000',
            'deadline': (timezone.now() + datetime.timedelta(days=5)).isoformat(),
        }, format='json').json()['id']

    def test_cancel_after_delivery_returns_stock(self):
        self.assertEqual(self.api.post(f'{ORDERS}{self.order_id}/deliver/').status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('7.000'))

        self.assertEqual(self.api.post(f'{ORDERS}{self.order_id}/cancel/').status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('10.000'),
                         'товар вернулся от клиента — остаток обязан восстановиться')
        self.assertTrue(
            StockMovement.objects.filter(
                product=self.product,
                movement_type=StockMovement.MovementType.INCOMING,
                reason__icontains=str(self.order_id)).exists(),
            'возврат обязан оставить след в журнале')

    def test_cancel_before_delivery_does_not_inflate_stock(self):
        """Невыданный заказ ничего не списывал — приходовать нечего."""
        self.assertEqual(self.api.post(f'{ORDERS}{self.order_id}/cancel/').status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('10.000'))
        self.assertFalse(StockMovement.objects.filter(
            product=self.product,
            movement_type=StockMovement.MovementType.INCOMING).exists())

    def test_cancel_twice_returns_stock_once(self):
        self.api.post(f'{ORDERS}{self.order_id}/deliver/')
        self.assertEqual(self.api.post(f'{ORDERS}{self.order_id}/cancel/').status_code, 200)
        self.api.post(f'{ORDERS}{self.order_id}/cancel/')
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('10.000'), 'приход ровно один')


class DestroyBypassTests(TestCase):
    """
    Удаление заказа шло мимо правил отмены.

    perform_destroy переводит заказ в «отменён» и архивирует — то есть делает
    то же, что cancel, но без его защит: не проверяет оплату и не возвращает
    товар, списанный при выдаче. Значит удалением можно было обойти запрет
    «оплаченный заказ отменить нельзя» и потерять товар.
    """
    def setUp(self):
        self.company = Company.objects.create(name='DestroyCo', is_active=True)
        self.owner = User.objects.create_user(username='dst_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('10'), unit='dona')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.order_id = self.api.post(ORDERS, {
            'client': self.client_obj.id, 'product': self.product.id,
            'quantity': '3', 'unit': 'dona', 'total_amount': '1000',
            'deadline': (timezone.now() + datetime.timedelta(days=5)).isoformat(),
        }, format='json').json()['id']

    def test_paid_order_cannot_be_deleted(self):
        """Тот же запрет, что и у отмены: иначе оплата повисает ни на чём."""
        self.api.post('/api/v1/clients/payments/', {
            'client': self.client_obj.id, 'order': self.order_id, 'amount': '500',
            'payment_method': 'cash', 'payment_date': timezone.now().isoformat(),
        }, format='json')
        resp = self.api.delete(f'{ORDERS}{self.order_id}/')
        self.assertEqual(resp.status_code, 400, resp.content[:200])
        self.assertNotEqual(Order.objects.get(pk=self.order_id).status,
                            Order.Status.CANCELLED)

    def test_delete_after_delivery_returns_stock(self):
        self.api.post(f'{ORDERS}{self.order_id}/deliver/')
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('7.000'))

        self.assertEqual(self.api.delete(f'{ORDERS}{self.order_id}/').status_code, 204)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('10.000'),
                         'удаление выданного заказа обязано вернуть товар')
