"""
Этап E — регрессия N+1 для warehouse (движения склада, рецепты, строки рецептов).

Метод: число SQL-запросов на list-эндпоинт не должно расти с количеством
объектов. Сравниваем счётчик запросов при N=3 и N=12 — если растёт, это N+1.

До фикса эти тесты ПАДАЮТ (доказательство N+1), после фикса — проходят.
"""
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.warehouse.models import (
    FinishedProduct, RawMaterial, Recipe, RecipeItem, StockMovement,
)


class _Perf(TestCase):
    def _seed_company(self, n):
        company = Company.objects.create(name=f'W{n}')
        owner = User.objects.create_user(username=f'w_o{n}', password='p',
                                         role=User.Role.OWNER, company=company)
        return company, owner

    def _api(self, owner):
        c = APIClient()
        c.force_authenticate(user=owner)
        return c

    def _count(self, url, seed):
        Company.objects.all().delete()
        User.objects.all().delete()
        owner = seed()
        api = self._api(owner)
        with CaptureQueriesContext(connection) as ctx:
            resp = api.get(url)
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        return len(ctx)


class StockMovementNPlusOneTests(_Perf):
    def _seed(self, n):
        def _do():
            company, owner = self._seed_company(n)
            for i in range(n):
                mat = RawMaterial.objects.create(company=company, name=f'M{i}',
                                                 quantity=Decimal('5'))
                # у каждой записи свой created_by, чтобы N+1 по created_by был виден
                u = User.objects.create_user(username=f'w_m{n}_{i}', password='p',
                                             role=User.Role.WORKER, company=company)
                StockMovement.objects.create(
                    company=company, movement_type=StockMovement.MovementType.INCOMING,
                    material=mat, quantity=Decimal('1'), reason='r', created_by=u)
            return owner
        return _do

    def test_no_n_plus_one(self):
        self.assertEqual(
            self._count('/api/v1/warehouse/stock-movements/', self._seed(3)),
            self._count('/api/v1/warehouse/stock-movements/', self._seed(12)),
        )


class RecipeNPlusOneTests(_Perf):
    def _seed(self, n):
        def _do():
            company, owner = self._seed_company(n)
            for i in range(n):
                prod = FinishedProduct.objects.create(company=company, name=f'P{i}',
                                                      quantity=Decimal('1'))
                recipe = Recipe.objects.create(company=company, product=prod,
                                               name=f'R{i}', is_active=True)
                for j in range(2):
                    mat = RawMaterial.objects.create(company=company, name=f'M{i}_{j}',
                                                     quantity=Decimal('5'))
                    RecipeItem.objects.create(recipe=recipe, material=mat,
                                              quantity_required=Decimal('1'), unit='sht')
            return owner
        return _do

    def test_no_n_plus_one(self):
        self.assertEqual(
            self._count('/api/v1/warehouse/recipes/', self._seed(3)),
            self._count('/api/v1/warehouse/recipes/', self._seed(12)),
        )


class RecipeItemNPlusOneTests(_Perf):
    def _seed(self, n):
        def _do():
            company, owner = self._seed_company(n)
            prod = FinishedProduct.objects.create(company=company, name='P',
                                                  quantity=Decimal('1'))
            recipe = Recipe.objects.create(company=company, product=prod,
                                           name='R', is_active=True)
            for i in range(n):
                mat = RawMaterial.objects.create(company=company, name=f'M{i}',
                                                 quantity=Decimal('5'))
                RecipeItem.objects.create(recipe=recipe, material=mat,
                                          quantity_required=Decimal('1'), unit='sht')
            return owner
        return _do

    def test_no_n_plus_one(self):
        self.assertEqual(
            self._count('/api/v1/warehouse/recipe-items/', self._seed(3)),
            self._count('/api/v1/warehouse/recipe-items/', self._seed(12)),
        )
