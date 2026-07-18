"""
Регрессионные тесты SQLi / XSS / некорректных query-параметров (ЭТАП 3).

ПОДТВЕРЖДЁННЫЙ БАГ (исправлен): нечисловые ?skill= и ?worker= доходили до ORM
и вызывали ValueError -> HTTP 500. Любой авторизованный пользователь мог уронить
обработчик одним GET. Теперь — 400.

SQLi и XSS воспроизвести не удалось (ORM параметризует запросы, Django-шаблоны
и format_html экранируют, фронтенд использует window.ui.escape) — тесты ниже
фиксируют это поведение, чтобы регрессия была видна сразу.
"""
from django.test import Client, TestCase
from rest_framework.test import APIClient

from apps.accounts.models import Skill, User
from apps.companies.models import Company

SQLI_PAYLOADS = ["' OR '1'='1", "'; DROP TABLE accounts_user; --", "1;--", "%'"]
XSS_PAYLOAD = '<script>alert(1)</script>'


def make_env(name):
    company = Company.objects.create(name=name)
    owner = User.objects.create_user(username=f'{name}_o', password='Str0ng!Pass9',
                                     role=User.Role.OWNER, company=company)
    worker = User.objects.create_user(username=f'{name}_w', password='Str0ng!Pass9',
                                      role=User.Role.WORKER, company=company)
    return company, owner, worker


class InvalidQueryParamTests(TestCase):
    """Регрессия подтверждённого бага: 400 вместо 500."""

    def setUp(self):
        self.company, self.owner, self.worker = make_env('InjA')
        self.api = APIClient()
        self.api.force_authenticate(user=self.owner)

    def test_skill_filter_rejects_non_numeric(self):
        for bad in ['abc', "' OR '1'='1", '1;--', '']:
            with self.subTest(skill=bad):
                resp = self.api.get('/api/v1/accounts/users/', {'skill': bad})
                self.assertNotEqual(resp.status_code, 500)
                if bad:
                    self.assertEqual(resp.status_code, 400)

    def test_skill_filter_accepts_numeric(self):
        skill = Skill.objects.create(company=self.company, name='Python')
        resp = self.api.get('/api/v1/accounts/users/', {'skill': skill.pk})
        self.assertEqual(resp.status_code, 200)

    def test_worker_payment_filter_rejects_non_numeric(self):
        for bad in ['abc', "' OR '1'='1"]:
            with self.subTest(worker=bad):
                resp = self.api.get('/api/v1/finance/worker-payments/', {'worker': bad})
                self.assertNotEqual(resp.status_code, 500)
                self.assertEqual(resp.status_code, 400)

    def test_worker_payment_filter_accepts_numeric(self):
        resp = self.api.get('/api/v1/finance/worker-payments/', {'worker': self.worker.pk})
        self.assertEqual(resp.status_code, 200)


class SQLInjectionTests(TestCase):
    """SQLi воспроизвести не удалось — фиксируем защиту ORM."""

    def setUp(self):
        self.company, self.owner, _ = make_env('InjB')
        Skill.objects.create(company=self.company, name='Python')
        self.api = APIClient()
        self.api.force_authenticate(user=self.owner)

    def test_search_payloads_are_treated_as_plain_text(self):
        for payload in SQLI_PAYLOADS:
            for url in ['/api/v1/accounts/skills/', '/api/v1/accounts/users/',
                        '/api/v1/clients/clients/', '/api/v1/warehouse/raw-materials/']:
                with self.subTest(url=url, payload=payload):
                    resp = self.api.get(url, {'search': payload})
                    self.assertEqual(resp.status_code, 200)

    def test_ordering_payload_does_not_break(self):
        for payload in SQLI_PAYLOADS:
            with self.subTest(payload=payload):
                self.assertEqual(
                    self.api.get('/api/v1/accounts/users/', {'ordering': payload}).status_code, 200)

    def test_tables_survive_drop_attempts(self):
        self.api.get('/api/v1/accounts/users/', {'search': "'; DROP TABLE accounts_user; --"})
        self.assertTrue(User.objects.exists())
        self.assertTrue(Skill.objects.exists())


class XSSEscapingTests(TestCase):
    """XSS воспроизвести не удалось — фиксируем экранирование в HTML-стоках."""

    def setUp(self):
        self.company, self.owner, self.worker = make_env('InjC')
        self.api = APIClient()
        self.api.force_authenticate(user=self.owner)

    def test_payload_is_stored_but_escaped_in_admin(self):
        self.api.post('/api/v1/accounts/skills/', {'name': XSS_PAYLOAD}, format='json')
        from apps.messaging.services import ensure_general_conversation
        conv = ensure_general_conversation(self.company)
        self.api.post('/api/v1/messaging/messages/',
                      {'conversation': conv.pk, 'content': XSS_PAYLOAD}, format='json')
        self.worker.full_name = XSS_PAYLOAD
        self.worker.save()

        superadmin = User.objects.create_superuser(username='inj_root', password='pw12345X')
        web = Client()
        web.force_login(superadmin)
        for url in ['/admin/accounts/skill/', '/admin/messaging/chatmessage/',
                    '/admin/accounts/user/']:
            with self.subTest(url=url):
                html = web.get(url).content.decode()
                self.assertNotIn(XSS_PAYLOAD, html)      # сырой скрипт не попал в HTML
                self.assertIn('&lt;script&gt;', html)     # он экранирован

    def test_api_returns_json_not_html(self):
        """API отдаёт JSON — payload там не является исполняемым контекстом."""
        resp = self.api.get('/api/v1/accounts/skills/')
        self.assertEqual(resp['Content-Type'], 'application/json')
