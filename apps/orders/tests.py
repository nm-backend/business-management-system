"""
Unit-тесты для приложения orders: свойства и методы модели Order
(is_paid, has_debt, update_payment_status, check_overdue).
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.clients.models import Client
from apps.orders.models import Order, PaymentStatus


def make_order(client, **kwargs):
    defaults = dict(
        quantity=Decimal('1'),
        unit='sht',
        deadline=datetime.date(2024, 1, 1),
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


class OrderPaymentStatusTests(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(name='Payer')

    def test_unpaid(self):
        order = make_order(self.client_obj, total_amount=Decimal('100'), paid_amount=Decimal('0'))
        order.update_payment_status()
        order.refresh_from_db()
        self.assertEqual(order.payment_status, PaymentStatus.UNPAID)

    def test_partial(self):
        order = make_order(self.client_obj, total_amount=Decimal('100'), paid_amount=Decimal('40'))
        order.update_payment_status()
        order.refresh_from_db()
        self.assertEqual(order.payment_status, PaymentStatus.PARTIAL)

    def test_paid(self):
        order = make_order(self.client_obj, total_amount=Decimal('100'), paid_amount=Decimal('100'))
        order.update_payment_status()
        order.refresh_from_db()
        self.assertEqual(order.payment_status, PaymentStatus.PAID)


class OrderCheckOverdueTests(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(name='Late')

    def test_overdue_when_past_deadline_and_not_completed(self):
        past = timezone.now().date() - datetime.timedelta(days=5)
        order = make_order(self.client_obj, deadline=past, status='new')
        order.check_overdue()
        order.refresh_from_db()
        self.assertTrue(order.is_overdue)

    def test_not_overdue_when_completed_status(self):
        past = timezone.now().date() - datetime.timedelta(days=5)
        order = make_order(self.client_obj, deadline=past, status='delivered')
        order.check_overdue()
        order.refresh_from_db()
        self.assertFalse(order.is_overdue)

    def test_not_overdue_when_deadline_in_future(self):
        future = timezone.now().date() + datetime.timedelta(days=5)
        order = make_order(self.client_obj, deadline=future, status='new')
        order.check_overdue()
        order.refresh_from_db()
        self.assertFalse(order.is_overdue)


class OrderUpdateClientFinancialsTests(TestCase):
    def test_recomputes_client_totals_debt_and_profit(self):
        client = Client.objects.create(name='Fin')
        order1 = make_order(client, total_amount=Decimal('100'), paid_amount=Decimal('60'))
        make_order(client, total_amount=Decimal('50'), paid_amount=Decimal('50'))

        order1.update_client_financials()
        client.refresh_from_db()

        self.assertEqual(client.total_orders_amount, Decimal('150'))
        self.assertEqual(client.total_paid, Decimal('110'))
        self.assertEqual(client.debt, Decimal('40'))
        self.assertEqual(client.profit, Decimal('11.0'))
