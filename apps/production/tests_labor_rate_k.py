"""
РќР°С‡РёСЃР»РµРЅРёРµ СЂР°Р±РѕС‚РЅРёРєСѓ: РЅРѕР»СЊ Р±РѕР»СЊС€Рµ РЅРµ РЅР°С‡РёСЃР»СЏРµС‚СЃСЏ РјРѕР»С‡Р°.

Р’РѕСЃРїСЂРѕРёР·РІРµРґРµРЅРѕ РїРѕР»РЅРѕР№ С†РµРїРѕС‡РєРѕР№ Р·Р°РєР°Р· -> Р·Р°РґР°С‡Р° -> РїСЂРёРЅСЏС‚РёРµ -> СЃРґР°С‡Р° СЂР°Р±РѕС‚С‹ ->
РїРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ: СЃРєР»Р°Рґ РїРѕРїРѕР»РЅСЏР»СЃСЏ (0 -> 5, РґРІРёР¶РµРЅРёРµ production_in), Р° СЂР°Р±РѕС‚РЅРёРєСѓ
РЅР°С‡РёСЃР»СЏР»РѕСЃСЊ 0.00, РїРѕС‚РѕРјСѓ С‡С‚Рѕ РґР»СЏ С‚РѕРІР°СЂР° РЅРµ Р±С‹Р»Рѕ СЃС‚Р°РІРєРё. РќРё РѕС€РёР±РєРё, РЅРё
РїСЂРµРґСѓРїСЂРµР¶РґРµРЅРёСЏ: Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂ РІРёРґРµР» В«РїРѕРґС‚РІРµСЂР¶РґРµРЅРѕВ» Рё Р±С‹Р» СѓРІРµСЂРµРЅ, С‡С‚Рѕ РІСЃС‘ РІ
РїРѕСЂСЏРґРєРµ, Р° СЂР°Р±РѕС‚РЅРёРє РЅРµ РїРѕР»СѓС‡Р°Р» РЅРёС‡РµРіРѕ.

Р РµС€РµРЅРёРµ РІР»Р°РґРµР»СЊС†Р°: РїРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ Р±РµР· СЃС‚Р°РІРєРё Р·Р°РїСЂРµС‰РµРЅРѕ, СЃС‚Р°РІРєР° Р·Р°РґР°С‘С‚СЃСЏ РІ
РєР°СЂС‚РѕС‡РєРµ С‚РѕРІР°СЂР° СЂСЏРґРѕРј СЃ СЃРµР±РµСЃС‚РѕРёРјРѕСЃС‚СЊСЋ Рё С†РµРЅРѕР№ РїСЂРѕРґР°Р¶Рё.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.finance.models import LaborRate
from apps.production.models import WorkRecord
from apps.warehouse.models import FinishedProduct, RawMaterial, Recipe, RecipeItem, StockMovement

WORKS = '/api/v1/production/works/'
PRODUCTS = '/api/v1/warehouse/finished-products/'


class ConfirmRequiresLaborRateTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RateCo', is_active=True)
        self.owner = User.objects.create_user(username='rate_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='rate_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.product = FinishedProduct.objects.create(
            company=self.company, name='РЎС‚РѕР»РµС€РЅРёС†Р°', quantity=Decimal('0'), unit='dona')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _work(self):
        return WorkRecord.objects.create(
            company=self.company, worker=self.worker, product=self.product,
            quantity=Decimal('5'), unit='dona',
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION)

    def test_confirm_without_rate_is_refused(self):
        work = self._work()
        resp = self.api.post(f'{WORKS}{work.id}/confirm/')
        self.assertEqual(resp.status_code, 400, resp.content[:200])
        self.assertEqual(resp.json().get('code'), 'labor_rate_missing')
        self.assertIn('РЎС‚РѕР»РµС€РЅРёС†Р°', resp.json()['detail'])

    def test_refused_confirmation_changes_nothing(self):
        """РћС‚РєР°Р· РѕР±СЏР·Р°РЅ Р±С‹С‚СЊ С‡РёСЃС‚С‹Рј: РЅРё СЃРєР»Р°РґР°, РЅРё СЃС‚Р°С‚СѓСЃР°, РЅРё РЅР°С‡РёСЃР»РµРЅРёСЏ."""
        work = self._work()
        self.api.post(f'{WORKS}{work.id}/confirm/')
        work.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(work.status, WorkRecord.WorkStatus.AWAITING_CONFIRMATION)
        self.assertEqual(work.labor_cost, Decimal('0.00'))
        self.assertEqual(self.product.quantity, Decimal('0.000'))
        self.assertFalse(StockMovement.objects.filter(product=self.product).exists())

    def test_confirm_with_rate_accrues_and_stocks(self):
        LaborRate.objects.create(company=self.company, product=self.product,
                                 operation=LaborRate.OperationType.OTHER,
                                 rate_per_unit=Decimal('1500'), unit='dona')
        work = self._work()
        resp = self.api.post(f'{WORKS}{work.id}/confirm/')
        self.assertEqual(resp.status_code, 200, resp.content[:200])

        work.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(work.labor_cost, Decimal('7500.00'), '5 С€С‚ * 1500')
        self.assertEqual(self.product.quantity, Decimal('5.000'))
        self.assertTrue(StockMovement.objects.filter(
            product=self.product, movement_type=StockMovement.MovementType.PRODUCTION_IN).exists())

    def test_owner_can_still_set_amount_by_hand(self):
        """РЇРІРЅРѕ СѓРєР°Р·Р°РЅРЅР°СЏ РІР»Р°РґРµР»СЊС†РµРј СЃСѓРјРјР° СЃС‚Р°РІРєСѓ РЅРµ С‚СЂРµР±СѓРµС‚."""
        work = self._work()
        resp = self.api.post(f'{WORKS}{work.id}/confirm/', {'labor_cost': '2000'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        work.refresh_from_db()
        self.assertEqual(work.labor_cost, Decimal('2000.00'))

    def test_accrual_reaches_worker_settlements(self):
        """РќР°С‡РёСЃР»РµРЅРЅРѕРµ РѕР±СЏР·Р°РЅРѕ РґРѕР№С‚Рё РґРѕ СЂР°СЃС‡С‘С‚РѕРІ СЃ СЂР°Р±РѕС‚РЅРёРєР°РјРё Рё РґРѕ РґР°С€Р±РѕСЂРґР°."""
        LaborRate.objects.create(company=self.company, product=self.product,
                                 operation=LaborRate.OperationType.OTHER,
                                 rate_per_unit=Decimal('1000'), unit='dona')
        work = self._work()
        self.api.post(f'{WORKS}{work.id}/confirm/')

        rows = self.api.get('/api/v1/finance/worker-payments/settlements/').json()
        mine = [r for r in rows['results'] if r['worker'] == self.worker.id]
        self.assertEqual(len(mine), 1, 'СЂР°Р±РѕС‚РЅРёРє РѕР±СЏР·Р°РЅ РїРѕСЏРІРёС‚СЊСЃСЏ РІ СЂР°СЃС‡С‘С‚Р°С…')
        self.assertEqual(Decimal(str(mine[0]['accrued'])), Decimal('5000'))
        self.assertEqual(Decimal(str(mine[0]['balance'])), Decimal('5000'))

        dash = self.api.get('/api/v1/reports/analytics/owner/', {'period': 'year'}).json()
        self.assertEqual(Decimal(str(dash['worker_debts'])), Decimal('5000'),
                         'РґР°С€Р±РѕСЂРґ РѕР±СЏР·Р°РЅ РїРѕРєР°Р·С‹РІР°С‚СЊ С‚РѕС‚ Р¶Рµ РґРѕР»Рі')


class LaborRateOperationTests(TestCase):
    """
    РџРѕР»РЅС‹Р№ Р°СѓРґРёС‚: СЂР°Р±РѕС‚Р° РЅРµ Р·РЅР°Р»Р° СЃРІРѕСЋ РѕРїРµСЂР°С†РёСЋ, Рё РЅР°С‡РёСЃР»РµРЅРёРµ Р±СЂР°Р»Рѕ СЃС‚Р°РІРєСѓ
    РїРѕ Р°Р»С„Р°РІРёС‚Сѓ (order_by('operation') -> 'cutting'). РЈ С‚РѕРІР°СЂР° СЃ РЅРµСЃРєРѕР»СЊРєРёРјРё
    СЃС‚Р°РІРєР°РјРё СЂР°Р±РѕС‚РЅРёРє РїРѕР»СѓС‡Р°Р» РґРµРЅСЊРіРё Р·Р° С‡СѓР¶СѓСЋ РѕРїРµСЂР°С†РёСЋ. РўРµРїРµСЂСЊ РѕРїРµСЂР°С†РёСЋ
    СѓРєР°Р·С‹РІР°РµС‚ СЂР°Р±РѕС‚РЅРёРє, Р° СЃС‚Р°РІРєР° РІС‹Р±РёСЂР°РµС‚СЃСЏ РїРѕ РЅРµР№.
    """

    def setUp(self):
        self.company = Company.objects.create(name='OpCo', is_active=True)
        self.owner = User.objects.create_user(username='op_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='op_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.product = FinishedProduct.objects.create(
            company=self.company, name='РЎС‚РѕР»РµС€РЅРёС†Р°', quantity=Decimal('0'), unit='dona')
        self.material = RawMaterial.objects.create(
            company=self.company, name='Р“СЂР°РЅРёС‚', quantity=Decimal('100'), unit='m2')
        self.recipe = Recipe.objects.create(company=self.company, product=self.product, name='R')
        RecipeItem.objects.create(recipe=self.recipe, material=self.material,
                                  quantity_required=Decimal('1'))
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _work(self, **kwargs):
        defaults = dict(
            company=self.company, worker=self.worker, product=self.product,
            quantity=Decimal('5'), unit='dona',
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION)
        defaults.update(kwargs)
        return WorkRecord.objects.create(**defaults)

    def _rates(self):
        LaborRate.objects.create(company=self.company, product=self.product,
                                 operation=LaborRate.OperationType.CUTTING,
                                 rate_per_unit=Decimal('50'), unit='dona')
        LaborRate.objects.create(company=self.company, product=self.product,
                                 operation=LaborRate.OperationType.POLISHING,
                                 rate_per_unit=Decimal('70'), unit='dona')

    def test_work_uses_rate_of_its_operation(self):
        """РџРѕР»РёСЂРѕРІРєР° РґРѕР»Р¶РЅР° РЅР°С‡РёСЃР»РёС‚СЊ РїРѕ СЃС‚Р°РІРєРµ РїРѕР»РёСЂРѕРІРєРё, Р° РЅРµ РїРѕ В«Р°Р»С„Р°РІРёС‚РЅРѕР№В» СЂРµР·РєРµ."""
        self._rates()
        work = self._work(operation=LaborRate.OperationType.POLISHING)
        resp = self.api.post(f'{WORKS}{work.id}/confirm/')
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        work.refresh_from_db()
        self.assertEqual(work.labor_cost, Decimal('350.00'), '5 * 70 (РїРѕР»РёСЂРѕРІРєР°)')

    def test_cutting_uses_cutting_rate(self):
        self._rates()
        work = self._work(operation=LaborRate.OperationType.CUTTING)
        self.assertEqual(self.api.post(f'{WORKS}{work.id}/confirm/').status_code, 200)
        work.refresh_from_db()
        self.assertEqual(work.labor_cost, Decimal('250.00'), '5 * 50 (СЂРµР·РєР°)')

    def test_work_without_operation_uses_single_rate(self):
        """РћРґРЅР° СЃС‚Р°РІРєР° РЅР° С‚РѕРІР°СЂ Рё СЂР°Р±РѕС‚Р° Р±РµР· РѕРїРµСЂР°С†РёРё вЂ” РєР°Рє СЂР°РЅСЊС€Рµ."""
        LaborRate.objects.create(company=self.company, product=self.product,
                                 operation=LaborRate.OperationType.OTHER,
                                 rate_per_unit=Decimal('1500'), unit='dona')
        work = self._work()
        resp = self.api.post(f'{WORKS}{work.id}/confirm/')
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        work.refresh_from_db()
        self.assertEqual(work.labor_cost, Decimal('7500.00'))

    def test_multiple_rates_without_operation_are_not_guessed(self):
        """РќРµСЃРєРѕР»СЊРєРѕ СЃС‚Р°РІРѕРє Рё РѕРїРµСЂР°С†РёСЏ РЅРµ СѓРєР°Р·Р°РЅР° вЂ” РЅР°С‡РёСЃР»СЏС‚СЊ РЅРµР»СЊР·СЏ РЅР°СѓРіР°Рґ."""
        self._rates()
        work = self._work()
        resp = self.api.post(f'{WORKS}{work.id}/confirm/')
        self.assertEqual(resp.status_code, 400, resp.content[:200])
        self.assertEqual(resp.json().get('code'), 'labor_rate_missing')
        work.refresh_from_db()
        self.assertEqual(work.status, WorkRecord.WorkStatus.AWAITING_CONFIRMATION)

    def test_operation_saved_on_work_create(self):
        resp = self.api.post(WORKS, {
            'worker': self.worker.id, 'product': self.product.id,
            'operation': 'polishing', 'quantity': '2', 'unit': 'dona',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:200])
        work = WorkRecord.objects.get(pk=resp.json()['id'])
        self.assertEqual(work.operation, LaborRate.OperationType.POLISHING)

    def test_rates_can_be_filtered_by_product(self):
        self._rates()
        rows = self.api.get('/api/v1/finance/labor-rates/', {'product': self.product.id}).json()
        rows = rows['results'] if isinstance(rows, dict) else rows
        self.assertEqual(len(rows), 2)


class LaborRateOnProductCardTests(TestCase):
    """РЎС‚Р°РІРєР° Р·Р°РґР°С‘С‚СЃСЏ РІ РєР°СЂС‚РѕС‡РєРµ С‚РѕРІР°СЂР° вЂ” С‚Р°Рј Р¶Рµ, РіРґРµ СЃРµР±РµСЃС‚РѕРёРјРѕСЃС‚СЊ Рё С†РµРЅР°."""

    def setUp(self):
        self.company = Company.objects.create(name='CardCo', is_active=True)
        self.owner = User.objects.create_user(username='card_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_rate_can_be_set_on_create(self):
        resp = self.api.post(PRODUCTS, {
            'name': 'РџРѕРґРѕРєРѕРЅРЅРёРє', 'quantity': '0', 'unit': 'dona', 'labor_rate': '900',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:200])
        product = FinishedProduct.objects.get(pk=resp.json()['id'])
        self.assertEqual(product.labor_rates.count(), 1)
        self.assertEqual(product.labor_rates.first().rate_per_unit, Decimal('900.00'))
        self.assertEqual(resp.json()['labor_rate'], '900.00')

    def test_rate_is_updated_not_duplicated(self):
        pid = self.api.post(PRODUCTS, {'name': 'РЎС‚СѓРїРµРЅСЊ', 'quantity': '0',
                                       'unit': 'dona', 'labor_rate': '500'},
                            format='json').json()['id']
        self.api.patch(f'{PRODUCTS}{pid}/', {'labor_rate': '750'}, format='json')
        product = FinishedProduct.objects.get(pk=pid)
        self.assertEqual(product.labor_rates.count(), 1, 'СЃС‚Р°РІРєР° РѕРґРЅР°, Р° РЅРµ РєРѕРїРёС‚СЃСЏ')
        self.assertEqual(product.labor_rates.first().rate_per_unit, Decimal('750.00'))

    def test_saving_card_without_rate_keeps_it(self):
        pid = self.api.post(PRODUCTS, {'name': 'РџР»РёС‚Р°', 'quantity': '0',
                                       'unit': 'dona', 'labor_rate': '400'},
                            format='json').json()['id']
        self.api.patch(f'{PRODUCTS}{pid}/', {'name': 'РџР»РёС‚Р° 2'}, format='json')
        product = FinishedProduct.objects.get(pk=pid)
        self.assertEqual(product.labor_rates.first().rate_per_unit, Decimal('400.00'))

    def test_worker_does_not_see_the_rate(self):
        pid = self.api.post(PRODUCTS, {'name': 'РџР»РёС‚Р°', 'quantity': '0',
                                       'unit': 'dona', 'labor_rate': '400'},
                            format='json').json()['id']
        worker = User.objects.create_user(username='card_worker', password='p',
                                          role=User.Role.WORKER, company=self.company)
        api = APIClient()
        api.force_authenticate(worker)
        self.assertNotIn('labor_rate', api.get(f'{PRODUCTS}{pid}/').json())

    def _product_with_rates(self, name, rates):
        pid = self.api.post(PRODUCTS, {'name': name, 'quantity': '0', 'unit': 'dona'},
                            format='json').json()['id']
        product = FinishedProduct.objects.get(pk=pid)
        for operation, amount in rates.items():
            LaborRate.objects.create(company=self.company, product=product,
                                     operation=operation, rate_per_unit=amount,
                                     unit=product.unit)
        return pid

    def test_card_shows_other_rate_when_present(self):
        pid = self._product_with_rates('РЎС‚РѕР»РµС€РЅРёС†Р°', {
            LaborRate.OperationType.CUTTING: '1000',
            LaborRate.OperationType.OTHER: '2000',
        })
        data = self.api.get(f'{PRODUCTS}{pid}/').json()
        self.assertEqual(data['labor_rate'], '2000.00')

    def test_card_edits_other_rate_not_alphabetical_first(self):
        pid = self._product_with_rates('РЎС‚РѕР»РµС€РЅРёС†Р°', {
            LaborRate.OperationType.CUTTING: '1000',
            LaborRate.OperationType.OTHER: '2000',
        })
        self.api.patch(f'{PRODUCTS}{pid}/', {'labor_rate': '1800'}, format='json')
        product = FinishedProduct.objects.get(pk=pid)
        self.assertEqual(product.labor_rates.count(), 2, 'РґСѓР±Р»РёРєР°С‚ РЅРµ Р·Р°РІРѕРґРёС‚СЃСЏ')
        rates = {r.operation: r.rate_per_unit for r in product.labor_rates.all()}
        self.assertEqual(rates[LaborRate.OperationType.OTHER], Decimal('1800.00'))
        self.assertEqual(rates[LaborRate.OperationType.CUTTING], Decimal('1000.00'))

    def test_card_creates_other_when_rates_ambiguous(self):
        pid = self._product_with_rates('РџРѕРґРѕРєРѕРЅРЅРёРє', {
            LaborRate.OperationType.CUTTING: '1000',
            LaborRate.OperationType.POLISHING: '2000',
        })
        self.assertIsNone(self.api.get(f'{PRODUCTS}{pid}/').json()['labor_rate'])
        self.api.patch(f'{PRODUCTS}{pid}/', {'labor_rate': '1500'}, format='json')
        product = FinishedProduct.objects.get(pk=pid)
        self.assertEqual(product.labor_rates.count(), 3)
        rates = {r.operation: r.rate_per_unit for r in product.labor_rates.all()}
        self.assertEqual(rates[LaborRate.OperationType.OTHER], Decimal('1500.00'))
        self.assertEqual(rates[LaborRate.OperationType.CUTTING], Decimal('1000.00'))

    def test_card_edits_single_rate_directly(self):
        pid = self._product_with_rates('РџР»РёС‚Р°', {
            LaborRate.OperationType.CUTTING: '1000',
        })
        self.assertEqual(self.api.get(f'{PRODUCTS}{pid}/').json()['labor_rate'], '1000.00')
        self.api.patch(f'{PRODUCTS}{pid}/', {'labor_rate': '1700'}, format='json')
        product = FinishedProduct.objects.get(pk=pid)
        self.assertEqual(product.labor_rates.count(), 1, 'OTHER РЅРµ СЃРѕР·РґР°С‘С‚СЃСЏ СЂСЏРґРѕРј СЃ РѕРґРЅРѕР№ СЃС‚Р°РІРєРѕР№')
        self.assertEqual(product.labor_rates.first().rate_per_unit, Decimal('1700.00'))
