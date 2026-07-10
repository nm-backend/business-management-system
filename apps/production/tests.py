"""
Unit-тесты для приложения production: жизненный цикл Task
(accept/refuse/complete/confirm) и WorkRecord (confirm/reject/
calculate_labor_cost, свойство is_confirmed).
"""
import datetime
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import User
from apps.clients.models import Client
from apps.finance.models import LaborRate
from apps.orders.models import Order, OrderStatus
from apps.production.models import Task, TaskStatus, WorkRecord
from apps.warehouse.models import FinishedProduct


class TaskLifecycleTests(TestCase):
    def setUp(self):
        self.worker = User.objects.create_user(username='worker', role=User.Role.WORKER)
        self.owner = User.objects.create_user(username='owner', role=User.Role.OWNER)
        client = Client.objects.create(name='C')
        self.order = Order.objects.create(
            client=client, quantity=Decimal('1'), unit='sht', deadline=datetime.date(2024, 1, 1)
        )

    def _task(self):
        return Task.objects.create(worker=self.worker, order=self.order)

    def test_accept_updates_task_and_order(self):
        task = self._task()
        task.accept()
        task.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.ACCEPTED)
        self.assertIsNotNone(task.accepted_at)
        self.assertEqual(self.order.status, OrderStatus.ACCEPTED_BY_WORKER)

    def test_refuse_updates_task_and_order(self):
        task = self._task()
        task.refuse('no time')
        task.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.REFUSED)
        self.assertEqual(task.refusal_comment, 'no time')
        self.assertEqual(self.order.status, OrderStatus.WORKER_REFUSED)

    def test_complete_sets_status_and_timestamp(self):
        task = self._task()
        task.complete()
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertIsNotNone(task.completed_at)

    def test_confirm_updates_task_and_order(self):
        task = self._task()
        task.confirm(self.owner)
        task.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.CONFIRMED)
        self.assertEqual(task.confirmed_by, self.owner)
        self.assertEqual(self.order.status, OrderStatus.IN_PROGRESS)

    def test_accept_without_order_does_not_fail(self):
        task = Task.objects.create(worker=self.worker)
        task.accept()
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.ACCEPTED)

    def test_str(self):
        task = self._task()
        self.assertIn(f'Task #{task.id}', str(task))
        self.assertIn('worker', str(task))


class WorkRecordTests(TestCase):
    def setUp(self):
        self.worker = User.objects.create_user(username='w', role=User.Role.WORKER)
        self.owner = User.objects.create_user(username='o', role=User.Role.OWNER)
        self.product = FinishedProduct.objects.create(name='Slab')

    def _work(self, **kwargs):
        defaults = dict(worker=self.worker, quantity=Decimal('2'), unit='sht')
        defaults.update(kwargs)
        return WorkRecord.objects.create(**defaults)

    def test_is_confirmed_property(self):
        work = self._work()
        self.assertFalse(work.is_confirmed)
        work.status = WorkRecord.WorkStatus.CONFIRMED
        self.assertTrue(work.is_confirmed)

    def test_confirm_sets_fields(self):
        work = self._work()
        work.confirm(self.owner, labor_cost=Decimal('150.00'))
        work.refresh_from_db()
        self.assertEqual(work.status, WorkRecord.WorkStatus.CONFIRMED)
        self.assertEqual(work.confirmed_by, self.owner)
        self.assertEqual(work.labor_cost, Decimal('150.00'))
        self.assertIsNotNone(work.confirmed_at)

    def test_confirm_also_confirms_related_task(self):
        client = Client.objects.create(name='C')
        order = Order.objects.create(
            client=client, quantity=Decimal('1'), unit='sht', deadline=datetime.date(2024, 1, 1)
        )
        task = Task.objects.create(worker=self.worker, order=order)
        work = self._work(task=task)
        work.confirm(self.owner)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.CONFIRMED)

    def test_reject_sets_status_and_reason(self):
        work = self._work()
        work.reject('bad quality')
        work.refresh_from_db()
        self.assertEqual(work.status, WorkRecord.WorkStatus.REJECTED)
        self.assertEqual(work.rejection_reason, 'bad quality')

    def test_calculate_labor_cost_without_product_returns_zero(self):
        work = self._work(product=None)
        self.assertEqual(work.calculate_labor_cost(), 0)

    def test_calculate_labor_cost_uses_cutting_rate(self):
        LaborRate.objects.create(
            product=self.product,
            operation=LaborRate.OperationType.CUTTING,
            rate_per_unit=Decimal('10.00'),
            unit='sht',
        )
        work = self._work(product=self.product, quantity=Decimal('3'))
        self.assertEqual(work.calculate_labor_cost(), Decimal('30.00'))

    def test_calculate_labor_cost_without_matching_rate_returns_zero(self):
        work = self._work(product=self.product)
        self.assertEqual(work.calculate_labor_cost(), 0)

    def test_str(self):
        work = self._work()
        self.assertIn(f'Work #{work.id}', str(work))
