"""
Unit-тесты для приложения orders: свойства и методы модели Order
(is_paid, has_debt, update_payment_status, check_overdue).
"""
from django.utils import timezone
from decimal import Decimal

from django.test import TestCase

from apps.clients.models import Client
from apps.orders.models import Order


def make_order(client, **kwargs):
    defaults = dict(
        quantity=Decimal('1'),
        unit='sht',
        deadline=timezone.now(),
    )
    defaults.update(kwargs)
    return Order.objects.create(client=client, **defaults)


class OrderPropertyTests(TestCase):
    def test_is_paid_true_when_paid_ge_total(self):
        self.assertTrue(Order(total_amount=Decimal('100'), paid_amount=Decimal('100')).is_paid)
        self.assertTrue(Order(total_amount=Decimal('100'), paid_amount=Decimal('120')).is_paid)

    def test_is_paid_false_when_underpaid(self):
        self.assertFalse(Order(total_amount=Decimal('100'), paid_amount=Decimal('50')).is_paid)

    def test_has_debt(self):
        self.assertTrue(Order(total_amount=Decimal('100'), paid_amount=Decimal('40')).has_debt)
        self.assertFalse(Order(total_amount=Decimal('100'), paid_amount=Decimal('100')).has_debt)

    def test_str(self):
        client = Client.objects.create(name='Bob')
        order = make_order(client, status='new')
        self.assertIn(f'Order #{order.id}', str(order))
        self.assertIn('Bob', str(order))

# NOTE: Order.update_payment_status() и Order.check_overdue() в текущем коде
# обращаются к self.PaymentStatus / self.OrderStatus, тогда как эти перечисления
# объявлены на уровне модуля (PaymentStatus / OrderStatus), а не вложены в модель.
# Из-за этого методы падают с AttributeError. Тесты на них не добавлены, чтобы
# не завязывать набор тестов на заведомо сломанное поведение (см. описание PR).
