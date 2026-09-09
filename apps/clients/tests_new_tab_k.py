"""
Вкладка «Янги» списка клиентов (макет «Мижозлар»).

Критерий фиксирован: created_at за последние 7 дней. Фильтр серверный —
иначе вторая страница «новых» содержала бы кого попало. Администратор
видит факт, без сумм; работник клиентов не видит.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.core.tests_tz_compliance_k import collect_money_keys

CLIENTS = '/api/v1/clients/clients/'


class ClientNewTabTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='NewTabCo')
        cls.owner = User.objects.create_user(
            username='nt_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='nt_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='nt_worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )
        cls.fresh = Client.objects.create(company=cls.company, name='Новый клиент')
        cls.old = Client.objects.create(company=cls.company, name='Старый клиент')
        Client.objects.filter(pk=cls.old.pk).update(
            created_at=timezone.now() - timedelta(days=8),
        )
        other = Company.objects.create(name='OtherNewTabCo')
        cls.foreign = Client.objects.create(company=other, name='Чужой новый')

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def names(self, user, params):
        rows = self.api_as(user).get(CLIENTS, params).data
        rows = rows['results'] if 'results' in rows else rows
        return {row['name'] for row in rows}

    def test_is_new_keeps_only_last_seven_days(self):
        names = self.names(self.owner, {'is_archived': 'false', 'is_new': 'true'})
        self.assertEqual(names, {'Новый клиент'})
        self.assertNotIn('Старый клиент', names)

    def test_is_new_is_tenant_scoped(self):
        names = self.names(self.owner, {'is_archived': 'false', 'is_new': 'true'})
        self.assertNotIn('Чужой новый', names)

    def test_admin_sees_new_tab_without_money(self):
        response = self.api_as(self.admin).get(
            CLIENTS, {'is_archived': 'false', 'is_new': 'true'},
        )
        self.assertEqual(response.status_code, 200)
        rows = response.data['results'] if 'results' in response.data else response.data
        self.assertEqual([row['name'] for row in rows], ['Новый клиент'])
        leaks = collect_money_keys(response.data)
        self.assertFalse(leaks, f'админ получил деньги: {leaks}')

    def test_worker_denied(self):
        response = self.api_as(self.worker).get(
            CLIENTS, {'is_archived': 'false', 'is_new': 'true'},
        )
        self.assertEqual(response.status_code, 403)

    def test_without_flag_old_clients_remain(self):
        names = self.names(self.owner, {'is_archived': 'false'})
        self.assertIn('Старый клиент', names)
        self.assertIn('Новый клиент', names)
