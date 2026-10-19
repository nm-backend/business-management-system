"""SPA routes use hash URLs; unknown server paths must remain real 404s."""
from django.test import TestCase


class SpaFallbackTests(TestCase):
    # CSRF-проверки включены: test client иначе не воспроизводит баг,
    # при котором POST-мусор под /api/ отдавал 403-страницу Django.
    def setUp(self):
        from django.test import Client
        self.client = Client(enforce_csrf_checks=True)
    def test_unknown_get_path_returns_custom_404(self):
        for path in ('/orders/', '/orders/123/detail/', '/warehouse', '/что-то-неправильно/'):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 404, f'{path}: {resp.status_code}')
            self.assertContains(resp, 'Саҳифа топилмади', status_code=404)
            self.assertContains(resp, 'href="/"', status_code=404)

    def test_known_pages_still_resolve(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/accounts/login/').status_code, 200)
        self.assertEqual(self.client.get('/accounts/setup/').status_code, 200)

    def test_non_get_method_not_masked(self):
        self.assertEqual(self.client.post('/orders/', {}).status_code, 404)
        self.assertEqual(self.client.put('/orders/1/', '{}', content_type='application/json').status_code, 404)

    def test_api_404_not_masked(self):
        self.assertEqual(self.client.get('/api/v1/nonexistent-endpoint/').status_code, 404)

    def test_openapi_ui_routes_resolve(self):
        self.assertEqual(self.client.get('/api/v1/schema/').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/swagger/').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/redoc/').status_code, 200)

    def test_accounts_me_requires_authentication(self):
        self.assertEqual(self.client.get('/api/v1/accounts/me/').status_code, 401)

    def test_admin_route_is_not_captured_by_spa(self):
        self.assertIn(self.client.get('/admin/').status_code, (200, 302))

    def test_error_views_render_standalone_pages(self):
        from django.test import RequestFactory
        from skladpro.error_views import error_403, error_500

        request = RequestFactory().get('/')
        forbidden = error_403(request)
        server_error = error_500(request)

        self.assertEqual(forbidden.status_code, 403)
        self.assertContains(forbidden, 'Кириш тақиқланган', status_code=403)
        self.assertEqual(server_error.status_code, 500)
        self.assertContains(server_error, 'Сервер хатолиги', status_code=500)

    def test_post_garbage_under_api_prefix_is_404_not_csrf_page(self):
        """csrf_exempt на fallback: POST-мусор по несуществующему пути
        должен давать честную 404, а не Django-страницу «CSRF cookie not set».
        Раньше CsrfViewMiddleware срабатывал раньше исключений fallback,
        и /api/v1/whatever/ с POST отдавал 403 + простыню системного текста."""
        for path in ('/api/v1/nonexistent/', '/api/v1/warehouse/materials/',
                     '/api/v1/orders/999999/', '/api/v1/abc'):
            resp = self.client.post(path, {'name': 'x'}, content_type='application/json')
            self.assertEqual(resp.status_code, 404, f'{path}: {resp.status_code}')
            self.assertNotIn('CSRF', resp.content.decode('utf-8', 'replace'),
                             f'{path} вернул CSRF-страницу')

    def test_media_static_still_served_via_static(self):
        """static()/media-паттерны идут ДО fallback, иначе файлы не раздаются."""
        from django.conf import settings
        for url in ('/media/nonexistent-file.png', '/static/nonexistent.css'):
            resp = self.client.get(url)
            self.assertNotIn(resp.status_code, (200,), f'{url} не должен маскироваться fallback')
        self.assertTrue(hasattr(settings, 'MEDIA_ROOT'))
