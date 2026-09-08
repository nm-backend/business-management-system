"""
Плановое количество задачи (макет «Ишни бажариш»: план 5 дона / факт 3).

Раньше плановый объём знал только заказ, а самостоятельная задача — вообще
никто: при сдаче сравнить факт с планом было не с чем.

Важно: план НЕ участвует в расчётах. Начисление считается по фактически
сданному количеству (ТЗ: «Начислено = количество работы × цена труда»), и
превышение плана работу не блокирует — в цеху бывает и перевыполнение.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.finance.models import LaborRate
from apps.orders.models import Order
from apps.production.models import Task, TaskStatus, WorkRecord
from apps.warehouse.models import FinishedProduct

TASKS = '/api/v1/production/tasks/'


class TaskPlannedQuantityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='PlanCo')
        cls.owner = User.objects.create_user(
            username='pq_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='pq_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='pq_worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )
        cls.product = FinishedProduct.objects.create(
            company=cls.company, name='Столешница', unit='sht', quantity=Decimal('0'),
        )
        LaborRate.objects.create(
            company=cls.company, product=cls.product,
            operation=LaborRate.OperationType.CUTTING,
            rate_per_unit=Decimal('100.00'), unit='sht',
        )
        cls.client_obj = Client.objects.create(company=cls.company, name='Акбаров')
        cls.order = Order.objects.create(
            company=cls.company, client=cls.client_obj, product=cls.product,
            quantity=Decimal('5'), unit='sht', total_amount=Decimal('1000.00'),
            deadline=timezone.now() + timezone.timedelta(days=3),
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_plan_saved_explicitly(self):
        response = self.api.post(TASKS, {
            'order': self.order.id, 'worker': self.worker.id, 'title': 'Столешница',
            'planned_quantity': '3', 'planned_unit': 'sht',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        task = Task.objects.get(pk=response.data['id'])
        self.assertEqual(task.planned_quantity, Decimal('3.000'))
        self.assertEqual(task.planned_unit, 'sht')

    def test_plan_defaults_from_order(self):
        """План не указали — берём объём заказа, а не оставляем пустым."""
        response = self.api.post(TASKS, {
            'order': self.order.id, 'worker': self.worker.id, 'title': 'Столешница',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        task = Task.objects.get(pk=response.data['id'])
        self.assertEqual(task.planned_quantity, Decimal('5.000'))
        self.assertEqual(task.planned_unit, 'sht')

    def test_self_assigned_task_without_plan_is_valid(self):
        """Самостоятельная работа работника плана не требует."""
        api = APIClient()
        api.force_authenticate(self.worker)
        response = api.post(TASKS, {'worker': self.worker.id}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(Task.objects.get(pk=response.data['id']).planned_quantity)

    def test_worker_sees_plan_but_cannot_change_it(self):
        task = Task.objects.create(
            company=self.company, order=self.order, worker=self.worker,
            assigned_by=self.owner, status=TaskStatus.ACCEPTED, title='Столешница',
            planned_quantity=Decimal('5'), planned_unit='sht',
        )
        api = APIClient()
        api.force_authenticate(self.worker)

        rows = api.get(TASKS).data
        rows = rows['results'] if 'results' in rows else rows
        self.assertEqual(Decimal(str(rows[0]['planned_quantity'])), Decimal('5.000'))

        response = api.patch(f'{TASKS}{task.id}/', {'planned_quantity': '999'}, format='json')
        self.assertEqual(response.status_code, 403, 'работник не может править план')
        task.refresh_from_db()
        self.assertEqual(task.planned_quantity, Decimal('5.000'))

    def test_zero_plan_rejected(self):
        response = self.api.post(TASKS, {
            'order': self.order.id, 'worker': self.worker.id, 'title': 'X',
            'planned_quantity': '0',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_overperformance_is_allowed_and_paid_by_fact(self):
        """
        Сдал больше плана — работа принимается, начисление по факту.

        План носит справочный характер; блокировать перевыполнение нельзя,
        иначе рабочий не сможет сдать реально сделанное.
        """
        task = Task.objects.create(
            company=self.company, order=self.order, worker=self.worker,
            assigned_by=self.owner, status=TaskStatus.ACCEPTED, title='Столешница',
            planned_quantity=Decimal('3'), planned_unit='sht',
        )
        api = APIClient()
        api.force_authenticate(self.worker)
        response = api.post('/api/v1/production/works/', {
            'task': task.id, 'product': self.product.id,
            'quantity': '5', 'unit': 'sht', 'operation': 'cutting',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)

        work = WorkRecord.objects.get(pk=response.data['id'])
        self.api.post(f'/api/v1/production/works/{work.id}/confirm/', {}, format='json')
        work.refresh_from_db()
        self.assertEqual(work.labor_cost, Decimal('500.00'), 'оплата по факту, не по плану')

    def test_plan_not_leaked_across_tenants(self):
        other = Company.objects.create(name='OtherPlanCo')
        other_owner = User.objects.create_user(
            username='pq_other', password='pw', role=User.Role.OWNER, company=other,
        )
        Task.objects.create(
            company=self.company, order=self.order, worker=self.worker,
            assigned_by=self.owner, title='Своя', planned_quantity=Decimal('7'),
        )
        api = APIClient()
        api.force_authenticate(other_owner)
        rows = api.get(TASKS).data
        rows = rows['results'] if 'results' in rows else rows
        self.assertEqual(rows, [])
