"""
Функции по макетам: штрихкод/зоны хранения сырья, расход (чиқариш),
итоговые показатели склада, рецепты (UI) и резервирование сырья под заказы.

Каждый блок проверяет то, чего не было до макетов:
- barcode/storage_zone — поля существовали только в UI, в API их не было;
- outgoing — операции «расход/потеря/корректировка» не было вовсе;
- summary — агрегатов склада не было;
- Recipe/RecipeItemViewSet — endpoints существовали, но UI рецептов не было;
- reserved_for_orders у сырья — резерв считался только для готовой продукции.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.orders.models import Order
from apps.warehouse.models import (
    FinishedProduct, RawMaterial, Recipe, RecipeItem, StockMovement,
)

MATERIALS = '/api/v1/warehouse/raw-materials/'
PRODUCTS = '/api/v1/warehouse/finished-products/'
RECIPES = '/api/v1/warehouse/recipes/'
RECIPE_ITEMS = '/api/v1/warehouse/recipe-items/'


class _Base(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='MockCo', is_active=True)
        self.owner = User.objects.create_user(username='mock_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.admin = User.objects.create_user(username='mock_admin', password='p',
                                              role=User.Role.ADMIN, company=self.company)
        self.worker = User.objects.create_user(username='mock_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.material = RawMaterial.objects.create(
            company=self.company, name='Гранит', quantity=Decimal('100'), unit='m2',
            avg_cost_price=Decimal('100'))
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('2'), unit='dona')

        # Подтверждение работы требует заданной ставки: без неё оно
        # отказывает, чтобы работнику не начислялся молча ноль.
        from apps.finance.models import LaborRate
        for _p in FinishedProduct.objects.filter(company=self.company):
            LaborRate.objects.get_or_create(
                company=self.company, product=_p,
                operation=LaborRate.OperationType.OTHER,
                defaults={'rate_per_unit': Decimal('100'), 'unit': _p.unit})
    def api(self, user=None):
        c = APIClient()
        c.force_authenticate(user or self.owner)
        return c


class BarcodeAndZoneTests(_Base):
    def test_material_supports_barcode_and_zone(self):
        r = self.api().post(MATERIALS, {
            'name': 'Мрамор', 'unit': 'm2',
            'barcode': '2001234567890', 'storage_zone': 'a',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content[:300])
        body = r.json()
        self.assertEqual(body['barcode'], '2001234567890')
        self.assertEqual(body['storage_zone'], 'a')
        self.assertEqual(body['storage_zone_display'], 'А зона')

    def test_barcode_is_searchable(self):
        self.material.barcode = '123456'
        self.material.save()
        r = self.api().get(f'{MATERIALS}?search=123456')
        ids = [row['id'] for row in r.json()['results']]
        self.assertEqual(ids, [self.material.id])

    def test_zone_is_filterable(self):
        other = RawMaterial.objects.create(company=self.company, name='Мрамор',
                                           storage_zone='b', quantity=Decimal('1'), unit='m2')
        r = self.api().get(f'{MATERIALS}?storage_zone=b')
        ids = [row['id'] for row in r.json()['results']]
        self.assertEqual(ids, [other.id])

    def test_document_number_saved_on_incoming(self):
        r = self.api().post(f'{MATERIALS}{self.material.id}/incoming/', {
            'quantity': '5', 'document_number': '№К-1258',
        }, format='json')
        self.assertEqual(r.status_code, 200, r.content[:300])
        m = StockMovement.objects.get(material=self.material,
                                      movement_type=StockMovement.MovementType.INCOMING)
        self.assertEqual(m.document_number, '№К-1258')


class OutgoingTests(_Base):
    def test_outgoing_reduces_quantity_and_writes_movement(self):
        r = self.api().post(f'{MATERIALS}{self.material.id}/outgoing/', {
            'quantity': '5', 'movement_type': 'outgoing', 'document_number': '№О-7',
        }, format='json')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('95.000'))
        m = StockMovement.objects.get(material=self.material,
                                      movement_type=StockMovement.MovementType.OUTGOING)
        self.assertEqual(m.quantity, Decimal('5.000'))
        self.assertEqual(m.document_number, '№О-7')

    def test_outgoing_limited_to_available_quantity(self):
        self.material.reserved_for_orders = Decimal('10')
        self.material.save()
        r = self.api().post(f'{MATERIALS}{self.material.id}/outgoing/', {
            'quantity': '95',  # available = 90
        }, format='json')
        self.assertEqual(r.status_code, 400, r.content[:300])
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('100.000'))

    def test_outgoing_reserved_material_blocked(self):
        self.material.reserved_for_orders = Decimal('100')
        self.material.save()
        r = self.api().post(f'{MATERIALS}{self.material.id}/outgoing/', {
            'quantity': '1',
        }, format='json')
        self.assertEqual(r.status_code, 400)
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('100.000'))

    def test_loss_and_adjustment_types_allowed(self):
        for mtype, expected in [('loss', StockMovement.MovementType.LOSS),
                                ('adjustment', StockMovement.MovementType.ADJUSTMENT)]:
            r = self.api().post(f'{MATERIALS}{self.material.id}/outgoing/', {
                'quantity': '1', 'movement_type': mtype,
            }, format='json')
            self.assertEqual(r.status_code, 200, r.content[:300])
            self.assertTrue(StockMovement.objects.filter(
                material=self.material, movement_type=expected).exists())

    def test_unknown_type_rejected(self):
        r = self.api().post(f'{MATERIALS}{self.material.id}/outgoing/', {
            'quantity': '1', 'movement_type': 'magic',
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_finished_product_can_be_written_off(self):
        r = self.api().post(f'{PRODUCTS}{self.product.id}/outgoing/', {
            'quantity': '1',
        }, format='json')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('1.000'))

    def test_worker_cannot_write_off(self):
        r = self.api(self.worker).post(f'{MATERIALS}{self.material.id}/outgoing/', {
            'quantity': '1',
        }, format='json')
        self.assertEqual(r.status_code, 403)
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('100.000'))


class SummaryTests(_Base):
    def test_summary_shows_total_quantity(self):
        RawMaterial.objects.create(company=self.company, name='Мрамор',
                                   quantity=Decimal('30'), unit='m2')
        r = self.api().get(f'{MATERIALS}summary/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        # DRF сериализует Decimal как float (130.0) — сравниваем численно.
        self.assertEqual(Decimal(str(r.json()['total_quantity'])), Decimal('130'))

    def test_summary_value_only_for_owner(self):
        r = self.api().get(f'{MATERIALS}summary/')
        self.assertIn('total_value', r.json())

        r = self.api(self.admin).get(f'{MATERIALS}summary/')
        self.assertNotIn('total_value', r.json())

    def test_worker_can_see_summary_counts(self):
        r = self.api(self.worker).get(f'{MATERIALS}summary/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertIn('total_quantity', r.json())


class RecipeAPITests(_Base):
    def setUp(self):
        super().setUp()
        self.m2 = RawMaterial.objects.create(company=self.company, name='Клей',
                                             quantity=Decimal('50'), unit='kg')

        # Подтверждение работы требует заданной ставки: без неё оно
        # отказывает, чтобы работнику не начислялся молча ноль.
        from apps.finance.models import LaborRate
        for _p in FinishedProduct.objects.filter(company=self.company):
            LaborRate.objects.get_or_create(
                company=self.company, product=_p,
                operation=LaborRate.OperationType.OTHER,
                defaults={'rate_per_unit': Decimal('100'), 'unit': _p.unit})
    def _make_recipe(self, **kw):
        data = {'product': self.product.id, 'name': 'Стандарт', **kw}
        r = self.api().post(RECIPES, data, format='json')
        self.assertEqual(r.status_code, 201, r.content[:300])
        return r.json()

    def test_create_recipe_with_items(self):
        recipe = self._make_recipe()
        r = self.api().post(RECIPE_ITEMS, {
            'recipe': recipe['id'], 'material': self.material.id,
            'quantity_required': '2.5', 'unit': 'm2',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content[:300])
        item = RecipeItem.objects.get(pk=r.json()['id'])
        self.assertEqual(item.quantity_required, Decimal('2.500'))
        self.assertEqual(item.material_id, self.material.id)

    def test_recipe_serializer_embeds_items_and_names(self):
        recipe = self._make_recipe()
        self.api().post(RECIPE_ITEMS, {
            'recipe': recipe['id'], 'material': self.material.id,
            'quantity_required': '2.5', 'unit': 'm2',
        }, format='json')
        body = self.api().get(f'{RECIPES}{recipe["id"]}/').json()
        self.assertEqual(len(body['items']), 1)
        self.assertEqual(body['items'][0]['material_name'], 'Гранит')

    def test_recipe_cannot_be_deleted(self):
        recipe = self._make_recipe()
        r = self.api().delete(f'{RECIPES}{recipe["id"]}/')
        self.assertEqual(r.status_code, 405)

    def test_recipe_item_cannot_be_deleted(self):
        recipe = self._make_recipe()
        item = self.api().post(RECIPE_ITEMS, {
            'recipe': recipe['id'], 'material': self.material.id,
            'quantity_required': '1', 'unit': 'm2',
        }, format='json').json()
        r = self.api().delete(f'{RECIPE_ITEMS}{item["id"]}/')
        self.assertEqual(r.status_code, 405)

    def test_cross_company_recipe_blocked(self):
        other = Company.objects.create(name='Чужая', is_active=True)
        stranger = User.objects.create_user(username='str_owner', password='p',
                                            role=User.Role.OWNER, company=other)
        r = self.api(stranger).post(RECIPES, {
            'product': self.product.id, 'name': 'Хак',
        }, format='json')
        self.assertEqual(r.status_code, 403)

    def test_worker_cannot_manage_recipes(self):
        r = self.api(self.worker).post(RECIPES, {
            'product': self.product.id, 'name': 'Воркер',
        }, format='json')
        self.assertEqual(r.status_code, 403)


class RawMaterialReservationTests(_Base):
    """Резерв сырья: создание заказа -> +резерв, отмена/выдача -> -резерв."""

    def setUp(self):
        super().setUp()
        self.cli = Client.objects.create(company=self.company, name='Клиент')
        self.recipe = Recipe.objects.create(
            company=self.company, product=self.product, name='Стандарт')
        RecipeItem.objects.create(recipe=self.recipe, material=self.material,
                                  quantity_required=Decimal('2'), unit='m2')

        # Подтверждение работы требует заданной ставки: без неё оно
        # отказывает, чтобы работнику не начислялся молча ноль.
        from apps.finance.models import LaborRate
        for _p in FinishedProduct.objects.filter(company=self.company):
            LaborRate.objects.get_or_create(
                company=self.company, product=_p,
                operation=LaborRate.OperationType.OTHER,
                defaults={'rate_per_unit': Decimal('100'), 'unit': _p.unit})
    def _create_order(self, **kw):
        r = self.api().post('/api/v1/orders/orders/', {
            'client': self.cli.id, 'product': self.product.id,
            'quantity': '3', 'unit': 'dona', **kw,
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content[:300])
        return r.json()['id']

    def test_order_create_reserves_raw_materials(self):
        # Рецепт: 2 м2 на 1 товар -> 3 товара резервируют 6 м2.
        self._create_order()
        self.material.refresh_from_db()
        self.assertEqual(self.material.reserved_for_orders, Decimal('6.000'))

    def test_order_cancel_releases_raw_materials(self):
        order_id = self._create_order()
        self.material.refresh_from_db()
        self.assertEqual(self.material.reserved_for_orders, Decimal('6.000'))

        r = self.api().post(f'/api/v1/orders/orders/{order_id}/cancel/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.material.refresh_from_db()
        self.assertEqual(self.material.reserved_for_orders, Decimal('0.000'))

    def test_order_deliver_releases_raw_materials(self):
        # Выдача теперь списывает готовую продукцию, поэтому нужен запас.
        # Тест про снятие резерва сырья, а не про остаток товара.
        self.product.quantity = Decimal('100')
        self.product.save(update_fields=['quantity'])
        order_id = self._create_order()
        r = self.api().post(f'/api/v1/orders/orders/{order_id}/deliver/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.material.refresh_from_db()
        self.assertEqual(self.material.reserved_for_orders, Decimal('0.000'))

    def test_order_quantity_update_resyncs_raw_reservation(self):
        order_id = self._create_order()  # 3 шт -> резерв 6 м2
        r = self.api().patch(f'/api/v1/orders/orders/{order_id}/',
                             {'quantity': '5'}, format='json')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.material.refresh_from_db()
        # (5 - 3) * 2 = 4 м2 дополнительно; но пересчёт через release+reserve
        # должен дать ровно 5 * 2 = 10 м2.
        self.assertEqual(self.material.reserved_for_orders, Decimal('10.000'))

    def test_order_without_recipe_reserves_nothing(self):
        other = FinishedProduct.objects.create(company=self.company,
                                               name='Просто товар', quantity=Decimal('1'))
        r = self.api().post('/api/v1/orders/orders/', {
            'client': self.cli.id, 'product': other.id,
            'quantity': '2', 'unit': 'dona',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content[:300])
        self.material.refresh_from_db()
        self.assertEqual(self.material.reserved_for_orders, Decimal('0.000'))

    def test_confirm_work_consumes_and_releases_reservation(self):
        from apps.production.models import Task, TaskStatus, WorkRecord
        order_id = self._create_order()
        order = Order.objects.get(pk=order_id)
        self.material.refresh_from_db()
        self.assertEqual(self.material.reserved_for_orders, Decimal('6.000'))

        task = Task.objects.create(
            company=self.company, order=order, worker=self.worker,
            status=TaskStatus.ACCEPTED)
        work = WorkRecord.objects.create(
            company=self.company, task=task, worker=self.worker,
            product=order.product, quantity=order.quantity, unit='dona',
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION)

        from apps.production.services import confirm_work
        confirm_work(work, self.owner)

        self.material.refresh_from_db()
        # 100 - 6 = 94; резерв полностью израсходован.
        self.assertEqual(self.material.quantity, Decimal('94.000'))
        self.assertEqual(self.material.reserved_for_orders, Decimal('0.000'))
