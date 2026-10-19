"""
API-контур партии «всё в брак»: 0 годных + N брака.

Сервис confirm_work такую партию поддерживал, но API отклонял её и при
создании (quantity <= 0), и при подтверждении. В результате полностью
забракованная партия не подтверждалась, работа висела в ожидании, а сырьё
оставалось на складе. Здесь проверяется именно HTTP-путь, которым пользуется
интерфейс, а не прямой вызов сервиса.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.finance.models import LaborRate
from apps.production.models import WorkRecord
from apps.warehouse.models import (
    FinishedProduct, RawMaterial, Recipe, RecipeItem, StockMovement,
)

WORKS = '/api/v1/production/works/'


class AllDefectApiTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='AllDefectCo', is_active=True)
        self.owner = User.objects.create_user(
            username='ad_owner', password='p',
            role=User.Role.OWNER, company=self.company,
        )
        self.worker = User.objects.create_user(
            username='ad_worker', password='p',
            role=User.Role.WORKER, company=self.company,
        )
        self.material = RawMaterial.objects.create(
            company=self.company, name='Мрамор', quantity=Decimal('100'), unit='m2',
        )
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('0'), unit='sht',
        )
        recipe = Recipe.objects.create(
            company=self.company, product=self.product, name='Основной', is_active=True,
        )
        RecipeItem.objects.create(
            recipe=recipe, material=self.material,
            quantity_required=Decimal('2'), unit='m2',
        )
        LaborRate.objects.create(
            company=self.company, product=self.product,
            operation=LaborRate.OperationType.OTHER,
            rate_per_unit=Decimal('1000'), unit='sht',
        )
        self.worker_api = APIClient()
        self.worker_api.force_authenticate(self.worker)
        self.owner_api = APIClient()
        self.owner_api.force_authenticate(self.owner)

    def _create_work(self, good, defect):
        return self.worker_api.post(WORKS, {
            'product': self.product.id,
            'quantity': str(good),
            'defect_quantity': str(defect),
            'unit': 'sht',
        }, format='json')

    def test_all_defect_batch_can_be_created_and_confirmed(self):
        created = self._create_work('0', '5')
        self.assertEqual(created.status_code, 201, created.content[:300])
        work_id = created.json()['id']

        confirmed = self.owner_api.post(f'{WORKS}{work_id}/confirm/')
        self.assertEqual(confirmed.status_code, 200, confirmed.content[:300])

        work = WorkRecord.objects.get(pk=work_id)
        self.material.refresh_from_db()
        self.product.refresh_from_db()

        self.assertEqual(work.status, WorkRecord.WorkStatus.CONFIRMED)
        self.assertEqual(work.labor_cost, Decimal('0.00'))
        # Сырьё израсходовано на брак: 5 * 2 = 10 м².
        self.assertEqual(self.material.quantity, Decimal('90.000'))
        # Годного товара нет.
        self.assertEqual(self.product.quantity, Decimal('0.000'))
        self.assertTrue(StockMovement.objects.filter(
            movement_type=StockMovement.MovementType.PRODUCTION_OUT,
            material=self.material, quantity=Decimal('10.000'),
        ).exists())
        self.assertFalse(StockMovement.objects.filter(
            movement_type=StockMovement.MovementType.PRODUCTION_IN,
            product=self.product,
        ).exists())

    def test_zero_good_and_zero_defect_rejected_on_create(self):
        response = self._create_work('0', '0')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(WorkRecord.objects.exists())

    def test_negative_good_rejected_on_create(self):
        response = self._create_work('-1', '5')
        self.assertEqual(response.status_code, 400)

    def test_patch_to_zero_total_rejected(self):
        created = self._create_work('1', '0')
        self.assertEqual(created.status_code, 201, created.content[:300])
        work_id = created.json()['id']

        response = self.owner_api.patch(
            f'{WORKS}{work_id}/', {'quantity': '0'}, format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(WorkRecord.objects.get(pk=work_id).quantity, Decimal('1.000'))

    def test_repeat_confirm_does_not_write_off_material_twice(self):
        created = self._create_work('0', '5')
        work_id = created.json()['id']
        self.assertEqual(
            self.owner_api.post(f'{WORKS}{work_id}/confirm/').status_code, 200,
        )
        again = self.owner_api.post(f'{WORKS}{work_id}/confirm/')
        self.assertEqual(again.status_code, 400)

        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('90.000'))
        self.assertEqual(StockMovement.objects.filter(
            movement_type=StockMovement.MovementType.PRODUCTION_OUT,
            material=self.material,
        ).count(), 1)
