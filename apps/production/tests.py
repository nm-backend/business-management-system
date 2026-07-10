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
from apps.orders.models import Order
from apps.production.models import Task, WorkRecord
from apps.warehouse.models import FinishedProduct


class TaskTests(TestCase):
    def setUp(self):
        self.worker = User.objects.create_user(username='worker', role=User.Role.WORKER)
        client = Client.objects.create(name='C')
        self.order = Order.objects.create(
            client=client, quantity=Decimal('1'), unit='sht', deadline=datetime.date(2024, 1, 1)
        )

    def test_str(self):
        task = Task.objects.create(worker=self.worker, order=self.order)
        self.assertIn(f'Task #{task.id}', str(task))
        self.assertIn('worker', str(task))

# NOTE: Task.accept()/refuse()/complete()/confirm() в текущем коде обращаются к
# self.TaskStatus и self.order.OrderStatus, тогда как эти перечисления объявлены
# на уровне модуля (TaskStatus / OrderStatus), а не вложены в модель. Методы падают
# с AttributeError, поэтому по ним тесты не добавлены (см. описание PR).


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
