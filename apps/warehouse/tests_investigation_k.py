"""
Расследование: отрицательная норма расхода в рецепте.

Воспроизведено до правки: RecipeItem.quantity_required=-5 принимался, и
confirm_work «дорисовывал» материал из воздуха (остаток рос вместо списания).
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.warehouse.models import FinishedProduct, RawMaterial

RECIPES = '/api/v1/warehouse/recipes/'
ITEMS = '/api/v1/warehouse/recipe-items/'


class RecipeItemMinValueTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RecipeCo', is_active=True)
        self.owner = User.objects.create_user(username='rec_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.material = RawMaterial.objects.create(
            company=self.company, name='Кирпич', stone_type='кирпич', unit='sht',
            quantity=Decimal('10'))
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Камин', quantity=Decimal('0'), unit='dona')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _recipe(self):
        resp = self.api.post(RECIPES, {
            'product': self.product.id, 'name': 'R', 'is_active': True,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.json()['id']

    def test_negative_quantity_required_rejected(self):
        recipe_id = self._recipe()
        resp = self.api.post(ITEMS, {
            'recipe': recipe_id, 'material': self.material.id,
            'quantity_required': '-5', 'unit': 'sht',
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('quantity_required', resp.data)

    def test_zero_quantity_required_rejected(self):
        recipe_id = self._recipe()
        resp = self.api.post(ITEMS, {
            'recipe': recipe_id, 'material': self.material.id,
            'quantity_required': '0', 'unit': 'sht',
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_positive_quantity_required_ok(self):
        recipe_id = self._recipe()
        resp = self.api.post(ITEMS, {
            'recipe': recipe_id, 'material': self.material.id,
            'quantity_required': '0.5', 'unit': 'sht',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
