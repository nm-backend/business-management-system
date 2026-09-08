"""
Тип клиента и ответственный сотрудник (макет «Мижоз картаси»).

Это не поля «ради макета»: тип определяет форму документов и обращение,
ответственный — кто ведёт клиента. Финансовой логики не касаются, поэтому
видны и администратору — но сумм в его карточке по-прежнему нет.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company

CLIENTS = '/api/v1/clients/clients/'


class ClientProfileFieldsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='ProfileCo')
        cls.owner = User.objects.create_user(
            username='cp_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='cp_admin', password='pw', role=User.Role.ADMIN,
            company=cls.company, full_name='Администратор Бахтиёр',
        )
        cls.worker = User.objects.create_user(
            username='cp_worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def test_defaults_to_individual(self):
        client = Client.objects.create(company=self.company, name='Акбаров')
        self.assertEqual(client.client_type, 'individual')
        self.assertIsNone(client.responsible_employee)

    def test_fields_saved_via_api(self):
        response = self.api_as(self.owner).post(CLIENTS, {
            'name': 'ООО Гранит', 'client_type': 'company',
            'responsible_employee': self.admin.id,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['client_type'], 'company')
        self.assertEqual(response.data['responsible_employee'], self.admin.id)
        self.assertEqual(response.data['responsible_employee_name'], 'Администратор Бахтиёр')
        self.assertTrue(response.data['client_type_display'])

    def test_responsible_from_other_company_rejected(self):
        other = Company.objects.create(name='OtherProfileCo')
        stranger = User.objects.create_user(
            username='cp_stranger', password='pw', role=User.Role.ADMIN, company=other,
        )
        response = self.api_as(self.owner).post(CLIENTS, {
            'name': 'Акбаров', 'responsible_employee': stranger.id,
        }, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('responsible_employee', response.data)

    def test_unknown_client_type_rejected(self):
        response = self.api_as(self.owner).post(CLIENTS, {
            'name': 'Акбаров', 'client_type': 'alien',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_admin_sees_fields_but_no_money(self):
        Client.objects.create(
            company=self.company, name='Акбаров', client_type='company',
            responsible_employee=self.admin, debt=Decimal('5000.00'),
            total_orders_amount=Decimal('9000.00'),
        )
        rows = self.api_as(self.admin).get(CLIENTS).data
        rows = rows['results'] if 'results' in rows else rows
        row = rows[0]
        self.assertEqual(row['client_type'], 'company')
        self.assertEqual(row['responsible_employee'], self.admin.id)
        for money_key in ('debt', 'total_orders_amount', 'total_paid'):
            self.assertNotIn(money_key, row, f'администратору ушло поле {money_key}')

    def test_worker_still_has_no_client_access(self):
        """Права не ослабли: клиентов работник не видит вовсе."""
        self.assertEqual(self.api_as(self.worker).get(CLIENTS).status_code, 403)

    def test_deleting_employee_keeps_client(self):
        """Увольнение сотрудника не должно удалять клиента."""
        client = Client.objects.create(
            company=self.company, name='Акбаров', responsible_employee=self.admin,
        )
        self.admin.delete()
        client.refresh_from_db()
        self.assertIsNone(client.responsible_employee)

    def test_filter_by_responsible(self):
        Client.objects.create(company=self.company, name='Свой', responsible_employee=self.admin)
        Client.objects.create(company=self.company, name='Ничей')
        rows = self.api_as(self.owner).get(CLIENTS, {'responsible_employee': self.admin.id}).data
        rows = rows['results'] if 'results' in rows else rows
        names = [r['name'] for r in rows]
        self.assertIn('Свой', names)
        # Без этой проверки тест прошёл бы и при полностью отсутствующем
        # фильтре: DRF молча игнорирует неизвестный query-параметр.
        self.assertNotIn('Ничей', names, 'фильтр по ответственному не работает')
