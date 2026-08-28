"""
Семантика потребности заказов (required_for_orders) на складе.

Модель однозначна:

    quantity            — физический остаток (>= 0);
    required_for_orders — ПОТРЕБНОСТЬ заказов (demand, >= 0), может превышать
                          физический остаток (overbooking);
    available_quantity  = quantity - required_for_orders (может быть < 0);
    shortage_quantity   = max(required_for_orders - quantity, 0);
    физического «резерва» (поштучного закрепления за заказом) в системе НЕТ —
    доступность проверяется по физическому остатку в момент выдачи/подтверждения.

Прежнее имя поля reserved_for_orders описывало логически невозможное состояние
(reserved > quantity); поле переименовано в required_for_orders.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct, RawMaterial, Recipe, RecipeItem

ORDERS = '/api/v1/orders/orders/'


class RequiredForOrdersSemanticsTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='ReqSemCo', is_active=True)
        self.owner = User.objects.create_user(username='rs_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.client = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('10'), unit='dona')
        self.material = RawMaterial.objects.create(
            company=self.company, name='Мрамор', quantity=Decimal('4'), unit='m2')
        recipe = Recipe.objects.create(company=self.company, product=self.product,
                                       name='Основной', is_active=True)
        RecipeItem.objects.create(recipe=recipe, material=self.material,
                                  quantity_required=Decimal('2'), unit='m2')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _deadline(self):
        return (timezone.now() + timedelta(days=5)).isoformat()

    def _order(self, product, quantity):
        resp = self.api.post(ORDERS, {
            'client': self.client.id, 'product': product.id,
            'quantity': str(quantity), 'unit': 'dona',
            'deadline': self._deadline(), 'total_amount': '1000',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        return resp.json()

    def test_field_is_named_required_for_orders(self):
        self.assertTrue(hasattr(FinishedProduct, 'required_for_orders'))
        self.assertTrue(hasattr(RawMaterial, 'required_for_orders'))
        self.assertFalse(hasattr(FinishedProduct, 'reserved_for_orders'))
        self.assertFalse(hasattr(RawMaterial, 'reserved_for_orders'))

    def test_product_requirement_can_exceed_stock(self):
        """Заказ 15 при остатке 10: потребность 15 > остатка, нехватка 5."""
        self._order(self.product, '15')
        self.product.refresh_from_db()
        self.assertEqual(self.product.required_for_orders, Decimal('15.000'))
        self.assertEqual(self.product.available_quantity, Decimal('-5.000'))
        self.assertEqual(self.product.shortage_quantity, Decimal('5.000'))

    def test_raw_material_requirement_can_exceed_stock(self):
        """Рецепт 2 м²/шт, заказ 3 шт при остатке 4 м²: потребность 6 > остатка."""
        self._order(self.product, '3')
        self.material.refresh_from_db()
        self.assertEqual(self.material.required_for_orders, Decimal('6.000'))
        self.assertEqual(self.material.available_quantity, Decimal('-2.000'))
        self.assertEqual(self.material.shortage_quantity, Decimal('2.000'))

    def test_order_flags_shortage_but_still_created(self):
        """Заказ с нехваткой создаётся и помечается has_product_shortage."""
        data = self._order(self.product, '15')
        self.assertTrue(data['has_product_shortage'])
        self.assertEqual(data['product_shortage']['available'], Decimal('10'))

    def test_delivery_guards_physical_stock(self):
        """Несмотря на overbooking, выдача сверх физического остатка невозможна."""
        data = self._order(self.product, '15')
        resp = self.api.post(f"{ORDERS}{data['id']}/deliver/", {}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['code'], 'not_enough_stock')
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('10.000'), 'остаток не тронут')

    def test_requirement_released_on_cancel(self):
        """Отмена снимает потребность, не трогая физический остаток."""
        data = self._order(self.product, '15')
        self.product.refresh_from_db()
        self.assertEqual(self.product.required_for_orders, Decimal('15.000'))
        resp = self.api.post(f"{ORDERS}{data['id']}/cancel/", {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self.product.refresh_from_db()
        self.assertEqual(self.product.required_for_orders, Decimal('0.000'))
        self.assertEqual(self.product.quantity, Decimal('10.000'))
