"""
API-контур 2FA: setup → confirm → status → перевыпуск кодов → disable.

Экран «Настройки → Безопасность» работает ровно через эти эндпоинты, поэтому
контракт проверяется целиком: иначе кнопка в интерфейсе могла бы вести в
никуда, а ошибка в ответе — остаться незамеченной.

Ключевое свойство модели: до подтверждения кодом 2FA НЕ включено, поэтому
закрытое окно настройки не блокирует сотруднику вход.
"""
import time

from django.test import TestCase
from django_otp.oath import TOTP
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.two_factor import (
    RECOVERY_DEVICE_NAME,
    TOTP_DEVICE_NAME,
    VERIFY_RECOVERY,
    get_totp_device,
    verify_code,
)
from apps.companies.models import Company

STATUS = '/api/v1/accounts/me/2fa/'
SETUP = '/api/v1/accounts/me/2fa/setup/'
CONFIRM = '/api/v1/accounts/me/2fa/confirm/'
DISABLE = '/api/v1/accounts/me/2fa/disable/'
RECOVERY = '/api/v1/accounts/me/2fa/recovery-codes/'

PASSWORD = 'secret-pass-123'


def code_for(device, offset=0):
    """
    TOTP-код так, как его посчитало бы приложение-аутентификатор.

    offset нужен, когда код уже был принят в этом же шаге: повторный код
    того же шага отклоняется по замыслу (защита от повторного использования),
    поэтому берём следующий шаг — он попадает в допуск tolerance=1.
    """
    totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    totp.time = time.time() + offset
    return f'{totp.token():0{device.digits}d}'


class TwoFactorApiTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='2FA Co', is_active=True)
        self.user = User.objects.create_user(
            username='twofa_user', password=PASSWORD,
            role=User.Role.OWNER, company=self.company,
        )
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def _setup(self):
        resp = self.api.post(SETUP, {'password': PASSWORD}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        return resp.json()

    def _enable(self):
        self._setup()
        device = get_totp_device(self.user, confirmed=False)
        resp = self.api.post(CONFIRM, {'code': code_for(device)}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        return resp.json()

    # ── статус ──

    def test_status_disabled_by_default(self):
        resp = self.api.get(STATUS)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'enabled': False, 'recovery_codes_left': 0})

    # ── шаг 1: секрет и QR ──

    def test_setup_requires_password(self):
        resp = self.api.post(SETUP, {}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('password', resp.json())

    def test_setup_rejects_wrong_password(self):
        resp = self.api.post(SETUP, {'password': 'not-my-password'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(get_totp_device(self.user, confirmed=False))

    def test_setup_returns_qr_and_secret(self):
        data = self._setup()
        self.assertEqual(set(data), {'secret', 'otpauth_uri', 'qr_code'})
        self.assertIn('otpauth://totp/', data['otpauth_uri'])
        self.assertTrue(data['qr_code'].startswith('data:image/png;base64,'))
        # QR рисуется на сервере: секрет не уходит во внешний сервис.
        self.assertNotIn('http', data['qr_code'])

    def test_setup_does_not_enable_before_confirmation(self):
        self._setup()
        self.assertFalse(self.api.get(STATUS).json()['enabled'])

    def test_setup_twice_reuses_single_pending_device(self):
        self._setup()
        first = get_totp_device(self.user, confirmed=False).pk
        self._setup()
        pending = get_totp_device(self.user, confirmed=False)
        self.assertNotEqual(first, pending.pk, 'незавершённая попытка должна заменяться')
        self.assertEqual(
            type(pending).objects.filter(user=self.user, name=TOTP_DEVICE_NAME).count(), 1,
        )

    # ── шаг 2: подтверждение ──

    def test_confirm_with_valid_code_enables_and_returns_recovery_codes(self):
        data = self._enable()
        self.assertTrue(data['enabled'])
        self.assertEqual(len(data['recovery_codes']), 10)

        status = self.api.get(STATUS).json()
        self.assertTrue(status['enabled'])
        self.assertEqual(status['recovery_codes_left'], 10)

    def test_confirm_with_invalid_code_keeps_2fa_off(self):
        self._setup()
        resp = self.api.post(CONFIRM, {'code': '000000'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(self.api.get(STATUS).json()['enabled'])

    def test_setup_after_enabled_is_rejected(self):
        self._enable()
        resp = self.api.post(SETUP, {'password': PASSWORD}, format='json')
        self.assertEqual(resp.status_code, 400)

    # ── резервные коды ──

    def test_recovery_code_is_single_use(self):
        codes = self._enable()['recovery_codes']
        self.assertEqual(verify_code(self.user, codes[0]), VERIFY_RECOVERY)
        self.assertIsNone(verify_code(self.user, codes[0]))

    def test_regenerate_invalidates_previous_codes(self):
        old = self._enable()['recovery_codes']
        resp = self.api.post(RECOVERY, {'password': PASSWORD}, format='json')
        self.assertEqual(resp.status_code, 200)
        new = resp.json()['recovery_codes']
        self.assertEqual(len(new), 10)
        self.assertTrue(set(old).isdisjoint(new))
        # Новые коды сразу активны, старые удалены из устройства.
        self.assertEqual(verify_code(self.user, new[0]), VERIFY_RECOVERY)
        self.assertFalse(
            StaticToken.objects.filter(
                device__user=self.user,
                device__name=RECOVERY_DEVICE_NAME,
                token=old[0],
            ).exists()
        )

    def test_regenerate_requires_2fa(self):
        resp = self.api.post(RECOVERY, {'password': PASSWORD}, format='json')
        self.assertEqual(resp.status_code, 400)

    # ── отключение ──

    def test_disable_requires_valid_code(self):
        self._enable()
        resp = self.api.post(DISABLE, {'password': PASSWORD, 'code': '000000'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(self.api.get(STATUS).json()['enabled'])

    def test_disable_requires_password(self):
        self._enable()
        resp = self.api.post(DISABLE, {'password': 'wrong', 'code': '000000'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_disable_removes_device_and_recovery_codes(self):
        self._enable()
        device = get_totp_device(self.user, confirmed=True)
        # code_for уже был принят при включении: берём следующий шаг.
        resp = self.api.post(
            DISABLE, {'password': PASSWORD, 'code': code_for(device, 30)}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        self.assertFalse(resp.json()['enabled'])
        self.assertFalse(self.api.get(STATUS).json()['enabled'])
        self.assertIsNone(get_totp_device(self.user))
        self.assertFalse(
            StaticDevice.objects.filter(user=self.user, name=RECOVERY_DEVICE_NAME).exists()
        )
