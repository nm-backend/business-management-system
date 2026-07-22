"""
Финальный адверсариал — производные финполя клиента не должны писаться через API.

total_orders_amount / total_paid / debt вычисляются recalculate_financials из
заказов и платежей. В ClientOwnerSerializer они были записываемыми, а
perform_update не пересчитывал — owner мог PATCH-ем подменить долг клиента
(до следующего платежа), искажая отчёты и создавая ложный audit-след.

До фикса тест падает (debt меняется), после — поля read-only.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.clients.models import Client


class ClientDerivedFieldsTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='DfCo')
        self.owner = User.objects.create_user(username='df_o', password='p',
                                               role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='C',
                                                debt=Decimal('500'),
                                                total_paid=Decimal('0'))
        self.api = APIClient()
        self.api.force_authenticate(user=self.owner)

    def test_debt_is_read_only(self):
        resp = self.api.patch(f'/api/v1/clients/clients/{self.client_obj.id}/',
                              {'debt': '0'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.debt, Decimal('500'))  # не подменён

    def test_total_paid_is_read_only(self):
        resp = self.api.patch(f'/api/v1/clients/clients/{self.client_obj.id}/',
                              {'total_paid': '999999'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.total_paid, Decimal('0'))

    def test_editable_fields_still_work(self):
        """Позитивный контроль: обычные поля (comment) редактируются."""
        resp = self.api.patch(f'/api/v1/clients/clients/{self.client_obj.id}/',
                              {'comment': 'важный клиент'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.comment, 'важный клиент')
