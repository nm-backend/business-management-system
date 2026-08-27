"""
Семантика количества и брака в WorkRecord (однозначный контракт).

    quantity        — ГОДНОЕ количество (good): приходуется на склад, оплачивается.
    defect_quantity — БРАК (defective): сырьё израсходовано, товара и оплаты нет.
    total_processed  = quantity + defect_quantity.

Эти тесты фиксируют, как три среза системы (склад, оплата труда, готовая
продукция) обязаны согласовываться друг с другом при подтверждении работы.
"""
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import User
from apps.companies.models import Company
from apps.finance.models import LaborRate
from apps.production.models import WorkRecord
from apps.production.services import confirm_work
from apps.warehouse.models import FinishedProduct, RawMaterial, Recipe, RecipeItem


class DefectSemanticsTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='DefSemCo', is_active=True)
        self.owner = User.objects.create_user(username='ds_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='ds_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.material = RawMaterial.objects.create(
            company=self.company, name='Мрамор', quantity=Decimal('100'), unit='m2')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('0'), unit='dona')
        recipe = Recipe.objects.create(company=self.company, product=self.product,
                                       name='Основной', is_active=True)
        # 2 м² сырья на 1 единицу продукции
        RecipeItem.objects.create(recipe=recipe, material=self.material,
                                  quantity_required=Decimal('2'), unit='m2')
        LaborRate.objects.create(company=self.company, product=self.product,
                                 operation=LaborRate.OperationType.OTHER,
                                 rate_per_unit=Decimal('1000'), unit='dona')

    def _confirm(self, good, defect):
        work = WorkRecord.objects.create(
            company=self.company, worker=self.worker, product=self.product,
            quantity=Decimal(good), defect_quantity=Decimal(defect), unit='dona',
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION)
        confirm_work(work, self.owner)
        work.refresh_from_db()
        self.material.refresh_from_db()
        self.product.refresh_from_db()
        return work

    def test_material_consumed_for_good_plus_defect(self):
        """5 годных + 2 брака -> списано (5+2)*2 = 14 м² сырья."""
        self._confirm('5', '2')
        self.assertEqual(self.material.quantity, Decimal('86.000'))

    def test_stock_receives_good_only(self):
        """На склад попадает только годное: 5, а не 7."""
        self._confirm('5', '2')
        self.assertEqual(self.product.quantity, Decimal('5.000'))

    def test_labor_paid_on_good_only(self):
        """Оплата труда начисляется на годное: 5 × 1000 = 5000, не на 7."""
        work = self._confirm('5', '2')
        self.assertEqual(work.labor_cost, Decimal('5000.00'))

    def test_all_defect_consumes_material_but_no_stock_or_wage(self):
        """Всё в брак (0 годных + 5 брака): сырьё списано, товара и оплаты нет."""
        work = self._confirm('0', '5')
        self.assertEqual(self.material.quantity, Decimal('90.000'))   # 5*2 списано
        self.assertEqual(self.product.quantity, Decimal('0.000'))     # товара нет
        self.assertEqual(work.labor_cost, Decimal('0.00'))            # оплаты нет
