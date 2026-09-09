"""
Тесты сводки по долгам клиентов (панель «Қарз назорати»).

Раньше панель считалась на фронте по первой странице списка (20 клиентов),
а сумма долга складывалась из строк Decimal («0»+«100.00») → на экране NaN.
Теперь считает сервер по всем неархивным клиентам компании.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company

URL = '/api/v1/clients/clients/debt_summary/'


class ClientDebtSummaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='Granit')
        cls.owner = User.objects.create_user(
            username='owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )

        # 25 должников — больше страницы (PAGE_SIZE=20), чтобы поймать
        # старую ошибку «считаем только первую страницу».
        for i in range(25):
            Client.objects.create(
                company=cls.company, name=f'Клиент {i}', debt=Decimal('100.00'),
                total_orders_amount=Decimal('100.00'),
            )
        Client.objects.create(company=cls.company, name='Без долга', debt=Decimal('0'))
        Client.objects.create(
            company=cls.company, name='Архивный должник',
            debt=Decimal('999.00'), is_archived=True,
        )

        # Чужая компания — её долги не должны попасть в сумму.
        cls.other = Company.objects.create(name='Marmar')
        cls.other_owner = User.objects.create_user(
            username='other_owner', password='pw', role=User.Role.OWNER, company=cls.other,
        )
        Client.objects.create(company=cls.other, name='Чужой', debt=Decimal('50000.00'))

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def test_counts_all_pages_not_just_first(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['debtors_count'], 25)

    def test_total_debt_is_a_number_not_concatenated_string(self):
        response = self.client.get(URL)
        self.assertEqual(Decimal(str(response.data['total_debt'])), Decimal('2500.00'))

    def test_archived_and_zero_debt_excluded(self):
        response = self.client.get(URL)
        # 999 архивного должника не попал в сумму.
        self.assertEqual(Decimal(str(response.data['total_debt'])), Decimal('2500.00'))
        # «Без долга» + архивный (архивные в выборке не участвуют вовсе).
        self.assertEqual(response.data['no_debt_count'], 1)

    def test_top_debtors_returned_sorted(self):
        Client.objects.create(company=self.company, name='Крупный', debt=Decimal('900000.00'))
        response = self.client.get(URL)
        top = response.data['top_debtors']
        self.assertEqual(top[0]['name'], 'Крупный')
        self.assertLessEqual(len(top), 10)

    def test_other_company_debts_not_included(self):
        response = self.client.get(URL)
        self.assertEqual(Decimal(str(response.data['total_debt'])), Decimal('2500.00'))

    def test_admin_forbidden(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        self.assertEqual(client.get(URL).status_code, 403)

    def test_worker_forbidden(self):
        client = APIClient()
        client.force_authenticate(self.worker)
        self.assertEqual(client.get(URL).status_code, 403)

    def test_anonymous_unauthorized(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)

    def test_overdue_buckets_present(self):
        """Панель «Қарз назорати» рисует бакеты из этого payload."""
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        buckets = response.data['buckets']
        for name in ('not_due', 'overdue_1_7', 'overdue_8_14', 'overdue_15_plus'):
            self.assertIn(name, buckets)
            self.assertIn('count', buckets[name])
            self.assertIn('total', buckets[name])
            self.assertIn('orders', buckets[name])
