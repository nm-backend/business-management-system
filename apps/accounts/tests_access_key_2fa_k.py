"""
Access Key не должен обходить включённое 2FA (аудит K, находка #2).

Раньше можно было выпустить ключ активному сотруднику с подтверждённым 2FA, а
публичный redeem ставил новый пароль и выдавал JWT — полностью минуя второй
фактор (и меняя пароль жертвы). Теперь ключ НЕ выдаётся и НЕ принимается для
аккаунта с включённым 2FA; онбординг приглашённых (у них 2FA ещё нет) работает.
"""
from django.test import TestCase
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework.test import APIClient

from apps.accounts.access_keys import issue_access_key, redeem_access_key
from apps.accounts.models import User
from apps.accounts.two_factor import TOTP_DEVICE_NAME
from apps.companies.models import Company


def enable_2fa(user):
    TOTPDevice.objects.create(user=user, name=TOTP_DEVICE_NAME, confirmed=True)


class AccessKey2FAServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='K2FA', is_active=True)
        self.admin = User.objects.create_user(username='k2_admin', password='p',
                                               role=User.Role.ADMIN, company=self.company)
        self.worker = User.objects.create_user(username='k2_worker', password='OldPass123!',
                                               role=User.Role.WORKER, company=self.company)

    def test_issue_refused_when_2fa_enabled(self):
        enable_2fa(self.worker)
        with self.assertRaises(ValueError):
            issue_access_key(user=self.worker, created_by=self.admin)

    def test_redeem_refused_when_2fa_enabled_password_unchanged(self):
        # Ключ выдан ДО включения 2FA (легитимно), затем работник включил 2FA.
        key = issue_access_key(user=self.worker, created_by=self.admin)
        enable_2fa(self.worker)
        user, error = redeem_access_key(code=key.key, new_password='NewPass123!x')
        self.assertIsNone(user)
        self.assertEqual(error, 'two_factor_enabled')
        self.worker.refresh_from_db()
        self.assertTrue(self.worker.check_password('OldPass123!'))  # пароль НЕ сменён

    def test_redeem_still_works_without_2fa(self):
        key = issue_access_key(user=self.worker, created_by=self.admin)
        user, error = redeem_access_key(code=key.key, new_password='NewPass123!x')
        self.assertIsNone(error)
        self.assertEqual(user, self.worker)


class AccessKey2FAEndpointTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='K2FAE', is_active=True)
        self.owner = User.objects.create_user(username='k2e_owner', password='p',
                                               role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='k2e_worker', password='OldPass123!',
                                               role=User.Role.WORKER, company=self.company)

    def test_issue_endpoint_returns_400_for_2fa_worker(self):
        enable_2fa(self.worker)
        c = APIClient()
        c.force_authenticate(user=self.owner)
        resp = c.post(f'/api/v1/accounts/users/{self.worker.id}/access_key/')
        self.assertEqual(resp.status_code, 400)

    def test_redeem_endpoint_blocked_for_2fa_worker(self):
        key = issue_access_key(user=self.worker, created_by=self.owner)
        enable_2fa(self.worker)
        pub = APIClient()
        resp = pub.post('/api/v1/accounts/access-key/redeem/',
                        {'access_key': key.key, 'new_password': 'NewPass123!x'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.worker.refresh_from_db()
        self.assertTrue(self.worker.check_password('OldPass123!'))
