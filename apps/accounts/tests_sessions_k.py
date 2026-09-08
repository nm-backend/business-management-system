"""
Управление активными сессиями (макет «Сеансларни бошқариш»).

Реализовано ПОВЕРХ штатного JWT, без второй системы аутентификации:
источник истины — OutstandingToken/BlacklistedToken из simplejwt, рядом
хранятся только метаданные устройства (UserSession).

Отдельно зафиксировано свойство архитектуры: отзыв убивает refresh немедленно,
а уже выданный access-токен живёт до истечения своего срока (stateless JWT).
Для мгновенной блокировки человека есть is_active — это разные инструменты.
"""
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken, OutstandingToken,
)

from apps.accounts.models import User, UserSession
from apps.companies.models import Company

LOGIN = '/api/v1/accounts/login/'
REFRESH = '/api/v1/accounts/token/refresh/'
SESSIONS = '/api/v1/accounts/me/sessions/'
REVOKE_OTHERS = '/api/v1/accounts/me/sessions/revoke-others/'
LOGOUT = '/api/v1/accounts/logout/'
ME = '/api/v1/accounts/me/'

PASSWORD = 'Str0ng!Pass9'


class SessionManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='SessionCo')
        cls.owner = User.objects.create_user(
            username='ss_owner', password=PASSWORD, role=User.Role.OWNER, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='ss_worker', password=PASSWORD, role=User.Role.WORKER, company=cls.company,
        )
        other = Company.objects.create(name='OtherSessionCo')
        cls.foreign_owner = User.objects.create_user(
            username='ss_foreign', password=PASSWORD, role=User.Role.OWNER, company=other,
        )
        cls.superadmin = User.objects.create_superuser(
            username='ss_super', password=PASSWORD,
        )

    def login(self, username, fingerprint='device-1', agent='Chrome/Android'):
        api = APIClient(HTTP_USER_AGENT=agent)
        response = api.post(LOGIN, {
            'username': username, 'password': PASSWORD, 'fingerprint': fingerprint,
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        tokens = response.data['tokens']
        api.credentials(HTTP_AUTHORIZATION=f'Bearer {tokens["access"]}', HTTP_USER_AGENT=agent)
        return api, tokens

    # ── Просмотр ────────────────────────────────────────────────────────────

    def test_login_creates_visible_session(self):
        api, _ = self.login('ss_owner')
        rows = api.get(SESSIONS).data['results']
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['is_current'], 'своя сессия должна быть помечена текущей')
        self.assertEqual(rows[0]['user_agent'], 'Chrome/Android')
        self.assertIsNotNone(rows[0]['expires_at'])

    def test_two_devices_two_sessions(self):
        api1, _ = self.login('ss_owner', fingerprint='device-1', agent='Chrome/Android')
        self.login('ss_owner', fingerprint='device-2', agent='Safari/iPhone')

        rows = api1.get(SESSIONS).data['results']
        self.assertEqual(len(rows), 2)
        current = [r for r in rows if r['is_current']]
        self.assertEqual(len(current), 1, 'текущей может быть только одна сессия')
        self.assertEqual(current[0]['user_agent'], 'Chrome/Android')

    def test_only_own_sessions_visible(self):
        self.login('ss_worker', fingerprint='w-1')
        self.login('ss_foreign', fingerprint='f-1')
        api, _ = self.login('ss_owner', fingerprint='o-1')

        rows = api.get(SESSIONS).data['results']
        self.assertEqual(len(rows), 1)
        own_jti = set(
            OutstandingToken.objects.filter(user=self.owner).values_list('jti', flat=True)
        )
        self.assertIn(rows[0]['jti'], own_jti)

    def test_superadmin_sessions_are_separate(self):
        """Супер-админ видит только свои сессии — не сессии компаний."""
        self.login('ss_owner', fingerprint='o-1')
        api, _ = self.login('ss_super', fingerprint='s-1')
        rows = api.get(SESSIONS).data['results']
        self.assertEqual(len(rows), 1)

    def test_anonymous_denied(self):
        self.assertEqual(APIClient().get(SESSIONS).status_code, 401)

    # ── Отзыв конкретной сессии ─────────────────────────────────────────────

    def test_revoke_specific_session_kills_its_refresh(self):
        api1, tokens1 = self.login('ss_owner', fingerprint='device-1')
        api2, tokens2 = self.login('ss_owner', fingerprint='device-2')

        target = [r for r in api2.get(SESSIONS).data['results'] if not r['is_current']][0]
        response = api2.post(SESSIONS, {'jti': target['jti']}, format='json')
        self.assertEqual(response.status_code, 200, response.data)

        # Отозванная сессия больше не обновляется…
        refresh_dead = APIClient().post(REFRESH, {
            'refresh': tokens1['refresh'], 'fingerprint': 'device-1',
        }, format='json')
        self.assertEqual(refresh_dead.status_code, 401)

        # …а оставшаяся продолжает работать.
        refresh_alive = APIClient().post(REFRESH, {
            'refresh': tokens2['refresh'], 'fingerprint': 'device-2',
        }, format='json')
        self.assertEqual(refresh_alive.status_code, 200, refresh_alive.data)

    def test_cannot_revoke_foreign_session(self):
        _, foreign_tokens = self.login('ss_foreign', fingerprint='f-1')
        foreign_jti = OutstandingToken.objects.filter(user=self.foreign_owner).first().jti

        api, _ = self.login('ss_owner', fingerprint='o-1')
        response = api.post(SESSIONS, {'jti': foreign_jti}, format='json')
        self.assertEqual(response.status_code, 404, 'чужую сессию отзывать нельзя')

        # Чужой refresh продолжает работать — мы его не тронули.
        still_alive = APIClient().post(REFRESH, {
            'refresh': foreign_tokens['refresh'], 'fingerprint': 'f-1',
        }, format='json')
        self.assertEqual(still_alive.status_code, 200)

    def test_owner_cannot_revoke_employee_session(self):
        """Даже владелец не управляет чужими сессиями — для этого есть блокировка аккаунта."""
        self.login('ss_worker', fingerprint='w-1')
        worker_jti = OutstandingToken.objects.filter(user=self.worker).first().jti

        api, _ = self.login('ss_owner', fingerprint='o-1')
        self.assertEqual(api.post(SESSIONS, {'jti': worker_jti}, format='json').status_code, 404)

    def test_revoke_without_jti_is_400(self):
        api, _ = self.login('ss_owner')
        self.assertEqual(api.post(SESSIONS, {}, format='json').status_code, 400)

    def test_revoke_unknown_jti_is_404(self):
        api, _ = self.login('ss_owner')
        self.assertEqual(
            api.post(SESSIONS, {'jti': 'не-существует'}, format='json').status_code, 404,
        )

    # ── Отзыв всех остальных ────────────────────────────────────────────────

    def test_revoke_others_keeps_current(self):
        _, tokens1 = self.login('ss_owner', fingerprint='device-1')
        api2, tokens2 = self.login('ss_owner', fingerprint='device-2')
        self.login('ss_owner', fingerprint='device-3')

        response = api2.post(REVOKE_OTHERS, {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['revoked'], 2)

        rows = api2.get(SESSIONS).data['results']
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['is_current'])

        dead = APIClient().post(REFRESH, {
            'refresh': tokens1['refresh'], 'fingerprint': 'device-1',
        }, format='json')
        self.assertEqual(dead.status_code, 401)
        alive = APIClient().post(REFRESH, {
            'refresh': tokens2['refresh'], 'fingerprint': 'device-2',
        }, format='json')
        self.assertEqual(alive.status_code, 200)

    def test_revoke_others_does_not_touch_other_users(self):
        _, worker_tokens = self.login('ss_worker', fingerprint='w-1')
        api, _ = self.login('ss_owner', fingerprint='o-1')
        api.post(REVOKE_OTHERS, {}, format='json')

        alive = APIClient().post(REFRESH, {
            'refresh': worker_tokens['refresh'], 'fingerprint': 'w-1',
        }, format='json')
        self.assertEqual(alive.status_code, 200, 'чужие сессии не должны отзываться')

    # ── Совместимость с обычным выходом ─────────────────────────────────────

    def test_plain_logout_still_works(self):
        api, tokens = self.login('ss_owner')
        response = api.post(LOGOUT, {'refresh': tokens['refresh']}, format='json')
        self.assertIn(response.status_code, (200, 204, 205), response.data)

        dead = APIClient().post(REFRESH, {
            'refresh': tokens['refresh'], 'fingerprint': 'device-1',
        }, format='json')
        self.assertEqual(dead.status_code, 401)

    def test_logout_removes_session_from_list(self):
        api1, tokens1 = self.login('ss_owner', fingerprint='device-1')
        api2, _ = self.login('ss_owner', fingerprint='device-2')
        self.assertEqual(len(api2.get(SESSIONS).data['results']), 2)

        api1.post(LOGOUT, {'refresh': tokens1['refresh']}, format='json')
        self.assertEqual(len(api2.get(SESSIONS).data['results']), 1)

    # ── Свойства архитектуры ────────────────────────────────────────────────

    def test_revocation_uses_standard_blacklist(self):
        """Отзыв — это штатный blacklist simplejwt, а не своя таблица."""
        api, _ = self.login('ss_owner', fingerprint='device-1')
        api2, _ = self.login('ss_owner', fingerprint='device-2')
        target = [r for r in api2.get(SESSIONS).data['results'] if not r['is_current']][0]
        api2.post(SESSIONS, {'jti': target['jti']}, format='json')

        token = OutstandingToken.objects.get(jti=target['jti'])
        self.assertTrue(BlacklistedToken.objects.filter(token=token).exists())

    def test_access_token_survives_until_expiry_by_design(self):
        """
        Отзыв убивает refresh немедленно; access живёт до своего срока.

        Это свойство stateless-JWT: сервер не ходит в БД на каждый запрос.
        Тест фиксирует ФАКТИЧЕСКОЕ поведение, чтобы оно не менялось незаметно;
        для мгновенной блокировки человека используется is_active.
        """
        api1, tokens1 = self.login('ss_owner', fingerprint='device-1')
        api2, _ = self.login('ss_owner', fingerprint='device-2')
        target = [r for r in api2.get(SESSIONS).data['results'] if not r['is_current']][0]
        api2.post(SESSIONS, {'jti': target['jti']}, format='json')

        self.assertEqual(api1.get(ME).status_code, 200)

        # А блокировка аккаунта закрывает доступ сразу.
        self.owner.is_active = False
        self.owner.save(update_fields=['is_active'])
        self.assertIn(api1.get(ME).status_code, (401, 403))

    def test_session_metadata_recorded(self):
        self.login('ss_owner', fingerprint='device-1', agent='Firefox/Linux')
        session = UserSession.objects.get(user=self.owner)
        self.assertEqual(session.user_agent, 'Firefox/Linux')
        self.assertTrue(session.fingerprint_hash)
        self.assertNotEqual(session.fingerprint_hash, 'device-1', 'отпечаток хранится хешем')

    def test_session_visible_even_without_metadata(self):
        """Если метаданные не записались, сессию всё равно можно увидеть и закрыть."""
        api, _ = self.login('ss_owner')
        UserSession.objects.all().delete()
        rows = api.get(SESSIONS).data['results']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['user_agent'], '')
