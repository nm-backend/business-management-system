"""Regression: client with debt before payment must be archived after full payment.

Воспроизведено: заказ выдан (deliver пересчитал долг клиента -> 300 в БД и в
памяти). Поздняя оплата: recalculate_financials() обновляет БД (долг 0), но
НЕ обновляет переданный инстанс клиента, поэтому auto_archive() видел старый
долг 300 и не архивировал клиента с нулевым долгом.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.orders.models import Order

from .models import Client


class ClientArchiveStaleDebtTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='StaleCo')
        self.owner = User.objects.create_user(
            username='stale_owner', password='p',
            role=User.Role.OWNER, company=self.company,
        )
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.api = APIClient()
        self.api.force_authenticate(user=self.owner)

    def _deliver_and_accrue_debt(self):
        order = Order.objects.create(
            company=self.company, client=self.client_obj,
            custom_product_name='Столешница', quantity=Decimal('1'), unit='sht',
            deadline=timezone.now() + timedelta(days=10),
            total_amount=Decimal('300'), status=Order.Status.DELIVERED,
        )
        self.client_obj.recalculate_financials()
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.debt, Decimal('300'))
        return order

    def test_full_payment_archives_client_that_had_debt(self):
        order = self._deliver_and_accrue_debt()
        resp = self.api.post('/api/v1/clients/payments/', {
            'client': self.client_obj.id, 'order': order.id,
            'amount': '300', 'payment_method': 'cash',
            'payment_date': '2026-08-03T12:00:00Z',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.debt, Decimal('0'))
        self.assertTrue(self.client_obj.is_archived)
