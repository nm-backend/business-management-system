"""
Брак в производстве (макет «Ишни якунлаш», поле «Брак миқдори»).

Рабочий указывает годное количество и брак раздельно. Сырьё израсходовано и
на брак тоже, а на склад готовой продукции попадает только годное.

До правки расход считался лишь по годному: материал, ушедший в брак, оставался
на складе и остаток был завышен — склад показывал сырьё, которого физически
уже нет.
"""
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import User
from apps.companies.models import Company
from apps.production.models import WorkRecord
from apps.production.services import confirm_work
from apps.warehouse.models import FinishedProduct, RawMaterial, Recipe, RecipeItem


class DefectConsumptionTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='DefectCo', is_active=True)
        self.owner = User.objects.create_user(username='def_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='def_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.material = RawMaterial.objects.create(
            company=self.company, name='Мрамор', quantity=Decimal('100'), unit='m2')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('0'), unit='dona')
        recipe = Recipe.objects.create(company=self.company, product=self.product,
                                       name='Основной', is_active=True)
        # на одну единицу продукции — 2 м² мрамора
        RecipeItem.objects.create(recipe=recipe, material=self.material,
                                  quantity_required=Decimal('2'), unit='m2')

    def _work(self, quantity, defect):
        return WorkRecord.objects.create(
            company=self.company, worker=self.worker, product=self.product,
            quantity=Decimal(quantity), defect_quantity=Decimal(defect), unit='dona',
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION)

    def test_defect_consumes_material_too(self):
        """3 годных + 2 брака -> списано 5*2 = 10 м², на склад ушло 3 штуки."""
        confirm_work(self._work('3', '2'), self.owner)
        self.material.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('90.000'))
        self.assertEqual(self.product.quantity, Decimal('3.000'))

    def test_without_defect_behaviour_unchanged(self):
        confirm_work(self._work('4', '0'), self.owner)
        self.material.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('92.000'))
        self.assertEqual(self.product.quantity, Decimal('4.000'))

    def test_defect_never_reaches_finished_stock(self):
        """Брак — это не товар: на остаток готовой продукции он не влияет."""
        confirm_work(self._work('0', '5'), self.owner)
        self.material.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('90.000'))
        self.assertEqual(self.product.quantity, Decimal('0.000'))

    def test_shortage_counts_defect(self):
        """Не хватает сырья с учётом брака — работа не подтверждается."""
        from apps.production.services import MaterialShortageError
        self.material.quantity = Decimal('10')
        self.material.save(update_fields=['quantity'])
        with self.assertRaises(MaterialShortageError):
            confirm_work(self._work('4', '2'), self.owner)   # нужно 12 м², есть 10
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('10.000'), 'склад не должен меняться')

    def test_negative_defect_rejected_by_api(self):
        from rest_framework.test import APIClient
        api = APIClient()
        api.force_authenticate(self.worker)
        resp = api.post('/api/v1/production/works/', {
            'product': self.product.id, 'quantity': '1',
            'defect_quantity': '-3', 'unit': 'dona',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
