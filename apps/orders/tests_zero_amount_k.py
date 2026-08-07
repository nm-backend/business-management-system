"""
Заказ с нулевой суммой: payment_status не врёт, долга нет.

Воспроизведено до правки:
- Создание заказа с total_amount=0 оставляло payment_status='unpaid'
  (дефолт модели, синхронизации при создании не было) при is_paid=True —
  «не оплачено» при нулевом долге: ложная тревога в канбане и в фильтре
  неоплаченных заказов.
- update_payment_status проверял paid_amount <= 0 раньше is_paid: заказ
  с нулевой суммой всегда «не оплачен», хотя долг по нему ноль.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct

ORDERS = '/api/v1/orders/orders/'


class ZeroAmountOrderTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='ZeroA', is_active=True)
        self.owner = User.objects.create_user(username='zero_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.product = FinishedProduct.objects.create(company=self.company, name='Столешница',
                                                      unit='dona', quantity=10)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        from apps.clients.models import Client
        self.client_model = Client.objects.create(company=self.company, name='Клиент')

    def _order(self, total_amount):
        resp = self.api.post(ORDERS, {
            'client': self.client_model.id, 'product': self.product.id,
            'quantity': '1', 'unit': 'dona', 'total_amount': total_amount,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        return Order.objects.get(pk=resp.json()['id'])

    def test_zero_total_order_is_paid(self):
        order = self._order('0')
        self.assertTrue(order.is_paid)
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID,
                         'нулевая сумма = нулевой долг, а не «не оплачено»')

    def test_positive_total_order_is_unpaid(self):
        order = self._order('100000')
        self.assertFalse(order.is_paid)
        self.assertEqual(order.payment_status, Order.PaymentStatus.UNPAID)

    def test_payment_flow_still_works(self):
        order = self._order('1000')
        order.apply_payment_amount(Decimal('400'))
        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PaymentStatus.PARTIAL)
        order.apply_payment_amount(Decimal('600'))
        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)

    def test_zero_total_order_delivers_without_unpaid_alarm(self):
        """Выдача бесплатного заказа не порождает ложной тревоги о долге."""
        order = self._order('0')
        resp = self.api.post(f'{ORDERS}{order.id}/deliver/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.DELIVERED)
        self.assertEqual(order.client.debt, Decimal('0'))
