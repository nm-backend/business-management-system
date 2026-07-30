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

class ApplyPaymentAmountTests(TestCase):
    """Order.apply_payment_amount() — защита от переплаты."""

    def setUp(self):
        self.client_model = Client.objects.create(name='TestClient')
        self.order = Order.objects.create(
            client=self.client_model,
            quantity=Decimal('1'),
            unit='sht',
            total_amount=Decimal('1000'),
        )

    def test_normal_payment_succeeds(self):
        """Оплата в пределах долга проходит."""
        self.order.apply_payment_amount(Decimal('400'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal('400'))
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PARTIAL)

    def test_exact_full_payment_succeeds(self):
        """Оплата ровно суммы долга проходит и статус становится PAID."""
        self.order.apply_payment_amount(Decimal('1000'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal('1000'))
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)

    def test_overpayment_raises_validation_error(self):
        """
        Симуляция DevTools-атаки: сумма больше остатка долга.
        Должен выбросить ValidationError, paid_amount не меняется.
        """
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.order.apply_payment_amount(Decimal('1500'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal('0'))

    def test_partial_payment_then_overpayment_raises(self):
        """
        После частичной оплаты (400) пытаемся внести ещё 700 при долге 600.
        Повторная DevTools-атака должна блокироваться.
        """
        self.order.apply_payment_amount(Decimal('400'))
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.order.apply_payment_amount(Decimal('700'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal('400'))
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PARTIAL)


class PaymentAPIDevToolsAttackTests(TestCase):
    """
    Симуляция атаки через DevTools: фронтенд имеет max="{debt}",
    но злоумышленник убирает этот атрибут и шлёт сумму больше долга.
    Сервер должен вернуть 400.
    """

    def setUp(self):
        from rest_framework.test import APIClient
        from apps.companies.models import Company
        from apps.accounts.models import User
        from apps.warehouse.models import FinishedProduct

        self.company = Company.objects.create(name='TestCo')
        self.owner = User.objects.create_user(
            username='own', password='pw', role=User.Role.OWNER, company=self.company)
        self.client_model = Client.objects.create(name='Client', company=self.company)
        self.product = FinishedProduct.objects.create(name='Prod', company=self.company)
        self.order = Order.objects.create(
            client=self.client_model,
            product=self.product,
            quantity=Decimal('1'),
            unit='sht',
            total_amount=Decimal('500'),
            company=self.company,
        )
        self.api = APIClient()
        self.api.force_authenticate(user=self.owner)

    def test_normal_payment_via_api_returns_201(self):
        """Обычная оплата в пределах долга — 201."""
        resp = self.api.post('/api/v1/clients/payments/', {
            'client': self.client_model.id,
            'order': self.order.id,
            'amount': '300',
            'payment_method': 'cash',
            'payment_date': '2026-07-27T12:00:00Z',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_overpayment_via_api_returns_400(self):
        """
        DevTools-атака: amount=999 при долге 500 → 400 ошибка.
        """
        resp = self.api.post('/api/v1/clients/payments/', {
            'client': self.client_model.id,
            'order': self.order.id,
            'amount': '999',
            'payment_method': 'cash',
            'payment_date': '2026-07-27T12:00:00Z',
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('больше долга', str(resp.data))

    def test_overpayment_after_partial_via_api_returns_400(self):
        """
        Частично оплатили 200, пытаемся доплатить 400 при долге 300 → 400.
        """
        self.api.post('/api/v1/clients/payments/', {
            'client': self.client_model.id,
            'order': self.order.id,
            'amount': '200',
            'payment_method': 'cash',
            'payment_date': '2026-07-27T12:00:00Z',
        }, format='json')
        resp = self.api.post('/api/v1/clients/payments/', {
            'client': self.client_model.id,
            'order': self.order.id,
            'amount': '400',
            'payment_method': 'cash',
            'payment_date': '2026-07-27T12:00:00Z',
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_cancel_paid_order_returns_400(self):
        """Отмена оплаченного заказа — 400."""
        self.api.post('/api/v1/clients/payments/', {
            'client': self.client_model.id,
            'order': self.order.id,
            'amount': '500',
            'payment_method': 'cash',
            'payment_date': '2026-07-27T12:00:00Z',
        }, format='json')
        resp = self.api.post(f'/api/v1/orders/orders/{self.order.id}/cancel/', format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('оплата', str(resp.data))

    def test_cancel_unpaid_order_succeeds(self):
        """Отмена неоплаченного заказа — 200."""
        resp = self.api.post(f'/api/v1/orders/orders/{self.order.id}/cancel/', format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
