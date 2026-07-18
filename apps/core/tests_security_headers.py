"""
Регрессионные тесты заголовков безопасности (ЭТАП 1).

Фиксируют доказанное поведение: CSP и Permissions-Policy присутствуют на
страницах приложения, но НЕ применяются к Swagger/ReDoc/Admin (внешний CDN и
собственные inline-скрипты фреймворков), иначе эти инструменты ломаются.
"""
from django.test import Client, TestCase

from apps.accounts.models import User


class SecurityHeadersTests(TestCase):
    def setUp(self):
        self.client = Client()
        # Без супер-админа /accounts/login/ редиректит на /accounts/setup/ и тело
        # пустое — создаём его, чтобы страница входа реально рендерилась.
        User.objects.create_superuser(username='hdr_setup_root', password='pw12345X')

    # ── Заголовки, которые ставит Django (проверяем, что не потеряли) ──
    def test_django_baseline_headers_present(self):
        resp = self.client.get('/accounts/login/')
        self.assertEqual(resp.headers.get('X-Frame-Options'), 'DENY')
        self.assertEqual(resp.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(resp.headers.get('Referrer-Policy'), 'same-origin')

    # ── Новые заголовки ──
    def test_permissions_policy_present(self):
        resp = self.client.get('/accounts/login/')
        policy = resp.headers.get('Permissions-Policy', '')
        self.assertIn('geolocation=()', policy)
        self.assertIn('camera=()', policy)

    def test_csp_present_on_app_pages(self):
        resp = self.client.get('/accounts/login/')
        csp = resp.headers.get('Content-Security-Policy', '')
        self.assertIn("default-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("nonce-", csp)

    def test_csp_allows_websocket_and_fonts(self):
        """Чат и шрифты не должны блокироваться политикой."""
        csp = self.client.get('/accounts/login/').headers.get('Content-Security-Policy', '')
        self.assertIn('ws:', csp)
        self.assertIn('wss:', csp)
        self.assertIn('fonts.gstatic.com', csp)
        self.assertIn('fonts.googleapis.com', csp)

    def test_inline_script_carries_matching_nonce(self):
        """Inline-скрипт страницы входа должен иметь nonce из заголовка CSP."""
        resp = self.client.get('/accounts/login/')
        csp = resp.headers.get('Content-Security-Policy', '')
        nonce = csp.split("'nonce-")[1].split("'")[0]
        self.assertIn(f'nonce="{nonce}"', resp.content.decode())

    def test_nonce_is_unique_per_request(self):
        a = self.client.get('/accounts/login/').headers['Content-Security-Policy']
        b = self.client.get('/accounts/login/').headers['Content-Security-Policy']
        self.assertNotEqual(a, b)

    # ── Исключения (иначе ломаются) ──
    def test_csp_not_applied_to_swagger(self):
        resp = self.client.get('/api/v1/swagger/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('Content-Security-Policy', resp.headers)

    def test_csp_not_applied_to_redoc(self):
        resp = self.client.get('/api/v1/redoc/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('Content-Security-Policy', resp.headers)

    def test_csp_not_applied_to_admin(self):
        superadmin = User.objects.create_superuser(username='hdr_root', password='pw12345X')
        self.client.force_login(superadmin)
        resp = self.client.get('/admin/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('Content-Security-Policy', resp.headers)

    def test_json_api_gets_no_csp(self):
        """CSP нужна для HTML; JSON-ответы её не получают."""
        resp = self.client.get('/api/v1/accounts/setup/check/')
        self.assertNotIn('Content-Security-Policy', resp.headers)
