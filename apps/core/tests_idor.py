"""
Регрессионные тесты IDOR / Broken Access Control (ЭТАП 2).

Фиксируют доказанное пентестом поведение: сотрудник компании A не может
прочитать, изменить или удалить объект компании B по прямому ID; аноним не
получает ничего; поля company/role/id нельзя подменить через PATCH
(mass assignment); работник не может повысить себе роль.

Тесты намеренно проверяют КОДЫ ОТВЕТА, а не текст — чтобы поймать регрессию,
если queryset перестанут фильтровать по компании.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import Skill, User
from apps.companies.models import Company

PASSWORD = 'Str0ng!Pass9'
SAFE = {401, 403, 404, 405}  # «чужое недоступно»


def make_company(name):
    company = Company.objects.create(name=name)
    owner = User.objects.create_user(username=f'{name}_o', password=PASSWORD, role=User.Role.OWNER, company=company)
    worker = User.objects.create_user(username=f'{name}_w', password=PASSWORD, role=User.Role.WORKER, company=company)
    return company, owner, worker


class IDORIsolationTests(TestCase):
    """Объекты компании B недоступны владельцу компании A по прямому ID."""

    def setUp(self):
        self.A, self.a_owner, self.a_worker = make_company('IdorA')
        self.B, self.b_owner, self.b_worker = make_company('IdorB')

        from apps.clients.models import Client as Cl
        from apps.finance.models import Expense, WorkerPayment
        from apps.messaging.models import Notification
        from apps.messaging.services import ensure_general_conversation
        from apps.orders.models import Order
        from apps.production.models import Task, WorkRecord
        from apps.warehouse.models import FinishedProduct, RawMaterial

        b_client = Cl.objects.create(company=self.B, name='ClientB')
        b_mat = RawMaterial.objects.create(company=self.B, name='MatB', quantity=Decimal('5'))
        b_prod = FinishedProduct.objects.create(company=self.B, name='ProdB', quantity=Decimal('5'))
        b_order = Order.objects.create(
            company=self.B, client=b_client, product=b_prod,
            quantity=Decimal('1'), unit='izdelie', deadline=datetime.date(2026, 1, 1),
        )
        self.targets = {
            '/api/v1/accounts/skills/{}/': Skill.objects.create(company=self.B, name='SkillB').pk,
            '/api/v1/clients/clients/{}/': b_client.pk,
            '/api/v1/warehouse/raw-materials/{}/': b_mat.pk,
            '/api/v1/warehouse/finished-products/{}/': b_prod.pk,
            '/api/v1/orders/orders/{}/': b_order.pk,
            '/api/v1/production/tasks/{}/': Task.objects.create(
                company=self.B, order=b_order, worker=self.b_worker, assigned_by=self.b_owner).pk,
            '/api/v1/production/works/{}/': WorkRecord.objects.create(
                company=self.B, worker=self.b_worker, product=b_prod, quantity=Decimal('1')).pk,
            '/api/v1/finance/expenses/{}/': Expense.objects.create(
                company=self.B, category='rent', amount=Decimal('100'),
                date=datetime.date(2026, 1, 1), created_by=self.b_owner).pk,
            '/api/v1/finance/worker-payments/{}/': WorkerPayment.objects.create(
                company=self.B, worker=self.b_worker, amount=Decimal('50'),
                payment_date=datetime.date(2026, 1, 1), created_by=self.b_owner).pk,
            '/api/v1/messaging/notifications/{}/': Notification.objects.create(
                company=self.B, user=self.b_owner, type='new_order', title='t', message='secretB').pk,
            '/api/v1/messaging/conversations/{}/': ensure_general_conversation(self.B).pk,
            '/api/v1/accounts/users/{}/': self.b_worker.pk,
        }

        self.api = APIClient()
        self.api.force_authenticate(user=self.a_owner)

    def test_cannot_read_other_company_objects(self):
        for tpl, pk in self.targets.items():
            with self.subTest(endpoint=tpl):
                self.assertIn(self.api.get(tpl.format(pk)).status_code, SAFE)

    def test_cannot_modify_other_company_objects(self):
        for tpl, pk in self.targets.items():
            with self.subTest(endpoint=tpl):
                self.assertIn(self.api.patch(tpl.format(pk), {}, format='json').status_code, SAFE)

    def test_cannot_delete_other_company_objects(self):
        for tpl, pk in self.targets.items():
            with self.subTest(endpoint=tpl):
                self.assertIn(self.api.delete(tpl.format(pk)).status_code, SAFE)

    def test_anonymous_gets_nothing(self):
        anon = APIClient()
        for tpl in self.targets:
            list_url = tpl.format(1).rsplit('/', 2)[0] + '/'
            with self.subTest(endpoint=list_url):
                self.assertIn(anon.get(list_url).status_code, {401, 403})


class MassAssignmentTests(TestCase):
    """Служебные поля нельзя подменить через PATCH."""

    def setUp(self):
        self.A, self.a_owner, self.a_worker = make_company('MassA')
        self.B, self.b_owner, _ = make_company('MassB')
        self.api = APIClient()
        self.api.force_authenticate(user=self.a_owner)

    def test_cannot_move_employee_to_other_company(self):
        self.api.patch(f'/api/v1/accounts/users/{self.a_worker.pk}/',
                       {'company': self.B.pk}, format='json')
        self.a_worker.refresh_from_db()
        self.assertEqual(self.a_worker.company_id, self.A.pk)

    def test_cannot_change_role_via_patch(self):
        self.api.patch(f'/api/v1/accounts/users/{self.a_worker.pk}/',
                       {'role': 'owner'}, format='json')
        self.a_worker.refresh_from_db()
        self.assertEqual(self.a_worker.role, User.Role.WORKER)

    def test_cannot_change_id_via_patch(self):
        original = self.a_worker.pk
        self.api.patch(f'/api/v1/accounts/users/{original}/', {'id': 9999}, format='json')
        self.a_worker.refresh_from_db()
        self.assertEqual(self.a_worker.pk, original)


class PrivilegeEscalationTests(TestCase):
    """Работник не может повысить себе права."""

    def setUp(self):
        self.A, self.a_owner, self.a_worker = make_company('PrivA')
        self.api = APIClient()
        self.api.force_authenticate(user=self.a_worker)

    def test_worker_cannot_self_promote_via_me(self):
        resp = self.api.patch('/api/v1/accounts/me/', {'role': 'admin'}, format='json')
        self.a_worker.refresh_from_db()
        self.assertEqual(resp.status_code, 200)          # запрос принят,
        self.assertEqual(self.a_worker.role, User.Role.WORKER)  # но роль не изменилась

    def test_worker_cannot_patch_users_endpoint(self):
        resp = self.api.patch(f'/api/v1/accounts/users/{self.a_worker.pk}/',
                              {'role': 'admin'}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_worker_cannot_grant_himself_permissions(self):
        self.api.patch('/api/v1/accounts/me/',
                       {'can_create_workers': True, 'can_write_to_owner': True}, format='json')
        self.a_worker.refresh_from_db()
        self.assertFalse(self.a_worker.can_create_workers)
