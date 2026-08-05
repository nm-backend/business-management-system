"""
Финальная перепроверка аудита (этап 8, повторная ревизия): безопасность
сессий и access keys.

1. Logout: из-за NameError (`RefreshToken` вместо импортированного класса)
   refresh-токен НЕ попадал в blacklist — «вышедшая» сессия продолжала жить.
2. Fingerprint: refresh без fingerprint для токена с claim fpr проходил
   (защита обходилась удалением поля), а вращённый токен терял защиту навсегда.
3. Access Key: ключ можно было выпустить УЖЕ активированному сотруднику —
   публичный redeem тихо сбрасывал его пароль (захват аккаунта).
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.access_keys import issue_access_key
from apps.accounts.models import User
from apps.companies.models import Company


def _login(client, username, password, fingerprint=''):
    payload = {'username': username, 'password': password}
    if fingerprint:
        payload['fingerprint'] = fingerprint
    return client.post('/api/v1/accounts/login/', payload, format='json')


class LogoutBlacklistsRefreshTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='LOGOUT', is_active=True)
        self.user = User.objects.create_user(
            username='logout_user', password='Pass123!x',
            role=User.Role.OWNER, company=self.company,
        )

    def test_logout_blacklists_refresh_token(self):
        c = APIClient()
        login = _login(c, 'logout_user', 'Pass123!x', fingerprint='fp-1')
        self.assertEqual(login.status_code, 200)
        refresh = login.data['tokens']['refresh']

        out = APIClient()
        out.force_authenticate(user=self.user)
        resp = out.post('/api/v1/accounts/logout/', {'refresh': refresh}, format='json')
        self.assertEqual(resp.status_code, 205)

        # После выхода refresh обязан умереть.
        pub = APIClient()
        refreshed = pub.post('/api/v1/accounts/token/refresh/', {'refresh': refresh}, format='json')
        self.assertEqual(refreshed.status_code, 401)

    def test_logout_without_refresh_still_succeeds(self):
        c = APIClient()
        c.force_authenticate(user=self.user)
        resp = c.post('/api/v1/accounts/logout/', {}, format='json')
        self.assertEqual(resp.status_code, 205)

    def test_logout_invalid_refresh_returns_400_not_silent(self):
        c = APIClient()
        c.force_authenticate(user=self.user)
        resp = c.post('/api/v1/accounts/logout/', {'refresh': 'garbage'}, format='json')
        self.assertEqual(resp.status_code, 400)


class FingerprintRefreshTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='FPR', is_active=True)
        self.user = User.objects.create_user(
            username='fpr_user', password='Pass123!x',
            role=User.Role.OWNER, company=self.company,
        )

    def test_refresh_without_fingerprint_rejected(self):
        c = APIClient()
        login = _login(c, 'fpr_user', 'Pass123!x', fingerprint='fp-device-1')
        refresh = login.data['tokens']['refresh']

        pub = APIClient()
        resp = pub.post('/api/v1/accounts/token/refresh/', {'refresh': refresh}, format='json')
        self.assertEqual(resp.status_code, 401)

    def test_refresh_with_wrong_fingerprint_is_theft(self):
        c = APIClient()
        login = _login(c, 'fpr_user', 'Pass123!x', fingerprint='fp-device-1')
        refresh = login.data['tokens']['refresh']

        pub = APIClient()
        resp = pub.post('/api/v1/accounts/token/refresh/',
                        {'refresh': refresh, 'fingerprint': 'fp-attacker'}, format='json')
        self.assertEqual(resp.status_code, 401)
        self.assertTrue(resp.data.get('token_theft'))

    def test_rotated_token_keeps_fingerprint_protection(self):
        c = APIClient()
        login = _login(c, 'fpr_user', 'Pass123!x', fingerprint='fp-device-1')
        refresh = login.data['tokens']['refresh']

        pub = APIClient()
        ok = pub.post('/api/v1/accounts/token/refresh/',
                      {'refresh': refresh, 'fingerprint': 'fp-device-1'}, format='json')
        self.assertEqual(ok.status_code, 200)
        new_refresh = ok.data['refresh']

        # Вращённый токен обязан сохранить защиту: без fingerprint — 401.
        again = pub.post('/api/v1/accounts/token/refresh/', {'refresh': new_refresh}, format='json')
        self.assertEqual(again.status_code, 401)

    def test_refresh_with_correct_fingerprint_works(self):
        c = APIClient()
        login = _login(c, 'fpr_user', 'Pass123!x', fingerprint='fp-device-1')
        refresh = login.data['tokens']['refresh']

        pub = APIClient()
        resp = pub.post('/api/v1/accounts/token/refresh/',
                        {'refresh': refresh, 'fingerprint': 'fp-device-1'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('access', resp.data)


class AccessKeyActiveAccountTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='AKACT', is_active=True)
        self.owner = User.objects.create_user(
            username='akact_owner', password='Pass123!x',
            role=User.Role.OWNER, company=self.company,
        )
        self.activated = User.objects.create_user(
            username='akact_worker', password='WorkerPass!1',
            role=User.Role.WORKER, company=self.company,
        )

    def test_issue_refused_for_activated_account(self):
        with self.assertRaises(ValueError):
            issue_access_key(user=self.activated, created_by=self.owner)

    def test_issue_endpoint_returns_400_for_activated_account(self):
        c = APIClient()
        c.force_authenticate(user=self.owner)
        resp = c.post(f'/api/v1/accounts/users/{self.activated.id}/access_key/')
        self.assertEqual(resp.status_code, 400)

    def test_issue_still_works_for_invited_account(self):
        invited = User.objects.create_user(
            username='akact_invited', role=User.Role.WORKER,
            company=self.company,
        )
        invited.set_unusable_password()
        invited.save()
        key = issue_access_key(user=invited, created_by=self.owner)
        self.assertIsNotNone(key)
