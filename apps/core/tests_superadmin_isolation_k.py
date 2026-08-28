"""
SuperAdmin = платформа, а не бизнес конкретной компании.

Скрытие пунктов меню в CSS/JS не считается защитой: проверяем сервер. Токен
супер-админа (company=None) обязан получать 403 на ВСЕ бизнес-эндпоинты
(заказы, склад, производство, клиенты, финансы, отчёты, аудит) и 200 только
на платформенные (компании, статистика, подписки).
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company


class SuperAdminIsolationTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_superuser(username='root', password='pw')
        self.company = Company.objects.create(name='Acme')
        self.api = APIClient()
        self.api.force_authenticate(self.superadmin)

    def test_business_endpoints_forbidden(self):
        business_urls = [
            '/api/v1/orders/orders/',
            '/api/v1/warehouse/raw-materials/',
            '/api/v1/warehouse/finished-products/',
            '/api/v1/warehouse/recipes/',
            '/api/v1/production/tasks/',
            '/api/v1/production/works/',
            '/api/v1/clients/clients/',
            '/api/v1/clients/payments/',
            '/api/v1/finance/expenses/',
            '/api/v1/finance/worker-payments/',
            '/api/v1/finance/labor-rates/',
            '/api/v1/reports/analytics/owner/',
            '/api/v1/reports/analytics/admin/',
            '/api/v1/audit/logs/',
        ]
        for url in business_urls:
            resp = self.api.get(url)
            self.assertIn(
                resp.status_code, (403, 404),
                f'{url}: ожидался запрет (403), получено {resp.status_code}',
            )

    def test_platform_endpoints_allowed(self):
        for url in (
            '/api/v1/companies/',
            '/api/v1/companies/stats/',
            '/api/v1/companies/plans/',
            '/api/v1/billing/subscriptions/',
            '/api/v1/accounts/me/',
        ):
            resp = self.api.get(url)
            self.assertEqual(resp.status_code, 200, f'{url}: {resp.status_code}')

    def test_superadmin_cannot_touch_company_business_data(self):
        """Даже с известным id бизнес-объекта компании супер-админ получает отказ."""
        from apps.clients.models import Client
        client = Client.objects.create(company=self.company, name='Клиент')
        resp = self.api.get(f'/api/v1/clients/clients/{client.id}/')
        self.assertIn(resp.status_code, (403, 404), 'супер-админ не должен видеть клиента компании')
        resp = self.api.delete(f'/api/v1/clients/clients/{client.id}/')
        self.assertIn(resp.status_code, (403, 404), 'супер-админ не должен удалять клиента компании')

    def test_superadmin_users_list_is_empty(self):
        """Список сотрудников компаний для супер-админа пуст (нет утечки)."""
        from apps.accounts.models import User
        User.objects.create_user(username='emp', password='p',
                                 role=User.Role.WORKER, company=self.company)
        resp = self.api.get('/api/v1/accounts/users/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['count'], 0)
