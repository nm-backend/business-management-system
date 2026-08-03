"""
Unit-тесты для приложения clients: свойства/методы модели Client.
"""
import datetime
from decimal import Decimal

from django.test import TestCase

from apps.clients.models import Client
from apps.orders.models import Order


class ClientPropertyTests(TestCase):
    def test_str_with_and_without_phone(self):
        self.assertEqual(str(Client(name='Acme', phone='123')), 'Acme (123)')
        self.assertEqual(str(Client(name='Acme', phone='')), 'Acme')

    def test_has_debt(self):
        self.assertTrue(Client(debt=Decimal('10')).has_debt)
        self.assertFalse(Client(debt=Decimal('0')).has_debt)

    def test_has_active_orders_true_and_false(self):
        client = Client.objects.create(name='C')
        self.assertFalse(client.has_active_orders)
        Order.objects.create(
            client=client,
            quantity=Decimal('1'),
            unit='sht',
            deadline=datetime.date(2024, 1, 1),
            status='in_progress',
        )
        self.assertTrue(client.has_active_orders)


class ClientAutoArchiveTests(TestCase):
    def test_auto_archive_when_no_active_orders_and_no_debt(self):
        client = Client.objects.create(name='Done', debt=Decimal('0'))
        client.auto_archive()
        client.refresh_from_db()
        self.assertTrue(client.is_archived)
        self.assertFalse(client.is_active)

    def test_no_archive_when_debt_present(self):
        client = Client.objects.create(name='Owing', debt=Decimal('50'))
        client.auto_archive()
        client.refresh_from_db()
        self.assertFalse(client.is_archived)

    def test_no_archive_when_active_orders_exist(self):
        client = Client.objects.create(name='Busy', debt=Decimal('0'))
        Order.objects.create(
            client=client,
            quantity=Decimal('1'),
            unit='sht',
            deadline=datetime.date(2024, 1, 1),
            status='new',
        )
        client.auto_archive()
        client.refresh_from_db()
        self.assertFalse(client.is_archived)


class ClientRecalculateFinancialsTests(TestCase):
    def test_recalculate_with_no_orders_resets_to_zero(self):
        client = Client.objects.create(
            name='Empty', total_orders_amount=Decimal('99'), total_paid=Decimal('99')
        )
        client.recalculate_financials()
        client.refresh_from_db()
        self.assertEqual(client.total_orders_amount, 0)
        self.assertEqual(client.total_paid, 0)
        self.assertEqual(client.debt, 0)

    def test_payment_on_cancelled_order_does_not_offset_other_debt(self):
        import datetime
        from django.utils import timezone
        from apps.clients.models import Payment

        client = Client.objects.create(name='Mixed')
        Order.objects.create(
            client=client, quantity=Decimal('1'), unit='sht',
            deadline=datetime.date(2024, 1, 1), total_amount=Decimal('100'), status='new',
        )
        cancelled = Order.objects.create(
            client=client, quantity=Decimal('1'), unit='sht',
            deadline=datetime.date(2024, 1, 1), total_amount=Decimal('50'), status='cancelled',
        )
        # Оплата 50 была сделана по отменённому заказу.
        Payment.objects.create(
            client=client, order=cancelled, amount=Decimal('50'), payment_date=timezone.now(),
        )
        client.recalculate_financials()
        client.refresh_from_db()
        # Долг = 100 (активный заказ), оплата отменённого заказа его не гасит.
        self.assertEqual(client.total_orders_amount, Decimal('100'))
        self.assertEqual(client.total_paid, Decimal('0'))
        self.assertEqual(client.debt, Decimal('100'))


class ClientArchiveAfterPaymentTests(TestCase):
    """
    Замечание тестировщика (баг 19): клиент не уходил в архив после полной
    оплаты. При оплате через PaymentViewSet вызывается client.auto_archive():
    если активных заказов и долга нет — клиент уходит в архив.
    """

    def setUp(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.accounts.models import User
        from apps.companies.models import Company
        from rest_framework.test import APIClient

        self.company = Company.objects.create(name='ArhCo')
        self.owner = User.objects.create_user(
            username='arh_owner', password='p', role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(
            company=self.company, name='Готовый клиент')
        self.client_api = APIClient()
        self.client_api.force_authenticate(user=self.owner)

    def _paid_delivered_order(self):
        from datetime import timedelta

        from django.utils import timezone

        order = Order.objects.create(
            company=self.company, client=self.client_obj,
            custom_product_name='Столешница', quantity=Decimal('1'), unit='sht',
            deadline=timezone.now() + timedelta(days=10),
            total_amount=Decimal('100'), status=Order.Status.DELIVERED,
        )
        return order

    def test_payment_archives_client_with_no_active_orders_and_no_debt(self):
        order = self._paid_delivered_order()
        resp = self.client_api.post('/api/v1/clients/payments/', {
            'client': self.client_obj.id, 'order': order.id,
            'amount': '100', 'payment_method': 'cash',
            'payment_date': '2026-08-03T12:00:00Z',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        self.client_obj.refresh_from_db()
        self.assertTrue(self.client_obj.is_archived)
        self.assertFalse(self.client_obj.is_active)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)

    def test_payment_does_not_archive_client_with_active_order(self):
        from datetime import timedelta

        from django.utils import timezone

        order = self._paid_delivered_order()
        Order.objects.create(
            company=self.company, client=self.client_obj,
            custom_product_name='Ещё одна', quantity=Decimal('1'), unit='sht',
            deadline=timezone.now() + timedelta(days=10),
            total_amount=Decimal('200'), status=Order.Status.IN_PROGRESS,
        )
        resp = self.client_api.post('/api/v1/clients/payments/', {
            'client': self.client_obj.id, 'order': order.id,
            'amount': '100', 'payment_method': 'cash',
            'payment_date': '2026-08-03T12:00:00Z',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        self.client_obj.refresh_from_db()
        self.assertFalse(self.client_obj.is_archived)
