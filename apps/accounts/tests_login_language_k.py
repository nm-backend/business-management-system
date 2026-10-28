"""
Экран входа: выбранный язык не должен теряться.

Раньше язык на экране входа был чисто клиентским. LoginSerializer и LoginView
переводили ошибки по request.user.language, но публичный эндпоинт анонимен —
request.user всегда AnonymousUser, поэтому любой отказ приходил на узбекском
независимо от выбранного языка. После успешного входа app.js загружал язык
профиля и возвращал интерфейс к uz_cyrl, даже если человек выбрал русский.

Теперь клиент передаёт язык, только когда пользователь действительно переключил
его на форме (иначе вход с чужого устройства затирал бы настройку профиля).
Сервер переводит отказы на этот язык и сохраняет выбор при успешном входе или
активации по Access Key.
"""
from django.test import TestCase
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework.test import APIClient

from apps.accounts.access_keys import issue_access_key
from apps.accounts.models import User
from apps.companies.models import Company
from core.utils import translate

LOGIN_URL = '/api/v1/accounts/login/'
REDEEM_URL = '/api/v1/accounts/access-key/redeem/'


class LoginLanguageTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='LangCo', is_active=True)
        self.user = User.objects.create_user(
            username='lang_user', password='LangPass123!',
            role=User.Role.OWNER, company=self.company, language='uz_cyrl',
        )
        self.api = APIClient()

    def _login(self, password='LangPass123!', username=None, **extra):
        return self.api.post(LOGIN_URL, {
            'username': username or self.user.username,
            'password': password,
            **extra,
        }, format='json')

    def _message(self, response):
        """Причина отказа: LoginView кладёт её в detail, сериализатор — в non_field_errors."""
        if 'detail' in response.data:
            return str(response.data['detail'])
        return str(response.data['non_field_errors'][0])

    def test_wrong_password_uses_selected_language(self):
        response = self._login(password='wrong-password', language='ru')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            self._message(response),
            translate('errors.auth.invalid_credentials', 'ru'),
        )

    def test_unknown_user_uses_selected_language(self):
        response = self._login(username='no_such_user', language='ky')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            self._message(response),
            translate('errors.auth.invalid_credentials', 'ky'),
        )

    def test_blocked_account_uses_selected_language(self):
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])

        response = self._login(language='ru')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            self._message(response),
            translate('errors.auth.account_inactive', 'ru'),
        )

    def test_blocked_company_uses_selected_language(self):
        self.company.is_active = False
        self.company.save(update_fields=['is_active'])
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])

        response = self._login(language='ru')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            self._message(response),
            translate('errors.auth.company_inactive', 'ru'),
        )

    def test_two_factor_prompt_uses_selected_language(self):
        """Второй фактор проверяется в LoginView, а не в сериализаторе."""
        TOTPDevice.objects.create(
            user=self.user, name='default', confirmed=True,
        )

        response = self._login(language='ru')

        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.data['two_factor_required'])
        self.assertEqual(
            response.data['detail'],
            translate('errors.auth.two_factor_required', 'ru'),
        )

    def test_successful_login_saves_selected_language(self):
        response = self._login(language='ky')

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.language, 'ky')
        # Ответ уже с новым языком: app.js берёт его из user.language и не
        # переключает интерфейс обратно после редиректа.
        self.assertEqual(response.data['user']['language'], 'ky')

    def test_login_without_selection_keeps_profile_language(self):
        """Пользователь не трогал переключатель — настройка профиля важнее."""
        self.user.language = 'ru'
        self.user.save(update_fields=['language'])

        response = self._login()

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.language, 'ru')
        self.assertEqual(response.data['user']['language'], 'ru')

    def test_failed_login_does_not_change_profile_language(self):
        self.user.language = 'ru'
        self.user.save(update_fields=['language'])

        response = self._login(password='wrong-password', language='ky')

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.language, 'ru')

    def test_unsupported_language_is_rejected(self):
        response = self._login(language='en')

        self.assertEqual(response.status_code, 400)
        self.assertIn('language', response.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.language, 'uz_cyrl')


class AccessKeyRedeemLanguageTests(TestCase):
    """Активация по ключу — тоже первый вход, язык должен сохраниться."""

    def setUp(self):
        self.company = Company.objects.create(name='KeyLangCo', is_active=True)
        self.owner = User.objects.create_user(
            username='key_lang_owner', password='OwnerPass123!',
            role=User.Role.OWNER, company=self.company,
        )
        # Приглашённый сотрудник: пароля ещё нет, аккаунт не активирован.
        self.invited = User.objects.create_user(
            username='key_lang_worker', role=User.Role.WORKER,
            company=self.company, is_active=False, language='uz_cyrl',
        )
        self.key = issue_access_key(user=self.invited, created_by=self.owner)
        self.api = APIClient()

    def _redeem(self, code=None, language=None):
        payload = {
            'access_key': code or self.key.key,
            'new_password': 'NewStrongPass123!',
        }
        if language is not None:
            payload['language'] = language
        return self.api.post(REDEEM_URL, payload, format='json')

    def test_redeem_saves_selected_language(self):
        response = self._redeem(language='ru')

        self.assertEqual(response.status_code, 200, response.content[:300])
        self.invited.refresh_from_db()
        self.assertEqual(self.invited.language, 'ru')
        self.assertEqual(response.data['user']['language'], 'ru')

    def test_invalid_key_error_uses_selected_language(self):
        response = self._redeem(code='SKP-0000-0000-0000', language='ru')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['detail'],
            translate('errors.auth.access_key_invalid', 'ru'),
        )
