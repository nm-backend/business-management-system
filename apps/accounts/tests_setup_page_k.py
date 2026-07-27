"""
Свежая установка должна быть проходимой (критический баг с боевого сервера).

БЫЛО: setup_view показывается, только пока нет ни одного супер-админа, но в
шаблоне стояла форма ВВОДА КОДА ДОСТУПА. Кода не существует (пользователей ноль,
выдать некому), а /accounts/login/ редиректит на /accounts/setup/ — попасть в
систему после деплоя было невозможно. Воспроизведено на проде.

СТАЛО: страница показывает форму создания супер-администратора, после создания
вход работает, а сама страница закрывается редиректом на логин.
"""
from django.test import TestCase

from apps.accounts.models import User

SETUP_PAGE = '/accounts/setup/'
LOGIN_PAGE = '/accounts/login/'
SETUP_API = '/api/v1/accounts/setup/owner/'
LOGIN_API = '/api/v1/accounts/login/'

CREDS = {
    'username': 'platform_admin',
    'full_name': 'Платформенный администратор',
    'phone': '+996700000000',
    'password': 'Str0ng!Pass9',
    'password_confirm': 'Str0ng!Pass9',
}


class FreshInstallSetupPageTests(TestCase):
    def test_setup_page_offers_admin_creation_not_access_key(self):
        resp = self.client.get(SETUP_PAGE)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        # Форма создания администратора присутствует...
        self.assertIn('id="setup-form"', html)
        self.assertIn('setup.create_owner', html)
        self.assertIn('id="password-confirm"', html)
        self.assertIn('/accounts/setup/owner/', html)
        # ...а тупиковая форма кода доступа — нет.
        self.assertNotIn('SKP-XXXX-XXXX-XXXX', html)
        self.assertNotIn('ak-verify-form', html)

    def test_full_first_login_flow(self):
        # 1. Создание супер-администратора через API формы.
        resp = self.client.post(SETUP_API, CREDS, content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertIn('access', resp.json()['tokens'])

        user = User.objects.get(username=CREDS['username'])
        self.assertEqual(user.role, User.Role.SUPERADMIN)
        self.assertTrue(user.is_staff)       # нужен для входа в /admin/
        self.assertTrue(user.is_superuser)

        # 2. Обычный вход логином/паролем работает.
        resp = self.client.post(LOGIN_API, {
            'username': CREDS['username'], 'password': CREDS['password'],
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('access', resp.json()['tokens'])

        # 3. Страница настройки закрывается, а публичный эндпоинт больше не даёт
        #    завести ВТОРОГО супер-админа (иначе любой аноним получил бы права).
        self.assertRedirects(self.client.get(SETUP_PAGE), LOGIN_PAGE,
                             fetch_redirect_response=False)
        resp = self.client.post(SETUP_API, dict(CREDS, username='second_admin'),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(User.objects.filter(role=User.Role.SUPERADMIN).count(), 1)

    def test_password_mismatch_rejected(self):
        bad = dict(CREDS, password_confirm='Different!Pass9')
        resp = self.client.post(SETUP_API, bad, content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(User.objects.filter(username=CREDS['username']).exists())


class BrandAssetsTests(TestCase):
    def test_pages_reference_existing_logo(self):
        # manifest.json ссылался на /static/images/logo.png, которого нет (404 в проде).
        from pathlib import Path
        import json
        from django.conf import settings

        static_dir = Path(settings.STATICFILES_DIRS[0])
        self.assertTrue((static_dir / 'img' / 'logo.svg').is_file())

        manifest = json.loads((static_dir / 'manifest.json').read_text(encoding='utf-8'))
        for icon in manifest['icons']:
            rel = icon['src'].replace('/static/', '')
            self.assertTrue((static_dir / rel).is_file(), f'иконка манифеста отсутствует: {icon["src"]}')

    def test_setup_page_shows_logo(self):
        html = self.client.get(SETUP_PAGE).content.decode()
        self.assertIn('img/logo.svg', html)
