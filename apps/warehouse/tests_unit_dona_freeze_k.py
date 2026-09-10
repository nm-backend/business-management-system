"""
Удаление legacy-единицы 'dona' (PR-2): канон — 'sht'.

'dona' и 'sht' означали одно и то же («штука»), но дублировались в
UnitChoices, раскалывая агрегаты отчётов (unit_totals) и списки выбора.
API отклоняет 'dona' как неизвестный выбор; старые строки перенесла
data-миграция 0026 (PR-2b).
"""
import importlib
from decimal import Decimal

from django.apps import apps as django_apps
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.finance.models import LaborRate
from apps.orders.models import Order
from apps.production.models import Task, WorkRecord
from apps.warehouse.models import FinishedProduct, RawMaterial, Recipe, RecipeItem
from apps.warehouse.serializers import RawMaterialSerializer

MATERIALS = '/api/v1/warehouse/raw-materials/'


class DonaFreezeTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='FreezeCo', is_active=True)
        self.owner = User.objects.create_user(username='frz_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_api_create_material_with_dona_rejected(self):
        resp = self.api.post(MATERIALS, {'name': 'Тест', 'quantity': '5',
                                         'unit': 'dona'}, format='json')
        self.assertEqual(resp.status_code, 400, resp.content[:200])
        self.assertIn('unit', resp.json())
        self.assertFalse(RawMaterial.objects.filter(name='Тест').exists())

    def test_api_create_material_with_sht_ok(self):
        resp = self.api.post(MATERIALS, {'name': 'Тест', 'quantity': '5',
                                         'unit': 'sht'}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:200])

    def test_serializer_rejects_dona_as_unknown_choice(self):
        s = RawMaterialSerializer(data={'name': 'Тест', 'unit': 'dona'})
        self.assertFalse(s.is_valid())
        self.assertIn('unit', s.errors)

    def test_serializer_accepts_sht(self):
        s = RawMaterialSerializer(data={'name': 'Тест', 'unit': 'sht'})
        s.is_valid()
        self.assertNotIn('unit', s.errors)


class DonaMergeMigrationTests(TestCase):
    """PR-2b: функция миграции переносит dona -> sht во всех 7 таблицах."""

    def test_merge_converts_all_dona_rows(self):
        company = Company.objects.create(name='MergeCo', is_active=True)
        worker = User.objects.create_user(username='mrg_worker', password='p',
                                          role=User.Role.WORKER, company=company)
        # Валидаторы не выполняются при прямом ORM-create — так legacy-строки
        # и попали в базу; именно их находит миграция.
        material = RawMaterial.objects.create(
            company=company, name='М', quantity=Decimal('1'), unit='dona')
        control = RawMaterial.objects.create(
            company=company, name='Контроль', quantity=Decimal('1'), unit='kg')
        product = FinishedProduct.objects.create(
            company=company, name='П', quantity=Decimal('1'), unit='dona')
        recipe = Recipe.objects.create(company=company, product=product,
                                       name='R', is_active=True)
        RecipeItem.objects.create(recipe=recipe, material=material,
                                  quantity_required=Decimal('1'), unit='dona')
        LaborRate.objects.create(company=company, product=product,
                                 operation=LaborRate.OperationType.CUTTING,
                                 rate_per_unit=Decimal('5'), unit='dona')
        client = Client.objects.create(name='C')
        order = Order.objects.create(client=client, quantity=Decimal('1'),
                                     unit='dona')
        Task.objects.create(worker=worker, order=order, planned_unit='dona')
        WorkRecord.objects.create(company=company, worker=worker, product=product,
                                  quantity=Decimal('1'), unit='dona')

        mod = importlib.import_module(
            'apps.warehouse.migrations.0026_merge_dona_into_sht')
        mod.merge_dona_into_sht(django_apps, None)

        for model, field in [
            (RawMaterial, 'unit'), (FinishedProduct, 'unit'),
            (RecipeItem, 'unit'), (LaborRate, 'unit'), (Order, 'unit'),
            (Task, 'planned_unit'), (WorkRecord, 'unit'),
        ]:
            self.assertEqual(model.objects.filter(**{field: 'dona'}).count(), 0,
                             f'{model.__name__}.{field}: остались dona-строки')
        control.refresh_from_db()
        self.assertEqual(control.unit, 'kg',
                         'миграция не должна трогать другие единицы')
        material.refresh_from_db()
        self.assertEqual(material.unit, 'sht')
