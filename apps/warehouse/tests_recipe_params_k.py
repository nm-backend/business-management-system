"""
Параметры рецепта: код, габариты и ВЫХОД партии (макет «Рецепт», RCP-001).

Ключевое изменение — норма расхода задана на выход партии, а не на одно
изделие. Раньше выход всегда подразумевался равным единице: рецепт «из одной
плиты выходит 4 подоконника» приходилось пересчитывать вручную, и ошибка
попадала прямо в списание сырья.

Обратная совместимость обязательна: у существующих рецептов output_quantity = 1,
и расход обязан остаться прежним — это проверяется первым тестом.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.finance.models import LaborRate
from apps.orders.models import Order
from apps.production.models import Task, TaskStatus, WorkRecord
from apps.production.services import get_recipe_requirements
from apps.warehouse.models import FinishedProduct, RawMaterial, Recipe, RecipeItem

RECIPES = '/api/v1/warehouse/recipes/'


class RecipeParametersTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='RecipeCo')
        cls.owner = User.objects.create_user(
            username='rp_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='rp_worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )
        cls.material = RawMaterial.objects.create(
            company=cls.company, name='Мрамор оқ', unit='m2',
            quantity=Decimal('100'), avg_cost_price=Decimal('50.00'),
        )
        cls.product = FinishedProduct.objects.create(
            company=cls.company, name='Подоконник', unit='sht', quantity=Decimal('0'),
        )
        LaborRate.objects.create(
            company=cls.company, product=cls.product,
            operation=LaborRate.OperationType.CUTTING,
            rate_per_unit=Decimal('10.00'), unit='sht',
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _recipe(self, output='1', required='2'):
        recipe = Recipe.objects.create(
            company=self.company, product=self.product, name='Подоконник',
            code='RCP-001', size='2000x600', thickness=Decimal('20.00'),
            output_quantity=Decimal(output),
        )
        RecipeItem.objects.create(
            recipe=recipe, material=self.material,
            quantity_required=Decimal(required), unit='m2',
        )
        return recipe

    # ── Расчёт расхода ──────────────────────────────────────────────────────

    def test_default_output_keeps_old_behaviour(self):
        """Выход 1 (все существующие рецепты) — расход считается как раньше."""
        self._recipe(output='1', required='2')
        self.product.refresh_from_db()
        requirements = get_recipe_requirements(self.product, Decimal('3'))
        self.assertEqual(requirements[0][1], Decimal('6.000'))

    def test_batch_output_divides_requirement(self):
        """Из одной закладки 4 изделия: на 4 изделия нужна одна норма."""
        self._recipe(output='4', required='2.4')
        self.product.refresh_from_db()
        requirements = get_recipe_requirements(self.product, Decimal('4'))
        self.assertEqual(requirements[0][1], Decimal('2.400'))

    def test_partial_batch_is_proportional(self):
        """Два изделия из партии в четыре — половина нормы."""
        self._recipe(output='4', required='2.4')
        self.product.refresh_from_db()
        requirements = get_recipe_requirements(self.product, Decimal('2'))
        self.assertEqual(requirements[0][1], Decimal('1.200'))

    def test_write_off_uses_batch_output(self):
        """Подтверждение работы списывает ровно столько, сколько посчитал рецепт."""
        self._recipe(output='4', required='2.4')
        task = Task.objects.create(
            company=self.company, worker=self.worker, assigned_by=self.owner,
            status=TaskStatus.ACCEPTED, title='Подоконник',
        )
        work = WorkRecord.objects.create(
            company=self.company, task=task, worker=self.worker, product=self.product,
            quantity=Decimal('4'), unit='sht',
            operation=LaborRate.OperationType.CUTTING,
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION,
        )
        response = self.api.post(f'/api/v1/production/works/{work.id}/confirm/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)

        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('97.600'))

    def test_order_demand_uses_batch_output(self):
        """Потребность заказа в сырье считается по той же формуле, что и списание."""
        self._recipe(output='4', required='2.4')
        client = Client.objects.create(company=self.company, name='Акбаров')
        response = self.api.post('/api/v1/orders/orders/', {
            'client': client.id, 'product': self.product.id,
            'quantity': '8', 'unit': 'sht', 'total_amount': '100.00',
            'deadline': (timezone.now() + timezone.timedelta(days=2)).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)

        self.material.refresh_from_db()
        # 8 изделий / выход 4 = 2 закладки × 2.4 м² = 4.8 м²
        self.assertEqual(self.material.required_for_orders, Decimal('4.800'))

    def test_zero_output_does_not_crash(self):
        """Испорченные данные (выход 0) не делят на ноль, а трактуются как 1."""
        recipe = self._recipe(output='1', required='2')
        Recipe.objects.filter(pk=recipe.pk).update(output_quantity=Decimal('0'))
        self.product.refresh_from_db()
        requirements = get_recipe_requirements(self.product, Decimal('2'))
        self.assertEqual(requirements[0][1], Decimal('4.000'))

    # ── API ─────────────────────────────────────────────────────────────────

    def test_parameters_saved_and_returned(self):
        response = self.api.post(RECIPES, {
            'product': self.product.id, 'name': 'Подоконник 2000',
            'code': 'RCP-001', 'size': '2000x600', 'thickness': '20.00',
            'output_quantity': '4',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['code'], 'RCP-001')
        self.assertEqual(response.data['size'], '2000x600')
        self.assertEqual(Decimal(str(response.data['thickness'])), Decimal('20.00'))
        self.assertEqual(Decimal(str(response.data['output_quantity'])), Decimal('4.000'))

    def test_zero_output_rejected_by_api(self):
        response = self.api.post(RECIPES, {
            'product': self.product.id, 'name': 'Плохой', 'output_quantity': '0',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('output_quantity', response.data)

    def test_negative_thickness_rejected(self):
        response = self.api.post(RECIPES, {
            'product': self.product.id, 'name': 'Плохой', 'thickness': '-5',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_recipes_are_closed_for_worker(self):
        """
        Рецепты — инструмент владельца и администратора, работнику закрыты.

        В списке экранов работника из ТЗ рецептов нет: он видит задачу,
        складские количества и наличие материала. Права (IsOwnerOrAdmin) не
        ослабляем — тест фиксирует именно это поведение, чтобы доступ не
        «поехал» при будущих правках.
        """
        self._recipe()
        api = APIClient()
        api.force_authenticate(self.worker)
        self.assertEqual(api.get(RECIPES).status_code, 403)
        response = api.post(RECIPES, {
            'product': self.product.id, 'name': 'Свой рецепт',
        }, format='json')
        self.assertEqual(response.status_code, 403)

    def test_defaults_for_existing_recipes(self):
        """Рецепт, созданный без новых полей, получает выход 1 и пустые габариты."""
        recipe = Recipe.objects.create(
            company=self.company, product=self.product, name='Старый',
        )
        self.assertEqual(recipe.output_quantity, Decimal('1'))
        self.assertEqual(recipe.code, '')
        self.assertEqual(recipe.size, '')
        self.assertIsNone(recipe.thickness)
