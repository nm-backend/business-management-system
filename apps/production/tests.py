"""
Unit-тесты для приложения production: жизненный цикл Task
(accept/refuse/complete/confirm) и сервисы подтверждения работы
(confirm_work списывает сырьё и приходует товар, reject_work не трогает склад).
"""
import datetime
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import User
from apps.clients.models import Client
from apps.finance.models import LaborRate
from apps.orders.models import Order
from apps.production import services
from apps.production.models import Task, TaskStatus, WorkRecord
from apps.warehouse.models import FinishedProduct, RawMaterial, Recipe, RecipeItem, StockMovement


class TaskLifecycleTests(TestCase):
    def setUp(self):
        self.worker = User.objects.create_user(username='worker', role=User.Role.WORKER)
        self.owner = User.objects.create_user(username='owner', role=User.Role.OWNER)
        client = Client.objects.create(name='C')
        self.order = Order.objects.create(
            client=client, quantity=Decimal('1'), unit='sht', deadline=datetime.date(2024, 1, 1)
        )

    def test_str(self):
        task = Task.objects.create(worker=self.worker, order=self.order)
        self.assertIn(f'Task #{task.id}', str(task))
        self.assertIn('worker', str(task))

    def test_accept_moves_task_and_order(self):
        task = Task.objects.create(worker=self.worker, order=self.order)
        task.accept()
        task.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.ACCEPTED)
        self.assertIsNotNone(task.accepted_at)
        self.assertEqual(self.order.status, Order.Status.ACCEPTED)

    def test_refuse_moves_task_and_order(self):
        task = Task.objects.create(worker=self.worker, order=self.order)
        task.refuse('no_time', 'busy')
        task.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.REFUSED)
        self.assertEqual(task.refusal_reason, 'no_time')
        self.assertEqual(task.refusal_comment, 'busy')
        self.assertEqual(self.order.status, Order.Status.WORKER_REFUSED)

    def test_complete_and_confirm(self):
        task = Task.objects.create(worker=self.worker, order=self.order)
        task.complete()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.AWAITING_CONFIRMATION)
        task.confirm(self.owner)
        task.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.CONFIRMED)
        self.assertEqual(task.confirmed_by, self.owner)
        self.assertEqual(self.order.status, Order.Status.READY)


class WorkConfirmServiceTests(TestCase):
    def setUp(self):
        self.worker = User.objects.create_user(username='w', role=User.Role.WORKER)
        self.owner = User.objects.create_user(username='o', role=User.Role.OWNER)
        self.product = FinishedProduct.objects.create(name='Slab', quantity=Decimal('0'))
        self.material = RawMaterial.objects.create(name='Marble', quantity=Decimal('10'))
        recipe = Recipe.objects.create(product=self.product, name='Default')
        RecipeItem.objects.create(
            recipe=recipe, material=self.material, quantity_required=Decimal('2'), unit='sht'
        )

    def _work(self, **kwargs):
        defaults = dict(worker=self.worker, product=self.product,
                        quantity=Decimal('2'), unit='sht')
        defaults.update(kwargs)
        return WorkRecord.objects.create(**defaults)

    def test_is_confirmed_property(self):
        work = self._work()
        self.assertFalse(work.is_confirmed)
        work.status = WorkRecord.WorkStatus.CONFIRMED
        self.assertTrue(work.is_confirmed)

    def test_confirm_deducts_materials_and_adds_product(self):
        work = self._work()  # 2 изделия x 2 ед. сырья = 4 ед. списания
        services.confirm_work(work, self.owner, labor_cost=Decimal('150.00'))
        work.refresh_from_db()
        self.material.refresh_from_db()
        self.product.refresh_from_db()

        self.assertEqual(work.status, WorkRecord.WorkStatus.CONFIRMED)
        self.assertEqual(work.confirmed_by, self.owner)
        self.assertEqual(work.labor_cost, Decimal('150.00'))
        self.assertEqual(self.material.quantity, Decimal('6'))
        self.assertEqual(self.product.quantity, Decimal('2'))
        self.assertEqual(
            StockMovement.objects.filter(movement_type='production_out', material=self.material).count(), 1
        )
        self.assertEqual(
            StockMovement.objects.filter(movement_type='production_in', product=self.product).count(), 1
        )

    def test_confirm_fails_on_shortage_and_keeps_stock(self):
        work = self._work(quantity=Decimal('10'))  # нужно 20 ед., есть 10
        with self.assertRaises(services.MaterialShortageError):
            services.confirm_work(work, self.owner)
        work.refresh_from_db()
        self.material.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(work.status, WorkRecord.WorkStatus.AWAITING_CONFIRMATION)
        self.assertEqual(self.material.quantity, Decimal('10'))
        self.assertEqual(self.product.quantity, Decimal('0'))
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_confirm_uses_labor_rate_when_cost_not_given(self):
        LaborRate.objects.create(
            product=self.product,
            operation=LaborRate.OperationType.CUTTING,
            rate_per_unit=Decimal('10.00'),
            unit='sht',
        )
        work = self._work(quantity=Decimal('3'))
        services.confirm_work(work, self.owner)
        work.refresh_from_db()
        self.assertEqual(work.labor_cost, Decimal('30.00'))

    def test_calculate_labor_cost_without_product_or_rate(self):
        self.assertEqual(services.calculate_labor_cost(self._work(product=None)), Decimal('0'))
        self.assertEqual(services.calculate_labor_cost(self._work()), Decimal('0'))

    def test_reject_keeps_stock_and_sets_reason(self):
        work = self._work()
        services.reject_work(work, self.owner, 'bad quality')
        work.refresh_from_db()
        self.material.refresh_from_db()
        self.assertEqual(work.status, WorkRecord.WorkStatus.REJECTED)
        self.assertEqual(work.rejection_reason, 'bad quality')
        self.assertEqual(self.material.quantity, Decimal('10'))
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_reject_resets_task_and_order_for_rework(self):
        import datetime
        client = Client.objects.create(name='C')
        order = Order.objects.create(
            client=client, quantity=Decimal('1'), unit='sht', deadline=datetime.date(2024, 1, 1),
        )
        task = Task.objects.create(worker=self.worker, order=order, status='accepted')
        task.complete()  # -> task COMPLETED, order AWAITING_CONFIRMATION
        work = self._work(task=task)
        services.reject_work(work, self.owner, 'redo it')
        task.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(task.status, 'accepted')
        self.assertIsNone(task.completed_at)
        self.assertEqual(order.status, Order.Status.IN_PROGRESS)

    def test_double_confirm_raises_already_processed(self):
        work = self._work()
        services.confirm_work(work, self.owner, labor_cost=Decimal('10'))
        with self.assertRaises(services.AlreadyProcessedError):
            services.confirm_work(work, self.owner, labor_cost=Decimal('10'))
        self.material.refresh_from_db()
        # Сырьё списано ровно один раз (4), а не дважды.
        self.assertEqual(self.material.quantity, Decimal('6'))

    def test_str(self):
        work = self._work()
        self.assertIn(f'Work #{work.id}', str(work))
