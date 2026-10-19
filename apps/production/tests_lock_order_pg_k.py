"""
Порядок блокировок сырья при подтверждении работ.

Два товара с рецептами, где одни и те же материалы перечислены в обратном
порядке, подтверждаются одновременно. Если строки блокировать в порядке
рецепта, потоки берут их крест-накрест и PostgreSQL возвращает deadlock.
Сервис обязан блокировать материалы в едином порядке (по pk).
"""
import threading
import unittest
from decimal import Decimal

from django.db import connection, connections
from django.test import TransactionTestCase

from apps.accounts.models import User
from apps.companies.models import Company
from apps.finance.models import LaborRate
from apps.production.models import WorkRecord
from apps.production.services import confirm_work
from apps.warehouse.models import FinishedProduct, RawMaterial, Recipe, RecipeItem


@unittest.skipUnless(connection.vendor == 'postgresql',
                     'Дедлоки проверяются только на PostgreSQL')
class ReversedRecipeLockOrderTests(TransactionTestCase):
    def setUp(self):
        self.company = Company.objects.create(name='LockOrderCo', is_active=True)
        self.owner = User.objects.create_user(
            username='lock_owner', password='p',
            role=User.Role.OWNER, company=self.company,
        )
        self.m1 = RawMaterial.objects.create(
            company=self.company, name='Материал 1', quantity=Decimal('100'), unit='m2',
        )
        self.m2 = RawMaterial.objects.create(
            company=self.company, name='Материал 2', quantity=Decimal('100'), unit='m2',
        )
        self.product_a = self._product('Товар А', [self.m1, self.m2])
        self.product_b = self._product('Товар Б', [self.m2, self.m1])

    def _product(self, name, materials):
        product = FinishedProduct.objects.create(
            company=self.company, name=name, quantity=Decimal('0'), unit='sht',
        )
        recipe = Recipe.objects.create(
            company=self.company, product=product, name='Рецепт', is_active=True,
        )
        for material in materials:
            RecipeItem.objects.create(
                recipe=recipe, material=material,
                quantity_required=Decimal('1'), unit='m2',
            )
        LaborRate.objects.create(
            company=self.company, product=product,
            operation=LaborRate.OperationType.OTHER,
            rate_per_unit=Decimal('100'), unit='sht',
        )
        return product

    def _work(self, product):
        return WorkRecord.objects.create(
            company=self.company, worker=self.owner, product=product,
            operation=LaborRate.OperationType.OTHER,
            quantity=Decimal('5'), unit='sht',
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION,
        )

    def test_parallel_confirm_with_reversed_recipes_does_not_deadlock(self):
        for attempt in range(5):
            work_a = self._work(self.product_a)
            work_b = self._work(self.product_b)
            barrier = threading.Barrier(2)
            errors = []

            def run(work_id):
                try:
                    barrier.wait(timeout=30)
                    work = WorkRecord.objects.get(pk=work_id)
                    confirm_work(work, self.owner)
                except Exception as exc:  # noqa: BLE001 — ошибка и есть результат
                    errors.append(exc)
                finally:
                    connections.close_all()

            threads = [
                threading.Thread(target=run, args=(work_a.pk,)),
                threading.Thread(target=run, args=(work_b.pk,)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=60)
            self.assertFalse([t for t in threads if t.is_alive()],
                             f'попытка {attempt + 1}: поток не завершился')
            self.assertEqual(errors, [], f'попытка {attempt + 1}: {errors!r}')

        self.m1.refresh_from_db()
        self.m2.refresh_from_db()
        # 10 подтверждений по 5 единиц, по 1 м² каждого материала на единицу.
        self.assertEqual(self.m1.quantity, Decimal('50.000'))
        self.assertEqual(self.m2.quantity, Decimal('50.000'))
        self.assertEqual(
            WorkRecord.objects.filter(
                status=WorkRecord.WorkStatus.CONFIRMED,
            ).count(),
            10,
        )
