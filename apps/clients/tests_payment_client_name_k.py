"""
Оплата клиента в ленте кассы: без имени клиента операция анонимна.

/clients/payments/ отдаёт суммы только владельцу; client_name — read-only,
чтобы дашборд не делал второй запрос за карточкой клиента.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client, Payment
from apps.companies.models import Company

PAYMENTS = '/api/v1/clients/payments/'


class PaymentClientNameTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='PayNameCo')
        cls.owner = User.objects.create_user(
            username='pn_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='pn_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )
        cls.client_obj = Client.objects.create(
            company=cls.company, name='Акбаров Азизбек',
        )
        Payment.objects.create(
            company=cls.company, client=cls.client_obj,
            amount=Decimal('150000.00'), payment_date=timezone.now(),
        )

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def test_owner_sees_client_name(self):
        rows = self.api_as(self.owner).get(PAYMENTS).data
        rows = rows['results'] if 'results' in rows else rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['client_name'], 'Акбаров Азизбек')
        self.assertEqual(rows[0]['client'], self.client_obj.id)

    def test_admin_still_forbidden(self):
        self.assertEqual(self.api_as(self.admin).get(PAYMENTS).status_code, 403)
