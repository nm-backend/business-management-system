"""
Этап J — Broken Access Control на глобальных Currency / ExchangeRate.

Currency и ExchangeRate — ГЛОБАЛЬНЫЕ (без company FK), а их ViewSet — полные
ModelViewSet с permission_classes=[IsAuthenticated]. Значит любой аутентифи-
цированный пользователь, включая работника любой компании, мог создавать/
менять/удалять глобальные валюты и курсы (общие для всех компаний).

Запись должна быть доступна только платформенному супер-админу; чтение —
всем аутентифицированным (компаниям нужны валюты для отображения).

До фикса тесты записи падают (201/200/204), после — 403.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.core.models import Currency, ExchangeRate


class CurrencyBacTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='CurCo')
        self.worker = User.objects.create_user(username='j_w', password='p',
                                                role=User.Role.WORKER, company=self.company)
        self.owner = User.objects.create_user(username='j_o', password='p',
                                               role=User.Role.OWNER, company=self.company)
        self.superadmin = User.objects.create_user(username='j_sa', password='p',
                                                    role=User.Role.SUPERADMIN, company=None)
        self.kgs = Currency.objects.create(code='KGS', name='Som', symbol='с')
        self.usd = Currency.objects.create(code='USD', name='Dollar', symbol='$')

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_worker_cannot_create_currency(self):
        resp = self.api(self.worker).post('/api/v1/core/currencies/', {
            'code': 'EUR', 'name': 'Euro', 'symbol': '€'}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_owner_cannot_create_exchange_rate(self):
        resp = self.api(self.owner).post('/api/v1/core/exchange-rates/', {
            'from_currency': self.usd.id, 'to_currency': self.kgs.id,
            'rate': '89.5', 'effective_date': '2026-01-15'}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_worker_cannot_delete_currency(self):
        resp = self.api(self.worker).delete(f'/api/v1/core/currencies/{self.usd.id}/')
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Currency.objects.filter(pk=self.usd.pk).exists())

    def test_authenticated_can_read_currencies(self):
        resp = self.api(self.worker).get('/api/v1/core/currencies/')
        self.assertEqual(resp.status_code, 200)

    def test_superadmin_can_create_currency(self):
        resp = self.api(self.superadmin).post('/api/v1/core/currencies/', {
            'code': 'RUB', 'name': 'Rouble', 'symbol': '₽'}, format='json')
        self.assertEqual(resp.status_code, 201)
