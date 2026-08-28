"""
Unit-тесты для приложения warehouse: свойства/строковые представления
моделей RawMaterial, FinishedProduct, StockMovement, Recipe, RecipeItem,
а также поведение мягкого удаления (archive/restore).
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.warehouse.models import (
    FinishedProduct,
    RawMaterial,
    Recipe,
    RecipeItem,
    StockMovement,
)


class RawMaterialTests(TestCase):
    def test_is_low_stock_when_quantity_at_or_below_min(self):
        m = RawMaterial(name='Marble', quantity=Decimal('5'), min_stock=Decimal('5'))
        self.assertTrue(m.is_low_stock)
        m.quantity = Decimal('4')
        self.assertTrue(m.is_low_stock)

    def test_not_low_stock_when_above_min(self):
        m = RawMaterial(name='Marble', quantity=Decimal('10'), min_stock=Decimal('5'))
        self.assertFalse(m.is_low_stock)

    def test_str_includes_quantity_and_unit(self):
        m = RawMaterial(name='Granite', quantity=Decimal('3.000'), unit='sht')
        self.assertEqual(str(m), 'Granite (3.000 Штук)')

    def test_archive_and_restore(self):
        m = RawMaterial.objects.create(name='Slab', quantity=Decimal('1'))
        m.archive()
        m.refresh_from_db()
        self.assertTrue(m.is_archived)
        self.assertIsNotNone(m.archived_at)

        m.restore()
        m.refresh_from_db()
        self.assertFalse(m.is_archived)
        self.assertIsNone(m.archived_at)


class FinishedProductTests(TestCase):
    def test_available_quantity_subtracts_reserved(self):
        p = FinishedProduct(name='Tile', quantity=Decimal('10'), required_for_orders=Decimal('3'))
        self.assertEqual(p.available_quantity, Decimal('7'))

    def test_is_low_stock_uses_available_quantity(self):
        p = FinishedProduct(
            name='Tile',
            quantity=Decimal('10'),
            required_for_orders=Decimal('8'),
            min_stock=Decimal('5'),
        )
        # available = 2 <= min_stock 5 -> low stock
        self.assertTrue(p.is_low_stock)

    def test_not_low_stock_when_available_above_min(self):
        p = FinishedProduct(
            name='Tile',
            quantity=Decimal('10'),
            required_for_orders=Decimal('1'),
            min_stock=Decimal('5'),
        )
        self.assertFalse(p.is_low_stock)

    def test_str_includes_quantity_and_unit(self):
        p = FinishedProduct(name='Countertop', quantity=Decimal('2.000'), unit='izdelie')
        self.assertEqual(str(p), 'Countertop (2.000 Изделие)')


class StockMovementCleanTests(TestCase):
    def setUp(self):
        self.material = RawMaterial.objects.create(name='M', quantity=Decimal('1'))
        self.product = FinishedProduct.objects.create(name='P', quantity=Decimal('1'))

    def test_valid_with_material_only(self):
        sm = StockMovement(movement_type='incoming', material=self.material, quantity=Decimal('1'))
        sm.clean()  # should not raise

    def test_error_when_both_material_and_product(self):
        sm = StockMovement(
            movement_type='incoming',
            material=self.material,
            product=self.product,
            quantity=Decimal('1'),
        )
        with self.assertRaises(ValidationError):
            sm.clean()

    def test_error_when_neither_material_nor_product(self):
        sm = StockMovement(movement_type='incoming', quantity=Decimal('1'))
        with self.assertRaises(ValidationError):
            sm.clean()


class RecipeTests(TestCase):
    def test_recipe_str(self):
        product = FinishedProduct.objects.create(name='Vase')
        recipe = Recipe.objects.create(product=product, name='Standard')
        self.assertEqual(str(recipe), 'Recipe for Vase: Standard')

    def test_recipe_item_str(self):
        product = FinishedProduct.objects.create(name='Vase')
        recipe = Recipe.objects.create(product=product, name='Standard')
        material = RawMaterial.objects.create(name='Clay')
        item = RecipeItem.objects.create(
            recipe=recipe, material=material, quantity_required=Decimal('2.000'), unit='sht'
        )
        self.assertEqual(str(item), '2.000 Штук of Clay')
