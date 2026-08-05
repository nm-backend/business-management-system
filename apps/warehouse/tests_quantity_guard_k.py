"""
Остаток меняется только складскими операциями, а не правкой карточки.

Воспроизведено до правки: PATCH quantity менял остаток сырья с 10 на 99999, а
журнал движений оставался пустым. Журнал переставал быть источником правды —
инвентаризацию не свести, себестоимость не проверить, злоупотребление внутри
компании не отследить: ни одна запись не говорила, кто и когда изменил цифру.

Это тот же класс, что и «выдача не писала движение», только дыра шире: правка
карточки доступна на каждом экране склада.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.warehouse.models import FinishedProduct, RawMaterial, StockMovement

MATERIALS = '/api/v1/warehouse/raw-materials/'
PRODUCTS = '/api/v1/warehouse/finished-products/'


class QuantityGuardTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='GuardCo', is_active=True)
        self.owner = User.objects.create_user(username='grd_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.material = RawMaterial.objects.create(
            company=self.company, name='Мрамор', quantity=Decimal('10'), unit='m2')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('10'), unit='dona')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_patch_cannot_change_material_stock(self):
        resp = self.api.patch(f'{MATERIALS}{self.material.id}/',
                              {'quantity': '99999'}, format='json')
        self.assertEqual(resp.status_code, 200, 'правка карточки не должна падать')
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('10.000'),
                         'остаток мимо журнала меняться не должен')

    def test_patch_cannot_change_product_stock(self):
        self.api.patch(f'{PRODUCTS}{self.product.id}/', {'quantity': '77777'}, format='json')
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('10.000'))

    def test_other_fields_still_editable(self):
        """Защищаем только количество: карточка должна оставаться рабочей."""
        resp = self.api.patch(f'{MATERIALS}{self.material.id}/',
                              {'name': 'Мрамор белый', 'min_stock': '3'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        self.material.refresh_from_db()
        self.assertEqual(self.material.name, 'Мрамор белый')
        self.assertEqual(self.material.min_stock, Decimal('3.000'))

    def test_initial_stock_can_be_set_on_creation(self):
        """Стартовый остаток при заведении позиции задать можно."""
        resp = self.api.post(MATERIALS, {'name': 'Гранит', 'quantity': '25',
                                         'unit': 'm2'}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:200])
        self.assertEqual(RawMaterial.objects.get(pk=resp.json()['id']).quantity,
                         Decimal('25.000'))

    def test_stock_changes_only_through_operations(self):
        """Приход и расход остаются рабочими и оставляют след."""
        self.api.post(f'{MATERIALS}{self.material.id}/incoming/',
                      {'quantity': '5'}, format='json')
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('15.000'))

        self.api.post(f'{MATERIALS}{self.material.id}/outgoing/',
                      {'quantity': '4'}, format='json')
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('11.000'))

        movements = StockMovement.objects.filter(material=self.material)
        self.assertEqual(movements.count(), 2, 'каждое изменение оставило запись')
        self.assertTrue(all(m.created_by == self.owner for m in movements),
                        'в журнале виден автор операции')

    def test_journal_matches_stock_after_operations(self):
        """
        Главный инвариант: остаток = стартовый + приходы − расходы.
        Если он держится, журналу можно доверять при инвентаризации.
        """
        start = self.material.quantity
        self.api.post(f'{MATERIALS}{self.material.id}/incoming/', {'quantity': '7'}, format='json')
        self.api.post(f'{MATERIALS}{self.material.id}/incoming/', {'quantity': '3'}, format='json')
        self.api.post(f'{MATERIALS}{self.material.id}/outgoing/', {'quantity': '6'}, format='json')

        incoming = sum(m.quantity for m in StockMovement.objects.filter(
            material=self.material, movement_type=StockMovement.MovementType.INCOMING))
        outgoing = sum(m.quantity for m in StockMovement.objects.filter(
            material=self.material, movement_type=StockMovement.MovementType.OUTGOING))
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, start + incoming - outgoing)
