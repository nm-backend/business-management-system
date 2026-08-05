"""
Глубокая ревизия accounts: дубликаты, чужой refresh в logout, push-подписки.

- создание пользователя с занятым username -> 400, а не 500 (IntegrityError)
- создание навыка с дублирующимся названием -> 400
- logout с чужим refresh-токеном -> 400 (нельзя выбить чужую сессию)
- push: лимит 5 подписок и валидация https-endpoint
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import PushSubscription, Skill, User
from apps.companies.models import Company

USERS = '/api/v1/accounts/users/'
SKILLS = '/api/v1/accounts/skills/'
PUSH = '/api/v1/accounts/push/subscribe/'


class DuplicateCreateTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='DupCo', is_active=True)
        self.owner = User.objects.create_user(username='dup_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_duplicate_username_returns_400(self):
        User.objects.create_user(username='taken', password='password1',
                                 role=User.Role.WORKER, company=self.company)
        resp = self.api.post(USERS, {
            'username': 'taken', 'password': 'password1', 'role': 'worker',
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.content[:200])
        self.assertIn('username', str(resp.data))

    def test_duplicate_skill_name_returns_400(self):
        Skill.objects.create(company=self.company, name='Резка')
        resp = self.api.post(SKILLS, {'name': 'Резка', 'category': 'Производство'},
                             format='json')
        self.assertEqual(resp.status_code, 400, resp.content[:200])
        self.assertIn('name', str(resp.data))

    def test_same_skill_name_in_other_company_is_ok(self):
        other_company = Company.objects.create(name='OtherDup', is_active=True)
        Skill.objects.create(company=other_company, name='Резка')
        resp = self.api.post(SKILLS, {'name': 'Резка', 'category': 'Производство'},
                             format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:200])


class LogoutForeignTokenTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='LogCo', is_active=True)
        self.owner = User.objects.create_user(username='log_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='log_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _refresh_for(self, user):
        from rest_framework_simplejwt.tokens import RefreshToken
        return str(RefreshToken.for_user(user))

    def test_logout_with_own_refresh_succeeds(self):
        resp = self.api.post('/api/v1/accounts/logout/',
                             {'refresh': self._refresh_for(self.owner)}, format='json')
        self.assertEqual(resp.status_code, 205, resp.content[:200])

    def test_logout_with_foreign_refresh_rejected(self):
        resp = self.api.post('/api/v1/accounts/logout/',
                             {'refresh': self._refresh_for(self.worker)}, format='json')
        self.assertEqual(resp.status_code, 400, resp.content[:200])

    def test_logout_without_refresh_succeeds(self):
        resp = self.api.post('/api/v1/accounts/logout/', {}, format='json')
        self.assertEqual(resp.status_code, 205)


class PushSubscriptionLimitTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='PushCo', is_active=True)
        self.worker = User.objects.create_user(username='push_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(self.worker)

    def _subscribe(self, endpoint):
        return self.api.post(PUSH, {
            'endpoint': endpoint,
            'keys': {'p256dh': 'a' * 32, 'auth': 'b' * 32},
        }, format='json')

    def test_non_https_endpoint_rejected(self):
        resp = self._subscribe('http://insecure.example.com/push')
        self.assertEqual(resp.status_code, 400, resp.content[:200])

    def test_five_subscriptions_then_limit(self):
        for i in range(5):
            resp = self._subscribe(f'https://example.com/push/{i}')
            self.assertEqual(resp.status_code, 201, resp.content[:200])
        resp = self._subscribe('https://example.com/push/6')
        self.assertEqual(resp.status_code, 400, resp.content[:200])
        self.assertEqual(PushSubscription.objects.filter(user=self.worker).count(), 5)

    def test_unsubscribe_frees_slot(self):
        for i in range(5):
            self._subscribe(f'https://example.com/push/{i}')
        self.api.delete(PUSH, {'endpoint': 'https://example.com/push/0'}, format='json')
        resp = self._subscribe('https://example.com/push/6')
        self.assertEqual(resp.status_code, 201, resp.content[:200])
