"""
Расследование: архив клиента с долгом.

Воспроизведено до правки: клиента с долгом можно было архивировать вручную —
долг исчезал из активного учёта и отчётов без следа.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.warehouse.models import FinishedProduct

CLIENTS = '/api/v1/clients/clients/'


class ClientArchiveWithDebtTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='ClCo', is_active=True)
        self.owner = User.objects.create_user(username='cl_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _client_with_debt(self):
        client = Client.objects.create(company=self.company, name='Должник')
        product = FinishedProduct.objects.create(
            company=self.company, name='Дверь', quantity=Decimal('5'), unit='dona')
        resp = self.api.post('/api/v1/orders/orders/', {
            'client': client.id, 'product': product.id, 'quantity': '1',
            'unit': 'dona', 'total_amount': '200000',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        client.refresh_from_db()
        self.assertEqual(client.debt, Decimal('200000'))
        return client

    def test_archive_client_with_debt_rejected(self):
        client = self._client_with_debt()
        resp = self.api.post(f'{CLIENTS}{client.id}/archive/', {}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        client.refresh_from_db()
        self.assertFalse(client.is_archived)

    def test_destroy_client_with_debt_rejected(self):
        client = self._client_with_debt()
        resp = self.api.delete(f'{CLIENTS}{client.id}/')
        self.assertEqual(resp.status_code, 400, resp.data)
        client.refresh_from_db()
        self.assertFalse(client.is_archived)

    def test_archive_client_without_debt_allowed(self):
        client = Client.objects.create(company=self.company, name='Чистый')
        resp = self.api.post(f'{CLIENTS}{client.id}/archive/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        client.refresh_from_db()
        self.assertTrue(client.is_archived)
