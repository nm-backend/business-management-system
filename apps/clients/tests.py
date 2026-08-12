"""
Unit-тесты для приложения clients: свойства/методы модели Client.
"""
import datetime
from decimal import Decimal

from django.test import TestCase

from apps.clients.models import Client, Payment
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


class PaymentAtomicityTests(TestCase):
    """
    Полный аудит: PaymentViewSet.perform_create создавал Payment (serializer.save)
    ДО проверки переплаты (apply_payment_amount). При ошибке — переплата или
    оплата отменённого заказа — клиент получал 400, но Payment оставался в базе:
    «сирота», деньги записаны, а долг и paid_amount не изменились.
    """

    def setUp(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.accounts.models import User
        from apps.companies.models import Company
        from rest_framework.test import APIClient

        self.company = Company.objects.create(name='AtomCo')
        self.owner = User.objects.create_user(
            username='atm_owner', password='p', role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.order = Order.objects.create(
            company=self.company, client=self.client_obj,
            custom_product_name='Столешница', quantity=Decimal('1'), unit='sht',
            deadline=timezone.now() + timedelta(days=10),
            total_amount=Decimal('100'), status=Order.Status.DELIVERED,
        )

    def _pay(self, amount):
        return self.api.post('/api/v1/clients/payments/', {
            'client': self.client_obj.id, 'order': self.order.id,
            'amount': amount, 'payment_method': 'cash',
            'payment_date': '2026-08-03T12:00:00Z',
        }, format='json')

    def test_overpayment_leaves_no_orphan_payment(self):
        resp = self._pay('150')
        self.assertEqual(resp.status_code, 400, resp.content[:300])
        self.assertEqual(Payment.objects.filter(order=self.order).count(), 0,
                         'СИРОТА: Payment остался в базе после 400')
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal('0'))

    def test_payment_for_cancelled_order_leaves_no_orphan(self):
        self.order.status = Order.Status.CANCELLED
        self.order.save(update_fields=['status'])
        resp = self._pay('50')
        self.assertEqual(resp.status_code, 400, resp.content[:300])
        self.assertEqual(Payment.objects.filter(order=self.order).count(), 0,
                         'СИРОТА: Payment остался в базе после 400')
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal('0'))


class ClientPhoneApiValidationTests(TestCase):
    """
    validate_phone работал только в админке: DRF не подхватывает field-валидаторы
    с модели, и через API телефон «привет» сохранялся без ошибок.
    """

    def setUp(self):
        from apps.accounts.models import User
        from apps.companies.models import Company
        from rest_framework.test import APIClient

        self.company = Company.objects.create(name='PhCo')
        self.owner = User.objects.create_user(
            username='ph_owner', password='p', role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_create_with_invalid_phone_rejected(self):
        resp = self.api.post('/api/v1/clients/clients/', {
            'name': 'Новый', 'phone': 'не телефон',
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.content[:300])
        self.assertIn('phone', resp.json())

    def test_patch_with_invalid_phone_rejected(self):
        resp = self.api.patch(f'/api/v1/clients/clients/{self.client_obj.id}/', {
            'phone': 'abc',
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.content[:300])

    def test_valid_phone_accepted(self):
        resp = self.api.post('/api/v1/clients/clients/', {
            'name': 'Звонкий', 'phone': '+996 (555) 12-34-56',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:300])

    def test_blank_phone_still_allowed(self):
        resp = self.api.patch(f'/api/v1/clients/clients/{self.client_obj.id}/', {
            'phone': '',
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.content[:300])
