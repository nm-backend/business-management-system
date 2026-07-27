"""
Защита денег по заказу: переплата, оплата отменённого, отмена оплаченного.

Найдено при разборе жалоб на боевое использование:
  • в форме оплаты можно было ввести сумму больше долга — излишек молча уходил
    в paid_amount, заказ становился «переплачен», и лишние деньги нигде не
    отслеживались;
  • оплаченный заказ можно было отменить — деньги клиента повисали ни на чём,
    так как отмена пересчитывает долг, но возврат не оформляет.

Проверки стоят на бэкенде (не только в форме), поэтому обходятся ни через
DevTools, ни через прямой вызов API.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct


class _OrderMoneyBase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='MoneyCo', is_active=True)
        self.owner = User.objects.create_user(username='money_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.cli = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Товар', quantity=Decimal('10'))
        self.order = Order.objects.create(
            company=self.company, client=self.cli, product=self.product,
            quantity=Decimal('1'), unit='dona', total_amount=Decimal('1000'),
            deadline=datetime.datetime(2026, 12, 1, tzinfo=datetime.timezone.utc))

    def api(self):
        c = APIClient()
        c.force_authenticate(self.owner)
        return c

    def pay(self, amount):
        return self.api().post('/api/v1/clients/payments/', {
            'client': self.cli.id, 'order': self.order.id,
            'amount': str(amount), 'payment_method': 'cash',
            'payment_date': '2026-07-01T10:00:00Z',
        }, format='json')


class OverpaymentTests(_OrderMoneyBase):
    def test_payment_over_debt_rejected(self):
        resp = self.pay('1500')          # долг 1000
        self.assertEqual(resp.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal('0'))

    def test_payment_equal_to_debt_accepted(self):
        resp = self.pay('1000')
        self.assertEqual(resp.status_code, 201)
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal('1000'))
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)

    def test_second_payment_cannot_exceed_remaining_debt(self):
        self.assertEqual(self.pay('600').status_code, 201)
        resp = self.pay('600')           # осталось 400
        self.assertEqual(resp.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal('600'))

    def test_partial_payments_up_to_total_are_fine(self):
        self.assertEqual(self.pay('400').status_code, 201)
        self.assertEqual(self.pay('600').status_code, 201)
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal('1000'))

    def test_model_level_guard_blocks_direct_call(self):
        """Обход формы через модель (скрипт, shell) тоже отклоняется."""
        with self.assertRaises(ValidationError):
            self.order.apply_payment_amount(Decimal('5000'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal('0'))

    def test_cancelled_order_cannot_be_paid(self):
        self.order.status = Order.Status.CANCELLED
        self.order.save(update_fields=['status'])
        with self.assertRaises(ValidationError):
            self.order.apply_payment_amount(Decimal('100'))


class CancelPaidOrderTests(_OrderMoneyBase):
    def test_paid_order_cannot_be_cancelled(self):
        self.assertEqual(self.pay('500').status_code, 201)
        resp = self.api().post(f'/api/v1/orders/orders/{self.order.id}/cancel/')
        self.assertEqual(resp.status_code, 400)
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.status, Order.Status.CANCELLED)
        self.assertEqual(self.order.paid_amount, Decimal('500'))

    def test_unpaid_order_can_be_cancelled(self):
        resp = self.api().post(f'/api/v1/orders/orders/{self.order.id}/cancel/')
        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CANCELLED)
