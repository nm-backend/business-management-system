"""
Страницы ошибок должны быть локализованы НА СЕРВЕРЕ.

Раньше в шаблонах 403/404/500 стоял только data-i18n, а i18n.js на этих
страницах не подключался — пользователь с русским или кыргызским языком
всегда видел узбекский текст. Тесты ниже проверяют фактический текст ответа,
а не наличие атрибута data-i18n.
"""
from pathlib import Path

from django.conf import settings
from django.test import Client, RequestFactory, TestCase

from apps.accounts.models import User
from apps.companies.models import Company
from skladpro.error_views import error_403, error_404, error_500


class ErrorPageLanguageTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='ErrI18nCo', is_active=True)
        self.client = Client()

    def _user(self, username, language):
        return User.objects.create_user(
            username=username, password='p', role=User.Role.OWNER,
            company=self.company, language=language,
        )

    def test_anonymous_default_is_uzbek_cyrillic(self):
        response = self.client.get('/no-such-page-default/')
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Саҳифа топилмади', status_code=404)
        self.assertContains(response, 'lang="uz-Cyrl"', status_code=404)
        self.assertEqual(response['Content-Language'], 'uz_cyrl')

    def test_anonymous_accept_language_russian(self):
        response = self.client.get(
            '/no-such-page-ru/', HTTP_ACCEPT_LANGUAGE='ru-RU,ru;q=0.9',
        )
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Страница не найдена', status_code=404)
        self.assertNotContains(response, 'Саҳифа топилмади', status_code=404)
        self.assertEqual(response['Content-Language'], 'ru')

    def test_anonymous_accept_language_kyrgyz(self):
        response = self.client.get(
            '/no-such-page-ky/', HTTP_ACCEPT_LANGUAGE='ky-KG,ky;q=0.9',
        )
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Баракча табылган жок', status_code=404)

    def test_unsupported_language_falls_back_to_uzbek(self):
        response = self.client.get(
            '/no-such-page-uk/', HTTP_ACCEPT_LANGUAGE='uk-UA,uk;q=0.9',
        )
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Саҳифа топилмади', status_code=404)

    def test_authenticated_user_language_wins_over_header(self):
        self.client.force_login(self._user('err_ru_user', 'ru'))
        response = self.client.get(
            '/no-such-page-user/', HTTP_ACCEPT_LANGUAGE='ky-KG',
        )
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Страница не найдена', status_code=404)

    def test_403_uses_user_language(self):
        request = RequestFactory().get('/')
        request.user = self._user('err_403_user', 'ky')
        response = error_403(request)
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'Кирүүгө тыюу салынган', status_code=403)
        self.assertContains(response, 'lang="ky"', status_code=403)

    def test_500_uses_user_language(self):
        request = RequestFactory().get('/')
        request.user = self._user('err_500_user', 'ru')
        response = error_500(request)
        self.assertEqual(response.status_code, 500)
        self.assertContains(response, 'Ошибка сервера', status_code=500)
        self.assertContains(response, 'На главную страницу', status_code=500)

    def test_error_pages_do_not_depend_on_javascript(self):
        """Требование ТЗ: страницы ошибок работают при отказе JS."""
        user = self._user('err_nojs_user', 'ru')
        request = RequestFactory().get('/')
        request.user = user
        for response in (error_403(request), error_404(request), error_500(request)):
            body = response.content.decode('utf-8')
            self.assertNotIn('<script', body.lower())
            self.assertNotIn('data-i18n', body)


class ErrorPageLocaleKeysTests(TestCase):
    def test_every_language_has_every_page_string(self):
        import json

        locale_dir = Path(settings.BASE_DIR) / 'locale'
        required = {
            'forbidden_title', 'forbidden_detail',
            'not_found_title', 'not_found_detail',
            'server_error_title', 'server_error_detail',
            'back_to_home',
        }
        for lang in ('uz_cyrl', 'ru', 'ky'):
            data = json.loads((locale_dir / f'{lang}.json').read_text(encoding='utf-8'))
            pages = data.get('errors', {}).get('pages', {})
            self.assertEqual(required - set(pages), set(), f'{lang}: пропущены ключи')
            for key in required:
                self.assertTrue(str(pages[key]).strip(), f'{lang}.{key} пуст')
