"""
Расследование: блокировка компании через PATCH и «живучесть» refresh-токена.

Воспроизведено до правки:
1. PATCH /companies/{id}/ {"is_active": false} проходил в обход toggle_active:
        сотрудники не деактивировались, токены не гасли, аудит не писался.
2. Даже после штатной блокировки (toggle_active) refresh-токен продолжал
   выдавать свежий access — сессия «жила» вечно.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company

COMPANIES = '/api/v1/companies/'
REFRESH = '/api/v1/accounts/token/refresh/'
LOGIN = '/api/v1/accounts/login/'


class CompanyBlockTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_user(username='sa_owner', password='p',
                                                   role=User.Role.SUPERADMIN, company=None)
        self.company = Company.objects.create(name='BlockCo', is_active=True)
        self.owner = User.objects.create_user(username='blk_owner', password='OwnerPass123!',
                                              role=User.Role.OWNER, company=self.company)
        self.sa_api = APIClient()
        self.sa_api.force_authenticate(self.superadmin)

    def test_patch_is_active_ignored(self):
        """is_active меняется только через toggle_active: PATCH его не трогает."""
        resp = self.sa_api.patch(f'{COMPANIES}{self.company.id}/', {'is_active': False},
                                 format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.company.refresh_from_db()
        self.assertTrue(self.company.is_active, 'компания не блокируется через PATCH')

    def test_toggle_active_blocks_refresh_token(self):
        api = APIClient()
        resp = api.post(LOGIN, {'username': 'blk_owner', 'password': 'OwnerPass123!'},
                        format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        refresh_token = resp.data['tokens']['refresh']

        resp = self.sa_api.post(f'{COMPANIES}{self.company.id}/toggle_active/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(resp.json()['is_active'])

        resp = api.post(REFRESH, {'refresh': refresh_token}, format='json')
        self.assertEqual(resp.status_code, 401, resp.data)

    def test_refresh_still_works_for_active_company(self):
        api = APIClient()
        resp = api.post(LOGIN, {'username': 'blk_owner', 'password': 'OwnerPass123!'},
                        format='json')
        refresh_token = resp.data['tokens']['refresh']
        resp = api.post(REFRESH, {'refresh': refresh_token}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
