"""
API tests for orders app.

Coverage:
- CRUD operations
- Status transitions
- assign_worker action
- update_payment action
- RBAC: owner sees financial data, admin/worker don't
"""
from decimal import Decimal
from datetime import date, timedelta
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.warehouse.models import FinishedProduct
from apps.orders.models import Order, OrderStatus, PaymentStatus


def _create_users():
    owner = User.objects.create_user(
        username='owner', password='owner123', role=User.Role.OWNER
    )
    admin = User.objects.create_user(
        username='admin', password='admin123', role=User.Role.ADMIN
    )
    worker = User.objects.create_user(
        username='worker', password='worker123', role=User.Role.WORKER
    )
    return owner, admin, worker


def _create_client_and_product():
    client = Client.objects.create(name='Test Client', phone='123456789')
    product = FinishedProduct.objects.create(
        name='Granite Slab', unit='m2', quantity=100,
        cost_price=Decimal('500'), sale_price=Decimal('1200')
    )
    return client, product


class OrderCRUDTests(TestCase):
    """Tests for basic CRUD operations on orders."""

    def setUp(self):
        self.api = APIClient()
        self.owner, self.admin, self.worker = _create_users()
        self.client_obj, self.product = _create_client_and_product()

    def _list_count(self, response):
        """Returns the number of results from a paginated list response."""
        data = response.json() if hasattr(response, 'content') else response.data
        if isinstance(data, dict) and 'results' in data:
            return len(data['results'])
        return len(data)

    def test_owner_can_create_order(self):
        self.api.force_authenticate(user=self.owner)
        response = self.api.post('/api/v1/orders/', {
            'client': self.client_obj.id,
            'product': self.product.id,
            'quantity': 10,
            'unit': 'm2',
            'deadline': '2026-12-31',
        })
        self.assertEqual(response.status_code, 201)
        self.assertIn('id', response.data)
        self.assertEqual(Order.objects.count(), 1)

    def test_owner_sees_financial_fields(self):
        self.api.force_authenticate(user=self.owner)
        order = Order.objects.create(
            client=self.client_obj, product=self.product, quantity=5, unit='m2',
            deadline='2026-12-31', total_amount=Decimal('6000'),
            paid_amount=Decimal('3000'),
        )
        response = self.api.get(f'/api/v1/orders/{order.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('total_amount', response.data)
        self.assertIn('paid_amount', response.data)

    def test_admin_does_not_see_financial_fields(self):
        self.api.force_authenticate(user=self.admin)
        order = Order.objects.create(
            client=self.client_obj, product=self.product, quantity=5, unit='m2',
            deadline='2026-12-31', total_amount=Decimal('6000'),
            paid_amount=Decimal('3000'),
        )
        response = self.api.get(f'/api/v1/orders/{order.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('total_amount', response.data)
        self.assertNotIn('paid_amount', response.data)

    def test_worker_does_not_see_financial_fields(self):
        self.api.force_authenticate(user=self.worker)
        order = Order.objects.create(
            client=self.client_obj, product=self.product, quantity=5, unit='m2',
            deadline='2026-12-31', total_amount=Decimal('6000'),
            paid_amount=Decimal('3000'),
        )
        response = self.api.get(f'/api/v1/orders/{order.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('total_amount', response.data)
        self.assertNotIn('paid_amount', response.data)

    def test_unauthenticated_cannot_create_order(self):
        response = self.api.post('/api/v1/orders/', {
            'client': self.client_obj.id,
            'quantity': 10,
            'unit': 'm2',
            'deadline': '2026-12-31',
        })
        self.assertEqual(response.status_code, 401)

    def test_list_orders(self):
        self.api.force_authenticate(user=self.owner)
        Order.objects.create(
            client=self.client_obj, product=self.product, quantity=5, unit='m2',
            deadline='2026-12-31',
        )
        response = self.api.get('/api/v1/orders/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._list_count(response), 1)

    def test_list_filter_by_status(self):
        self.api.force_authenticate(user=self.owner)
        Order.objects.create(
            client=self.client_obj, quantity=3, unit='m2', deadline='2026-12-31',
            status=OrderStatus.NEW,
        )
        Order.objects.create(
            client=self.client_obj, quantity=7, unit='m2', deadline='2026-12-31',
            status=OrderStatus.READY,
        )
        response = self.api.get(f'/api/v1/orders/?status={OrderStatus.NEW}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._list_count(response), 1)

    def test_new_order_default_statuses(self):
        self.api.force_authenticate(user=self.owner)
        response = self.api.post('/api/v1/orders/', {
            'client': self.client_obj.id,
            'quantity': 5,
            'unit': 'm2',
            'deadline': '2026-12-31',
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], OrderStatus.NEW)
        self.assertEqual(response.data['payment_status'], PaymentStatus.UNPAID)
        # is_paid = paid >= total; 0 >= 0 is True
        self.assertEqual(response.data['is_paid'], True)
        self.assertEqual(response.data['has_debt'], False)

    def test_has_debt_when_partially_paid(self):
        order = Order.objects.create(
            client=self.client_obj, quantity=5, unit='m2', deadline='2026-12-31',
            total_amount=Decimal('5000'), paid_amount=Decimal('2000'),
        )
        self.assertTrue(order.has_debt)
        self.assertFalse(order.is_paid)

    def test_is_paid_when_fully_paid(self):
        order = Order.objects.create(
            client=self.client_obj, quantity=5, unit='m2', deadline='2026-12-31',
            total_amount=Decimal('5000'), paid_amount=Decimal('5000'),
        )
        self.assertTrue(order.is_paid)
        self.assertFalse(order.has_debt)

    def test_overdue_check(self):
        order = Order.objects.create(
            client=self.client_obj, quantity=5, unit='m2',
            deadline=date.today() - timedelta(days=1),
        )
        order.check_overdue()
        self.assertTrue(order.is_overdue)

        order.status = OrderStatus.DELIVERED
        order.save()
        order.check_overdue()
        self.assertFalse(order.is_overdue)


class OrderActionsTests(TestCase):
    """Tests for assign_worker and update_payment actions."""

    def setUp(self):
        self.api = APIClient()
        self.owner, self.admin, self.worker = _create_users()
        self.client_obj, _ = _create_client_and_product()
        self.order = Order.objects.create(
            client=self.client_obj, quantity=10, unit='m2', deadline='2026-12-31',
        )

    def test_owner_can_assign_worker(self):
        self.api.force_authenticate(user=self.owner)
        response = self.api.post(f'/api/v1/orders/{self.order.id}/assign_worker/', {
            'worker_id': self.worker.id,
        })
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.worker, self.worker)
        self.assertEqual(self.order.status, OrderStatus.SENT_TO_WORKER)

    def test_admin_can_assign_worker(self):
        self.api.force_authenticate(user=self.admin)
        response = self.api.post(f'/api/v1/orders/{self.order.id}/assign_worker/', {
            'worker_id': self.worker.id,
        })
        self.assertEqual(response.status_code, 200)

    def test_worker_cannot_assign_worker(self):
        self.api.force_authenticate(user=self.worker)
        response = self.api.post(f'/api/v1/orders/{self.order.id}/assign_worker/', {
            'worker_id': self.worker.id,
        })
        self.assertEqual(response.status_code, 403)

    def test_assign_worker_missing_id_returns_400(self):
        self.api.force_authenticate(user=self.owner)
        response = self.api.post(f'/api/v1/orders/{self.order.id}/assign_worker/', {})
        self.assertEqual(response.status_code, 400)

    def test_owner_can_update_payment(self):
        self.api.force_authenticate(user=self.owner)
        self.order.total_amount = Decimal('6000')
        self.order.save()
        response = self.api.post(f'/api/v1/orders/{self.order.id}/update_payment/', {
            'payment_status': 'paid',
            'amount': 6000,
        })
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, PaymentStatus.PAID)
        self.assertEqual(self.order.paid_amount, 6000)

    def test_admin_cannot_update_payment(self):
        self.api.force_authenticate(user=self.admin)
        response = self.api.post(f'/api/v1/orders/{self.order.id}/update_payment/', {
            'payment_status': 'paid',
        })
        self.assertEqual(response.status_code, 403)
