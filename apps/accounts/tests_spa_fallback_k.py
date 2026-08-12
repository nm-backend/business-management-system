"""
Аудит K: SPA-fallback — прямой заход на подстраницу не должен давать 404.

Раньше маршрутизацию делал только браузерный роутер со старта на '/':
/orders/, /warehouse/ и т.п. при hard-reload/вставке ссылки извне
отдавали 404. Fallback отдаёт index.html для любых неизвестных GET,
но не маскирует API/admin/static и не обслуживает не-GET методы.
"""
from django.test import TestCase


class SpaFallbackTests(TestCase):
    # CSRF-проверки включены: test client иначе не воспроизводит баг,
    # при котором POST-мусор под /api/ отдавал 403-страницу Django.
    def setUp(self):
        from django.test import Client
        self.client = Client(enforce_csrf_checks=True)
    def test_unknown_get_path_serves_index(self):
        for path in ('/orders/', '/orders/123/detail/', '/warehouse', '/some/deep/page'):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, f'{path}: {resp.status_code}')
            self.assertContains(resp, 'index.html' if False else 'SkladPro',
                                msg_prefix=f'{path} не отдал SPA: ')

    def test_known_pages_still_resolve(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/accounts/login/').status_code, 200)
        self.assertEqual(self.client.get('/accounts/setup/').status_code, 200)

    def test_non_get_method_not_masked(self):
        self.assertEqual(self.client.post('/orders/', {}).status_code, 404)
        self.assertEqual(self.client.put('/orders/1/', '{}', content_type='application/json').status_code, 404)

    def test_api_404_not_masked(self):
        self.assertEqual(self.client.get('/api/v1/nonexistent-endpoint/').status_code, 404)

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
