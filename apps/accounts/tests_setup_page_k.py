"""
Вход в систему на пустой базе (критический баг с боевого сервера).

БЫЛО: login_view и index_view редиректили на /accounts/setup/, пока в базе нет
супер-админа, а на setup-странице — только форма кода доступа. Кода не
существует (выдавать некому), поэтому свежий деплой было НЕ ОТКРЫТЬ вообще.
Воспроизведено на проде.

СТАЛО (как задумано): страница входа доступна всегда и даёт два пути —
логин/пароль или активация по коду доступа. Платформенный супер-администратор
создаётся командой `manage.py createsuperuser`, коды доступа сотрудникам
выдаются из админки.
"""
from django.test import TestCase

from apps.accounts.models import User

LOGIN_PAGE = '/accounts/login/'
KEY_PAGE = '/accounts/setup/'
LOGIN_API = '/api/v1/accounts/login/'
ADMIN_LOGIN = '/admin/login/'


class EmptyDatabaseEntryTests(TestCase):
    """На пустой базе страницы входа должны открываться, а не редиректить в тупик."""

    def test_login_page_opens_with_empty_database(self):
        self.assertFalse(User.objects.exists())
        resp = self.client.get(LOGIN_PAGE)
        self.assertEqual(resp.status_code, 200)

    def test_login_page_offers_both_ways_in(self):
        html = self.client.get(LOGIN_PAGE).content.decode()
        # 1) логин/пароль
        self.assertIn('id="login-form"', html)
        self.assertIn('id="username"', html)
        self.assertIn('id="password"', html)
        # 2) код доступа
        self.assertIn('id="access-key-panel"', html)
        self.assertIn('id="show-access-key"', html)

    def test_key_activation_page_opens_with_empty_database(self):
        resp = self.client.get(KEY_PAGE)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('ak-verify-form', resp.content.decode())

    def test_admin_login_page_reachable(self):
        # Вход в админку — источник кодов доступа.
        resp = self.client.get(ADMIN_LOGIN)
        self.assertEqual(resp.status_code, 200)


class CreateSuperuserCommandTests(TestCase):
    """Аккаунт из `manage.py createsuperuser` должен работать и в админке, и в приложении."""

    def test_createsuperuser_gets_platform_role_and_can_log_in(self):
        user = User.objects.create_superuser(username='platform_admin', password='Str0ng!Pass9')
        self.assertEqual(user.role, User.Role.SUPERADMIN)   # роль платформы, не worker
        self.assertTrue(user.is_staff)                      # доступ к /admin/
        self.assertTrue(user.is_superuser)
        self.assertIsNone(user.company_id)                  # супер-админ вне компаний

        resp = self.client.post(LOGIN_API, {
            'username': 'platform_admin', 'password': 'Str0ng!Pass9',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('access', resp.json()['tokens'])

    def test_pages_still_open_after_superuser_exists(self):
        User.objects.create_superuser(username='platform_admin2', password='Str0ng!Pass9')
        self.assertEqual(self.client.get(LOGIN_PAGE).status_code, 200)
        self.assertEqual(self.client.get(KEY_PAGE).status_code, 200)


class BrandAssetsTests(TestCase):
    def test_manifest_icons_exist_on_disk(self):
        # manifest.json ссылался на /static/images/logo.png, которого нет (404 в проде).
        import json
        from pathlib import Path

        from django.conf import settings

        static_dir = Path(settings.STATICFILES_DIRS[0])
        manifest = json.loads((static_dir / 'manifest.json').read_text(encoding='utf-8'))
        for icon in manifest['icons']:
            rel = icon['src'].replace('/static/', '')
            self.assertTrue((static_dir / rel).is_file(),
                            f'иконка манифеста отсутствует: {icon["src"]}')
