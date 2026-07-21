"""
Этап E.5 — регрессия mass-assignment / кросс-тенант через RecipeSerializer.

RecipeSerializer использует fields='__all__', из-за чего company и product были
записываемыми. perform_update не форсил company → владелец компании A мог
PATCH-ем перекинуть свой рецепт в компанию B или привязать его к продукту
чужой компании.

До фикса эти тесты падают (рецепт уезжает в чужую компанию/продукт),
после фикса — company read-only, product проверяется на company.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.warehouse.models import FinishedProduct, Recipe


class RecipeMassAssignTests(TestCase):
    def setUp(self):
        self.a = Company.objects.create(name='A')
        self.b = Company.objects.create(name='B')
        self.owner_a = User.objects.create_user(username='e5_oa', password='p',
                                                 role=User.Role.OWNER, company=self.a)
        self.prod_a = FinishedProduct.objects.create(company=self.a, name='PA',
                                                     quantity=Decimal('1'))
        self.prod_b = FinishedProduct.objects.create(company=self.b, name='PB',
                                                     quantity=Decimal('1'))
        self.recipe_a = Recipe.objects.create(company=self.a, product=self.prod_a,
                                              name='RA', is_active=True)

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_cannot_move_recipe_to_other_company(self):
        resp = self.api(self.owner_a).patch(
            f'/api/v1/warehouse/recipes/{self.recipe_a.id}/',
            {'company': self.b.id}, format='json')
        # company read-only: запрос может пройти (200), но company НЕ меняется.
        self.recipe_a.refresh_from_db()
        self.assertEqual(self.recipe_a.company_id, self.a.id)

    def test_cannot_attach_recipe_to_foreign_product(self):
        resp = self.api(self.owner_a).patch(
            f'/api/v1/warehouse/recipes/{self.recipe_a.id}/',
            {'product': self.prod_b.id}, format='json')
        self.assertEqual(resp.status_code, 403)
        self.recipe_a.refresh_from_db()
        self.assertEqual(self.recipe_a.product_id, self.prod_a.id)

    def test_create_recipe_forces_own_company(self):
        resp = self.api(self.owner_a).post('/api/v1/warehouse/recipes/', {
            'product': self.prod_a.id, 'name': 'New', 'company': self.b.id,
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        recipe = Recipe.objects.get(name='New')
        self.assertEqual(recipe.company_id, self.a.id)  # company форсится сервером

    def test_create_recipe_with_foreign_product_rejected(self):
        resp = self.api(self.owner_a).post('/api/v1/warehouse/recipes/', {
            'product': self.prod_b.id, 'name': 'X',
        }, format='json')
        self.assertEqual(resp.status_code, 403)
