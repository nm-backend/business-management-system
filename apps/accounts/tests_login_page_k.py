"""
Страница входа: только вход.

Требование заказчика и ТЗ: аккаунтов ровно три типа (Эгаси / Администратор /
Ишчи), создаёт их владелец, самостоятельной регистрации нет. Раньше на экране
входа была вторая панель «У меня есть код доступа» — ввод кода, установка
пароля и активация учётной записи, то есть фактически создание аккаунта прямо
на входе. Панель убрана; активация по выданному коду осталась на отдельной
странице /accounts/setup/.
"""
from django.test import TestCase
from django.urls import reverse


class LoginPageIsLoginOnlyTests(TestCase):
    def setUp(self):
        self.html = self.client.get(reverse('login-page')).content.decode('utf-8')

    def test_page_renders(self):
        response = self.client.get(reverse('login-page'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/login.html')

    def test_has_login_form(self):
        self.assertIn('id="login-form"', self.html)
        self.assertIn('id="username"', self.html)
        self.assertIn('id="password"', self.html)
        self.assertIn('auth.login_button', self.html)

    def test_no_account_creation_ui(self):
        """Ни кнопки «есть код доступа», ни форм активации/создания аккаунта."""
        for marker in (
            'show-access-key',       # кнопка перехода к активации
            'access-key-panel',      # панель активации
            'ak-verify-form',        # шаг 1: проверка кода
            'ak-redeem-form',        # шаг 2: установка пароля
            'auth.have_access_key',
            'auth.set_password',
            'access-key/verify',
            'access-key/redeem',
            'setup/owner',
        ):
            self.assertNotIn(marker, self.html, f'на экране входа найдено «{marker}»')

    def test_no_new_password_field(self):
        """Поле «придумайте пароль» — признак регистрации, его быть не должно."""
        self.assertNotIn('autocomplete="new-password"', self.html)
        self.assertIn('autocomplete="current-password"', self.html)

    def test_activation_page_still_available_separately(self):
        """Активация по коду доступна, но отдельной страницей, не на входе."""
        response = self.client.get(reverse('setup-page'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/setup.html')
