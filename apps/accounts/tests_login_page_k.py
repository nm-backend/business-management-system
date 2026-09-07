"""
Первый экран — только вход, и никакой регистрации.

SkladPro.Nod — закрытая корпоративная система: пользователь не создаёт себе
аккаунт сам. На экране входа допустимы ровно два способа ВОЙТИ:
  1) логин и пароль;
  2) ключ доступа (Access Key), выданный владельцем/администратором, —
     аккаунт при этом уже существует, сотрудник только задаёт себе пароль.

Тест держит границу с двух сторон: способы входа присутствуют, а публичной
регистрации нет ни в UI, ни в маршрутах API.
"""
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company


class LoginScreenTests(TestCase):
    def setUp(self):
        self.html = self.client.get(reverse('login-page')).content.decode('utf-8')

    def test_page_renders(self):
        response = self.client.get(reverse('login-page'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/login.html')

    def test_has_credentials_login(self):
        self.assertIn('id="login-form"', self.html)
        self.assertIn('id="username"', self.html)
        self.assertIn('id="password"', self.html)
        self.assertIn('auth.login_button', self.html)

    def test_has_access_key_login(self):
        """Второй разрешённый способ входа — по выданному ключу доступа."""
        self.assertIn('id="access-key-panel"', self.html)
        self.assertIn('id="show-access-key"', self.html)
        self.assertIn('access-key/verify', self.html)
        self.assertIn('access-key/redeem', self.html)

    def test_no_registration_ui(self):
        """Ни «Регистрация», ни «Создать аккаунт», ни ссылок на signup."""
        lowered = self.html.lower()
        for marker in ('register', 'signup', 'sign-up', 'sign up',
                       'регистрац', 'создать аккаунт', 'setup/owner'):
            # Сообщение короткое: страница целиком в ошибке нечитаема.
            self.assertNotIn(marker, lowered, f'на экране входа найдено «{marker}»'[:120])


class NoPublicRegistrationApiTests(TestCase):
    """Публичной регистрации нет и в API — проверяем маршруты, а не только UI."""

    def test_no_signup_routes(self):
        from django.urls import NoReverseMatch, reverse as django_reverse

        for name in ('register', 'signup', 'sign-up', 'user-register'):
            with self.assertRaises(NoReverseMatch):
                django_reverse(name)

    def test_common_signup_paths_are_404(self):
        api = APIClient()
        for path in ('/api/v1/accounts/register/', '/api/v1/accounts/signup/',
                     '/api/v1/register/', '/api/v1/signup/'):
            response = api.post(path, {
                'username': 'intruder', 'password': 'Str0ng!Pass9',
            }, format='json')
            self.assertEqual(response.status_code, 404, f'{path} отвечает {response.status_code}')
        self.assertFalse(User.objects.filter(username='intruder').exists())

    def test_bootstrap_setup_blocked_once_any_user_exists(self):
        """
        Публичный bootstrap владельца закрывается, как только в системе есть
        хотя бы один пользователь.

        Раньше он проверял только наличие супер-администратора: в компании с
        владельцем и работниками, но без платформенного супер-админа, любой
        аноним мог создать себе супер-аккаунт.
        """
        company = Company.objects.create(name='Granit')
        User.objects.create_user(
            username='owner', password='pw', role=User.Role.OWNER, company=company,
        )
        api = APIClient()
        response = api.post('/api/v1/accounts/setup/owner/', {
            'username': 'intruder', 'password': 'Str0ng!Pass9',
            'password_confirm': 'Str0ng!Pass9', 'full_name': 'Intruder',
        }, format='json')
        self.assertEqual(response.status_code, 403, response.data)
        self.assertFalse(User.objects.filter(username='intruder').exists())

    def test_setup_check_reports_closed_when_users_exist(self):
        company = Company.objects.create(name='Granit')
        User.objects.create_user(
            username='owner2', password='pw', role=User.Role.OWNER, company=company,
        )
        response = APIClient().get('/api/v1/accounts/setup/check/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['setup_required'])
