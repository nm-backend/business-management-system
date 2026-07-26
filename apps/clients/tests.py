"""
API tests for clients app.

Coverage:
- Client CRUD operations
- Active / archived list endpoints
- archive / unarchive actions
- RBAC: owner sees financial fields, admin/worker don't
- Auto-archive signal
"""
from decimal import Decimal
from datetime import date
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
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


class ClientCRUDTests(TestCase):
    """Tests for basic CRUD on clients."""

    def setUp(self):
        self.api = APIClient()
        self.owner, self.admin, self.worker = _create_users()

    def test_owner_can_create_client(self):
        self.api.force_authenticate(user=self.owner)
        response = self.api.post('/api/v1/clients/', {
            'name': 'New Client',
            'phone': '998901234567',
            'address': 'Tashkent',
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(response.data['name'], 'New Client')

    def test_admin_can_create_client(self):
        self.api.force_authenticate(user=self.admin)
        response = self.api.post('/api/v1/clients/', {'name': 'Admin Client'})
        self.assertEqual(response.status_code, 201)

    def test_worker_can_create_client(self):
        self.api.force_authenticate(user=self.worker)
        response = self.api.post('/api/v1/clients/', {'name': 'Worker Client'})
        self.assertEqual(response.status_code, 201)

    def test_unauthenticated_cannot_create(self):
        response = self.api.post('/api/v1/clients/', {'name': 'No Auth'})
        self.assertEqual(response.status_code, 401)

    def test_owner_sees_financial_fields(self):
        self.api.force_authenticate(user=self.owner)
        client = Client.objects.create(
            name='Financial Client', total_orders_amount=Decimal('10000'),
            total_paid=Decimal('5000'), debt=Decimal('5000'), profit=Decimal('500'),
        )
        response = self.api.get(f'/api/v1/clients/{client.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('total_orders_amount', response.data)
        self.assertIn('total_paid', response.data)
        self.assertIn('debt', response.data)
        self.assertIn('profit', response.data)

    def test_admin_does_not_see_financial_fields(self):
        self.api.force_authenticate(user=self.admin)
        client = Client.objects.create(
            name='Hidden Client', total_orders_amount=Decimal('10000'),
        )
        response = self.api.get(f'/api/v1/clients/{client.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('total_orders_amount', response.data)
        self.assertNotIn('total_paid', response.data)
        self.assertNotIn('debt', response.data)
        self.assertNotIn('profit', response.data)

    def test_worker_does_not_see_financial_fields(self):
        self.api.force_authenticate(user=self.worker)
        client = Client.objects.create(
            name='Worker View', total_orders_amount=Decimal('10000'),
        )
        response = self.api.get(f'/api/v1/clients/{client.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('total_orders_amount', response.data)
        self.assertNotIn('profit', response.data)

    def test_list_clients(self):
        self.api.force_authenticate(user=self.owner)
        Client.objects.create(name='Client A')
        Client.objects.create(name='Client B')
        response = self.api.get('/api/v1/clients/')
        self.assertEqual(response.status_code, 200)
        data = response.json() if hasattr(response, 'content') else response.data
        results = data.get('results', data) if isinstance(data, dict) else data
        self.assertEqual(len(results), 2)

    def test_client_has_debt_property(self):
        client = Client.objects.create(name='Debtor', debt=Decimal('500'))
        self.assertTrue(client.has_debt)
        client2 = Client.objects.create(name='Clean', debt=Decimal('0'))
        self.assertFalse(client2.has_debt)


class ClientArchiveTests(TestCase):
    """Tests for active/archived and archive/unarchive actions."""

    def setUp(self):
        self.api = APIClient()
        self.owner, self.admin, self.worker = _create_users()
        self.client_obj = Client.objects.create(name='Archivable')
        Client.objects.create(name='Other')

    def test_active_endpoint_returns_active_only(self):
        self.api.force_authenticate(user=self.owner)
        self.client_obj.is_archived = True
        self.client_obj.is_active = False
        self.client_obj.save()
        response = self.api.get('/api/v1/clients/active/')
        self.assertEqual(response.status_code, 200)
        names = [c['name'] for c in response.data]
        self.assertNotIn('Archivable', names)

    def test_archived_endpoint_returns_archived_only(self):
        self.api.force_authenticate(user=self.owner)
        self.client_obj.is_archived = True
        self.client_obj.save()
        response = self.api.get('/api/v1/clients/archived/')
        self.assertEqual(response.status_code, 200)
        names = [c['name'] for c in response.data]
        self.assertIn('Archivable', names)

    def test_owner_can_archive_client(self):
        self.api.force_authenticate(user=self.owner)
        response = self.api.post(f'/api/v1/clients/{self.client_obj.id}/archive/')
        self.assertEqual(response.status_code, 200)
        self.client_obj.refresh_from_db()
        self.assertTrue(self.client_obj.is_archived)

    def test_admin_cannot_archive_client(self):
        self.api.force_authenticate(user=self.admin)
        response = self.api.post(f'/api/v1/clients/{self.client_obj.id}/archive/')
        self.assertEqual(response.status_code, 403)

    def test_worker_cannot_archive_client(self):
        self.api.force_authenticate(user=self.worker)
        response = self.api.post(f'/api/v1/clients/{self.client_obj.id}/archive/')
        self.assertEqual(response.status_code, 403)

    def test_owner_can_unarchive_client(self):
        self.api.force_authenticate(user=self.owner)
        self.client_obj.is_archived = True
        self.client_obj.save()
        response = self.api.post(f'/api/v1/clients/{self.client_obj.id}/unarchive/')
        self.assertEqual(response.status_code, 200)
        self.client_obj.refresh_from_db()
        self.assertFalse(self.client_obj.is_archived)


class ClientAutoArchiveTests(TestCase):
    """Tests for auto-archive logic."""

    def test_auto_archive_when_no_orders(self):
        client = Client.objects.create(name='Clean Client')
        client.auto_archive()
        self.assertTrue(client.is_archived)
        self.assertFalse(client.is_active)

    def test_auto_archive_not_triggered_with_active_order(self):
        client = Client.objects.create(name='Active Client')
        Order.objects.create(
            client=client, quantity=1, unit='m2',
            deadline=date(2026, 12, 31), status=OrderStatus.NEW,
        )
        client.auto_archive()
        self.assertFalse(client.is_archived)

    def test_auto_archive_not_triggered_with_debt(self):
        client = Client.objects.create(name='Debt Client', debt=Decimal('500'))
        client.auto_archive()
        self.assertFalse(client.is_archived)
