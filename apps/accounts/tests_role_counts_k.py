"""
Счётчики ролей (макет «Роллар ва аккаунтлар»: «Егаси 1 киши», «Ишчи 8 киши»).

Семантика: считаем тех, кто РЕАЛЬНО может работать — активных и не
заблокированных. Уволенный или заблокированный сотрудник в счётчике роли не
участвует, иначе владелец видит штат больше фактического.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company

ROLE_COUNTS = '/api/v1/accounts/users/role-counts/'


class RoleCountsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='RolesCo')
        cls.owner = User.objects.create_user(
            username='rc_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='rc_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )
        for index in range(3):
            User.objects.create_user(
                username=f'rc_worker{index}', password='pw',
                role=User.Role.WORKER, company=cls.company,
            )

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def test_counts_reflect_real_accounts(self):
        data = self.api_as(self.owner).get(ROLE_COUNTS).data
        self.assertEqual(data['owner'], 1)
        self.assertEqual(data['admin'], 1)
        self.assertEqual(data['worker'], 3)
        self.assertEqual(data['total'], 5)

    def test_inactive_account_not_counted(self):
        worker = User.objects.filter(company=self.company, role=User.Role.WORKER).first()
        worker.is_active = False
        worker.save(update_fields=['is_active'])

        data = self.api_as(self.owner).get(ROLE_COUNTS).data
        self.assertEqual(data['worker'], 2, 'деактивированный аккаунт попал в счётчик')
        self.assertEqual(data['total'], 4)

    def test_blocked_account_not_counted(self):
        worker = User.objects.filter(company=self.company, role=User.Role.WORKER).last()
        worker.blocked_by_owner = True
        worker.save(update_fields=['blocked_by_owner'])

        data = self.api_as(self.owner).get(ROLE_COUNTS).data
        self.assertEqual(data['worker'], 2, 'заблокированный аккаунт попал в счётчик')

    def test_counts_are_tenant_scoped(self):
        other = Company.objects.create(name='OtherRolesCo')
        for index in range(5):
            User.objects.create_user(
                username=f'other_worker{index}', password='pw',
                role=User.Role.WORKER, company=other,
            )
        data = self.api_as(self.owner).get(ROLE_COUNTS).data
        self.assertEqual(data['worker'], 3, 'посчитаны работники чужой компании')

    def test_superadmin_not_counted_in_company(self):
        User.objects.create_superuser(username='rc_super', password='pw')
        data = self.api_as(self.owner).get(ROLE_COUNTS).data
        self.assertEqual(data['total'], 5)

    def test_admin_can_read_counts(self):
        """Администратор ведёт сотрудников — счётчики ему нужны."""
        self.assertEqual(self.api_as(self.admin).get(ROLE_COUNTS).status_code, 200)

    def test_worker_denied(self):
        worker = User.objects.filter(company=self.company, role=User.Role.WORKER).first()
        self.assertEqual(self.api_as(worker).get(ROLE_COUNTS).status_code, 403)

    def test_anonymous_denied(self):
        self.assertEqual(APIClient().get(ROLE_COUNTS).status_code, 401)

    def test_single_query(self):
        """Счётчики считаются одним запросом, а не перебором ролей."""
        api = self.api_as(self.owner)
        api.get(ROLE_COUNTS)
        with self.assertNumQueries(1):   # ровно один агрегат
            api.get(ROLE_COUNTS)

        # Данных больше — запрос всё равно один.
        for index in range(10):
            User.objects.create_user(
                username=f'rc_extra{index}', password='pw',
                role=User.Role.WORKER, company=self.company,
            )
        with self.assertNumQueries(1):
            api.get(ROLE_COUNTS)
