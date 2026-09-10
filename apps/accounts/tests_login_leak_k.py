"""
Экран входа не должен показывать служебные комментарии шаблона.

Воспроизведено на проде: комментарий к шаблону был записан «однострочным»
синтаксисом `{# … #}`, но занимал МНОГО строк. Регулярное выражение лексера
Django не работает через переводы строк, поэтому весь служебный текст
(«Экран входа (макет «Кириш»)…») вываливался на страницу входа как обычный
контент. Комментарий переписан парным тегом comment/endcomment — здесь
фиксируем, что на странице нет ни «решёточных» артефактов, ни текста.
"""
from django.test import TestCase


class LoginPageNoLeakedCommentsTests(TestCase):
    def _page(self):
        return self.client.get('/accounts/login/')

    def test_login_page_ok(self):
        response = self._page()
        self.assertEqual(response.status_code, 200)

    def test_no_template_comment_artifacts(self):
        """Ни открывающих `{#`, ни парных тегов в отрендеренном HTML нет."""
        content = self._page().content.decode('utf-8')
        self.assertNotIn('{#', content)
        self.assertNotIn('#}', content)
        self.assertNotIn('{%', content)

    def test_no_leaked_design_note_text(self):
        """Конкретный утёкший текст (воспроизведённый на проде) отсутствует."""
        content = self._page().content.decode('utf-8')
        leaked_fragments = [
            'Экран входа (макет',
            'Ровно два способа ВОЙТИ',
            'закрытая корпоративная система',
            'tests_login_page_k.py',
        ]
        for fragment in leaked_fragments:
            self.assertNotIn(fragment, content)

    def test_both_login_ways_present(self):
        """Ровно два способа войти: пароль и ключ доступа, регистрации нет."""
        content = self._page().content.decode('utf-8')
        self.assertIn('login-form', content)
        self.assertIn('ak-verify-form', content)
        self.assertNotIn('register', content.lower())
