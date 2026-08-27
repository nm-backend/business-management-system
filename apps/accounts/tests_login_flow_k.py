"""
Приёмочный тест входа (контракт): публичной регистрации нет.

    anonymous            -> /accounts/login/ (страница входа)
    POST login           -> JWT access + refresh
    refresh              -> новый access (fingerprint-обёртка)
    logout               -> refresh блэклистится
    /accounts/me/        -> корректная роль
    публичные /register, /signup, /create-account отсутствуют.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company


class LoginFlowAcceptanceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='LoginCo')
        self.owner = User.objects.create_user(username='lf_owner', password='Str0ng!Pass',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='lf_worker', password='Str0ng!Pass',
                                               role=User.Role.WORKER, company=self.company)

    def test_anonymous_login_page_served(self):
        client = APIClient()
        resp = client.get('/accounts/login/')
        self.assertEqual(resp.status_code, 200)

    def test_login_returns_jwt_and_refresh_rotates(self):
        api = APIClient()
        resp = api.post('/api/v1/accounts/login/', {
            'username': 'lf_owner', 'password': 'Str0ng!Pass', 'fingerprint': 'x' * 32,
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        tokens = resp.data['tokens']
        self.assertTrue(tokens['access'])
        self.assertTrue(tokens['refresh'])
        self.assertEqual(resp.data['user']['role'], 'owner')

        # refresh -> новый access (с fingerprint).
        resp2 = api.post('/api/v1/accounts/token/refresh/', {
            'refresh': tokens['refresh'], 'fingerprint': 'x' * 32,
        }, format='json')
        self.assertEqual(resp2.status_code, 200, resp2.data)
        self.assertTrue(resp2.data['access'])

        # me -> корректная роль.
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {resp2.data['access']}")
        me = api.get('/api/v1/accounts/me/')
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data['role'], 'owner')

    def test_logout_blacklists_refresh(self):
        api = APIClient()
        tokens = api.post('/api/v1/accounts/login/', {
            'username': 'lf_worker', 'password': 'Str0ng!Pass', 'fingerprint': 'x' * 32,
        }, format='json').data['tokens']
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        resp = api.post('/api/v1/accounts/logout/', {'refresh': tokens['refresh']}, format='json')
        self.assertEqual(resp.status_code, 205)
        # Повторный refresh заблэклистенного токена отвергается.
        resp2 = api.post('/api/v1/accounts/token/refresh/', {
            'refresh': tokens['refresh'], 'fingerprint': 'x' * 32,
        }, format='json')
        self.assertEqual(resp2.status_code, 401)

    def test_no_public_signup_routes(self):
        client = APIClient()
        for path in ('/register', '/signup', '/create-account',
                     '/accounts/register/', '/accounts/signup/'):
            # SPA-fallback отдаёт index.html (200) для неизвестных GET-путей,
            # но это НЕ страница регистрации. Для POST — честная 404.
            resp = client.post(path, {}, format='json')
            self.assertEqual(resp.status_code, 404, f'{path} не должен существовать')
