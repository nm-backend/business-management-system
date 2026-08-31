"""
Stage 2 — ТЕСТЫ КОНКУРРЕНТНОСТИ И ГОНКИ ДАННЫХ.

Проверяют:
- select_for_update + @transaction.atomic в confirm_work
- Параллельные confirm_work не списывают сырьё дважды
- Order.cost_price фиксируется в момент DELIVERED (снимок)
- Параллельные deliver не дублируют списание
"""
import datetime
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal

from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.finance.models import LaborRate
from apps.orders.models import Order
from apps.production.models import Task, TaskStatus, WorkRecord
from apps.warehouse.models import (
    FinishedProduct, RawMaterial, Recipe, RecipeItem, StockMovement,
)

from apps.production.services import (
    confirm_work, MaterialShortageError, AlreadyProcessedError,
)


class _ConcurrencyBase(TransactionTestCase):
    """Базовый setUp для concurrency-тестов (нужна реальная БД, не in-memory)."""

    def setUp(self):
        self.company = Company.objects.create(name='RaceCo')
        self.owner = User.objects.create_user(
            username='race_owner', password='pw', role=User.Role.OWNER,
            company=self.company,
        )
        self.worker = User.objects.create_user(
            username='race_worker', password='pw', role=User.Role.WORKER,
            company=self.company,
        )
        self.admin = User.objects.create_user(
            username='race_admin', password='pw', role=User.Role.ADMIN,
            company=self.company,
        )

        self.material = RawMaterial.objects.create(
            company=self.company, name='Гранит',
            quantity=Decimal('20'), purchase_price=Decimal('1000'),
            avg_cost_price=Decimal('800'), unit='m2',
        )
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница',
            quantity=Decimal('0'), cost_price=Decimal('0'),
            sale_price=Decimal('30000'), unit='izdelie',
        )
        self.recipe = Recipe.objects.create(
            company=self.company, product=self.product,
            name='Стандарт', is_active=True,
        )
        RecipeItem.objects.create(
            recipe=self.recipe, material=self.material,
            quantity_required=Decimal('2'), unit='m2',
        )
        self.labor_rate = LaborRate.objects.create(
            company=self.company, product=self.product,
            operation=LaborRate.OperationType.CUTTING,
            rate_per_unit=Decimal('5000'), unit='izdelie',
        )
        self.client_obj = Client.objects.create(
            company=self.company, name='RaceClient',
        )
        self.api = APIClient()
        self.api.force_authenticate(user=self.owner)


def _is_postgresql():
    from django.db import connection
    return hasattr(connection.ops, 'postgresql_version')


class ConfirmWorkMaterialDeductionTests(_ConcurrencyBase):
    """confirm_work списывает ровно столько сырья, сколько нужно по рецепту."""

    def test_single_confirm_deducts_correct_amount(self):
        """Однократное подтверждение: quantity=5, рецепт=2m2 → 10m2 списано."""
        task = Task.objects.create(
            company=self.company, worker=self.worker, assigned_by=self.owner,
            status=TaskStatus.PENDING,
        )
        work = WorkRecord.objects.create(
            company=self.company, task=task, worker=self.worker,
            product=self.product, operation=LaborRate.OperationType.CUTTING,
            quantity=Decimal('5'), unit='izdelie',
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION,
        )

        initial_qty = self.material.quantity
        required = Decimal('5') * Decimal('2')  # 10 m2

        confirm_work(work, self.owner, request=None)

        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, initial_qty - required)

    def test_parallel_confirms_do_not_over_deduct(self):
        """Два параллельных confirm_work по 5 шт → списано ровно 20 m2, не 40."""
        if not _is_postgresql():
            self.skipTest('SQLite does not support real row-level locking')
        results = {}
        errors = {}

        def do_confirm(work_id, label):
            try:
                w = WorkRecord.objects.get(pk=work_id)
                confirm_work(w, self.owner, request=None)
                results[label] = True
            except (MaterialShortageError, AlreadyProcessedError) as e:
                errors[label] = str(e)
            except Exception as e:
                errors[label] = f'Unexpected: {e}'

        tasks = []
        works = []
        for i in range(2):
            t = Task.objects.create(
                company=self.company, worker=self.worker, assigned_by=self.owner,
                status=TaskStatus.PENDING,
            )
            w = WorkRecord.objects.create(
                company=self.company, task=t, worker=self.worker,
                product=self.product, operation=LaborRate.OperationType.CUTTING,
                quantity=Decimal('5'), unit='izdelie',
                status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION,
            )
            works.append(w)

        threads = [
            threading.Thread(target=do_confirm, args=(works[0].pk, 'A')),
            threading.Thread(target=do_confirm, args=(works[1].pk, 'B')),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.material.refresh_from_db()
        initial_qty = Decimal('20')
        total_deducted = initial_qty - self.material.quantity

        # Два подтверждения по 5 шт * 2 m2/шт = 20 m2
        self.assertEqual(total_deducted, Decimal('20'),
                         f'Expected 20m2 deducted, got {total_deducted}. '
                         f'Results: {results}, Errors: {errors}')
        self.assertEqual(len(results), 2, f'Both should succeed: {errors}')

    def test_insufficient_material_blocks_confirm(self):
        """Если сырья не хватает — confirm_work бросает MaterialShortageError."""
        self.material.quantity = Decimal('3')
        self.material.save(update_fields=['quantity'])

        task = Task.objects.create(
            company=self.company, worker=self.worker, assigned_by=self.owner,
            status=TaskStatus.PENDING,
        )
        work = WorkRecord.objects.create(
            company=self.company, task=task, worker=self.worker,
            product=self.product, operation=LaborRate.OperationType.CUTTING,
            quantity=Decimal('5'), unit='izdelie',
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION,
        )

        with self.assertRaises(MaterialShortageError):
            confirm_work(work, self.owner, request=None)

        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('3'),
                         'Склад не должен меняться при нехватке')


class ConfirmWorkProductReceiptTests(_ConcurrencyBase):
    """confirm_work приходует готовую продукцию на склад."""

    def test_confirm_increases_product_quantity(self):
        task = Task.objects.create(
            company=self.company, worker=self.worker, assigned_by=self.owner,
            status=TaskStatus.PENDING,
        )
        work = WorkRecord.objects.create(
            company=self.company, task=task, worker=self.worker,
            product=self.product, operation=LaborRate.OperationType.CUTTING,
            quantity=Decimal('5'), unit='izdelie',
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION,
        )

        initial_product_qty = self.product.quantity
        confirm_work(work, self.owner, request=None)

        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, initial_product_qty + Decimal('5'))


class ConfirmWorkLaborCostTests(_ConcurrencyBase):
    """confirm_work начисляет labor_cost = quantity * rate_per_unit."""

    def test_labor_cost_calculation(self):
        task = Task.objects.create(
            company=self.company, worker=self.worker, assigned_by=self.owner,
            status=TaskStatus.PENDING,
        )
        work = WorkRecord.objects.create(
            company=self.company, task=task, worker=self.worker,
            product=self.product, operation=LaborRate.OperationType.CUTTING,
            quantity=Decimal('5'), unit='izdelie',
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION,
        )

        confirm_work(work, self.owner, request=None)
        work.refresh_from_db()
        expected = Decimal('5') * Decimal('5000')
        self.assertEqual(work.labor_cost, expected)
        self.assertEqual(work.status, WorkRecord.WorkStatus.CONFIRMED)


class CostPriceSnapshotTests(_ConcurrencyBase):
    """Order.cost_price фиксируется в момент перехода в DELIVERED."""

    def test_cost_price_snapshot_on_deliver(self):
        """При выдаче заказа cost_price = product.cost_price (снимок)."""
        self.product.cost_price = Decimal('15000')
        self.product.quantity = Decimal('10')
        self.product.save(update_fields=['cost_price', 'quantity'])

        order = Order.objects.create(
            company=self.company, client=self.client_obj,
            product=self.product, quantity=Decimal('3'),
            unit='izdelie', status=Order.Status.READY,
            total_amount=Decimal('90000'), paid_amount=Decimal('90000'),
            deadline=datetime.date(2026, 12, 31),
        )
        order.release_product_requirement()
        order.release_raw_material_requirements()

        resp = self.api.post(f'/api/v1/orders/orders/{order.pk}/deliver/')
        self.assertEqual(resp.status_code, 200)

        order.refresh_from_db()
        self.assertEqual(order.cost_price, Decimal('15000'),
                         'cost_price snapshot should be fixed at deliver time')

    def test_cost_price_not_changed_by_later_edit(self):
        """Если себестоимость товара изменилась ПОСЛЕ выдачи — снимок не меняется."""
        self.product.cost_price = Decimal('15000')
        self.product.quantity = Decimal('10')
        self.product.save(update_fields=['cost_price', 'quantity'])

        order = Order.objects.create(
            company=self.company, client=self.client_obj,
            product=self.product, quantity=Decimal('2'),
            unit='izdelie', status=Order.Status.READY,
            total_amount=Decimal('60000'), paid_amount=Decimal('60000'),
            deadline=datetime.date(2026, 12, 31),
        )
        order.release_product_requirement()
        order.release_raw_material_requirements()

        resp = self.api.post(f'/api/v1/orders/orders/{order.pk}/deliver/')
        self.assertEqual(resp.status_code, 200)

        # Симулируем переоценку товара после выдачи
        self.product.cost_price = Decimal('99999')
        self.product.save(update_fields=['cost_price'])

        order.refresh_from_db()
        self.assertEqual(order.cost_price, Decimal('15000'),
                         'Snapshot should NOT change after product cost update')

    def test_cost_price_not_overwritten_on_repeated_save(self):
        """Повторный save() не перезаписывает cost_price (defensive)."""
        self.product.cost_price = Decimal('10000')
        self.product.quantity = Decimal('5')
        self.product.save(update_fields=['cost_price', 'quantity'])

        order = Order.objects.create(
            company=self.company, client=self.client_obj,
            product=self.product, quantity=Decimal('2'),
            unit='izdelie', status=Order.Status.READY,
            total_amount=Decimal('50000'), paid_amount=Decimal('50000'),
            deadline=datetime.date(2026, 12, 31),
        )
        order.release_product_requirement()
        order.release_raw_material_requirements()

        resp = self.api.post(f'/api/v1/orders/orders/{order.pk}/deliver/')
        self.assertEqual(resp.status_code, 200)
        order.refresh_from_db()

        # Второй deliver на уже выданный заказ должен вернуть 400
        resp2 = self.api.post(f'/api/v1/orders/orders/{order.pk}/deliver/')
        self.assertEqual(resp2.status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.cost_price, Decimal('10000'))


class ParallelDeliverTests(_ConcurrencyBase):
    """Параллельные deliver не дублируют списание товара."""

    def test_parallel_deliver_only_one_succeeds(self):
        if not _is_postgresql():
            self.skipTest('SQLite does not support real row-level locking')
        """Два параллельных deliver одного заказа: один 200, другой 400."""
        self.product.quantity = Decimal('10')
        self.product.save(update_fields=['quantity'])

        order = Order.objects.create(
            company=self.company, client=self.client_obj,
            product=self.product, quantity=Decimal('3'),
            unit='izdelie', status=Order.Status.READY,
            total_amount=Decimal('90000'), paid_amount=Decimal('90000'),
            deadline=datetime.date(2026, 12, 31),
        )
        order.release_product_requirement()
        order.release_raw_material_requirements()

        statuses = {}

        def do_deliver(label):
            api = APIClient()
            api.force_authenticate(user=self.owner)
            resp = api.post(f'/api/v1/orders/orders/{order.pk}/deliver/')
            statuses[label] = resp.status_code

        threads = [
            threading.Thread(target=do_deliver, args=('A',)),
            threading.Thread(target=do_deliver, args=('B',)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.product.refresh_from_db()
        # Должен быть только один successful deliver
        self.assertEqual(
            sorted(statuses.values()), [200, 400],
            f'Expected [200, 400], got {statuses}'
        )
        # Товар списан ровно 3 шт, не 6
        self.assertEqual(self.product.quantity, Decimal('7'))
