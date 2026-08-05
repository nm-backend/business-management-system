"""
Подтверждённая работа неизменна по количеству и браку (PATCH запрещён).

confirm_work уже списал сырьё, приходовал товар и начислил оплату по
(quantity + defect_quantity). До правки owner/admin мог PATCH'ем поменять
эти поля у подтверждённой работы: склад и заработок оставались по старым
значениям, а карточка показывала новые — цифры расходились с фактическим
складом и балансом работника.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.production.models import WorkRecord
from apps.production.services import confirm_work
from apps.warehouse.models import FinishedProduct, RawMaterial, Recipe, RecipeItem


class ConfirmedWorkGuardTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='GuardCo', is_active=True)
        self.owner = User.objects.create_user(username='gr_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='gr_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.material = RawMaterial.objects.create(
            company=self.company, name='Мрамор', quantity=Decimal('100'), unit='m2')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('0'), unit='dona')
        recipe = Recipe.objects.create(company=self.company, product=self.product,
                                       name='Основной', is_active=True)
        RecipeItem.objects.create(recipe=recipe, material=self.material,
                                  quantity_required=Decimal('2'), unit='m2')

        from apps.finance.models import LaborRate
        LaborRate.objects.get_or_create(
            company=self.company, product=self.product,
            operation=LaborRate.OperationType.OTHER,
            defaults={'rate_per_unit': Decimal('100'), 'unit': self.product.unit})

        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def _work(self, quantity='3', defect='0', status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION):
        return WorkRecord.objects.create(
            company=self.company, worker=self.worker, product=self.product,
            quantity=Decimal(quantity), defect_quantity=Decimal(defect), unit='dona',
            status=status)

    def _patch(self, work, data):
        return self.client.patch(f'/api/v1/production/works/{work.id}/', data, format='json')

    def test_quantity_locked_after_confirm(self):
        work = self._work()
        confirm_work(work, self.owner)
        resp = self._patch(work, {'quantity': '10'})
        self.assertEqual(resp.status_code, 400)

    def test_defect_locked_after_confirm(self):
        work = self._work(defect='1')
        confirm_work(work, self.owner)
        resp = self._patch(work, {'defect_quantity': '5'})
        self.assertEqual(resp.status_code, 400)

    def test_noop_patch_with_same_quantity_allowed(self):
        """Отправка того же значения (повторный PATCH из формы) не запрещается."""
        work = self._work()
        confirm_work(work, self.owner)
        resp = self._patch(work, {'quantity': str(work.quantity)})
        self.assertEqual(resp.status_code, 200)

    def test_comment_still_editable_after_confirm(self):
        """Нефинансовые поля подтверждённой работы править можно."""
        work = self._work()
        confirm_work(work, self.owner)
        resp = self._patch(work, {'comment': 'уточнение'})
        self.assertEqual(resp.status_code, 200)

    def test_quantity_editable_before_confirm(self):
        """До подтверждения количество корректируется (опечатка рабочего)."""
        work = self._work(quantity='3')
        resp = self._patch(work, {'quantity': '5'})
        self.assertEqual(resp.status_code, 200)
        work.refresh_from_db()
        self.assertEqual(work.quantity, Decimal('5'))

    def test_negative_quantity_rejected_before_confirm(self):
        work = self._work(quantity='3')
        resp = self._patch(work, {'quantity': '-2'})
        self.assertEqual(resp.status_code, 400)

    def test_quantity_lock_applies_to_admin_too(self):
        """Админ патчит через WorkRecordLimitedSerializer — защита та же."""
        work = self._work()
        confirm_work(work, self.owner)
        admin = User.objects.create_user(username='gr_admin', password='p',
                                         role=User.Role.ADMIN, company=self.company)
        api = APIClient()
        api.force_authenticate(admin)
        resp = api.patch(f'/api/v1/production/works/{work.id}/',
                         {'quantity': '9'}, format='json')
        self.assertEqual(resp.status_code, 400)
