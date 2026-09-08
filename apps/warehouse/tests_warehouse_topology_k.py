"""
Склады, ячейки хранения и занятость (макеты «Асосий омбор», «Омбордаги
жойлашув»: А-01…А-08, «Жами майдон 420 м², банд 86.1 %, бўш 13.9 %»).

Раньше склад в системе был ровно один и подразумевался неявно: у материала
было только текстовое «место хранения», поэтому ни переключателя складов, ни
карты ячеек с занятостью построить было нельзя.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.warehouse.models import RawMaterial, Warehouse, WarehouseCell

WAREHOUSES = '/api/v1/warehouse/warehouses/'
CELLS = '/api/v1/warehouse/cells/'
MATERIALS = '/api/v1/warehouse/raw-materials/'


class WarehouseTopologyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='Granit')
        cls.owner = User.objects.create_user(
            username='owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )
        cls.warehouse = Warehouse.objects.create(
            company=cls.company, name='Асосий омбор', code='MAIN',
            total_area=Decimal('420.00'), is_default=True,
        )
        cls.cell_a1 = WarehouseCell.objects.create(
            company=cls.company, warehouse=cls.warehouse, code='A-01',
            zone='a', capacity_area=Decimal('100.00'),
        )
        cls.cell_a2 = WarehouseCell.objects.create(
            company=cls.company, warehouse=cls.warehouse, code='A-02',
            zone='a', capacity_area=Decimal('100.00'),
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    # ── Модель занятости ────────────────────────────────────────────────────

    def test_cell_occupancy_uses_material_quantity_for_area_units(self):
        """Материал в м² занимает столько площади, сколько его лежит."""
        RawMaterial.objects.create(
            company=self.company, name='Гранит', unit='m2',
            quantity=Decimal('60'), warehouse=self.warehouse, cell=self.cell_a1,
        )
        self.assertEqual(self.cell_a1.occupied_area, Decimal('60'))
        self.assertEqual(self.cell_a1.occupancy_percent, Decimal('60.0'))

    def test_explicit_occupied_area_wins(self):
        RawMaterial.objects.create(
            company=self.company, name='Плитка', unit='sht',
            quantity=Decimal('500'), occupied_area=Decimal('25.50'),
            warehouse=self.warehouse, cell=self.cell_a1,
        )
        self.assertEqual(self.cell_a1.occupied_area, Decimal('25.50'))

    def test_piece_material_without_area_does_not_occupy(self):
        """Штучный материал без указанной площади габариты за пользователя не придумывает."""
        RawMaterial.objects.create(
            company=self.company, name='Крепёж', unit='sht',
            quantity=Decimal('1000'), warehouse=self.warehouse, cell=self.cell_a1,
        )
        self.assertEqual(self.cell_a1.occupied_area, Decimal('0'))

    def test_warehouse_percent_counts_from_total_area(self):
        RawMaterial.objects.create(
            company=self.company, name='Гранит', unit='m2',
            quantity=Decimal('210'), warehouse=self.warehouse, cell=self.cell_a1,
        )
        # 210 из 420 м² -> 50 %
        self.assertEqual(self.warehouse.occupancy_percent, Decimal('50.0'))

    # ── API ─────────────────────────────────────────────────────────────────

    def test_occupancy_endpoint_returns_map(self):
        RawMaterial.objects.create(
            company=self.company, name='Гранит', unit='m2',
            quantity=Decimal('84'), warehouse=self.warehouse, cell=self.cell_a1,
        )
        response = self.api.get(f'{WAREHOUSES}{self.warehouse.id}/occupancy/')
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data
        self.assertEqual(Decimal(str(data['total_area'])), Decimal('420.00'))
        self.assertEqual(Decimal(str(data['occupied_area'])), Decimal('84'))
        self.assertEqual(Decimal(str(data['occupancy_percent'])), Decimal('20.0'))
        self.assertEqual(Decimal(str(data['free_percent'])), Decimal('80.0'))
        codes = [cell['code'] for cell in data['cells']]
        self.assertEqual(codes, ['A-01', 'A-02'])

    def test_worker_can_read_but_not_change(self):
        api = APIClient()
        api.force_authenticate(self.worker)
        self.assertEqual(api.get(WAREHOUSES).status_code, 200)
        response = api.post(WAREHOUSES, {'name': 'Свой склад'}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_materials_filtered_by_warehouse_and_cell(self):
        other = Warehouse.objects.create(company=self.company, name='Иккинчи омбор')
        RawMaterial.objects.create(
            company=self.company, name='Гранит', unit='m2', quantity=Decimal('10'),
            warehouse=self.warehouse, cell=self.cell_a1,
        )
        RawMaterial.objects.create(
            company=self.company, name='Мрамор', unit='m2', quantity=Decimal('5'),
            warehouse=other,
        )
        response = self.api.get(MATERIALS, {'warehouse': self.warehouse.id})
        names = [row['name'] for row in (response.data['results'] if 'results' in response.data else response.data)]
        self.assertEqual(names, ['Гранит'])

        response = self.api.get(MATERIALS, {'cell': self.cell_a1.id})
        names = [row['name'] for row in (response.data['results'] if 'results' in response.data else response.data)]
        self.assertEqual(names, ['Гранит'])

    def test_material_cannot_be_placed_into_foreign_cell(self):
        other_company = Company.objects.create(name='Other')
        foreign_wh = Warehouse.objects.create(company=other_company, name='Чужой')
        foreign_cell = WarehouseCell.objects.create(
            company=other_company, warehouse=foreign_wh, code='B-01',
        )
        response = self.api.post(MATERIALS, {
            'name': 'Гранит', 'unit': 'm2', 'cell': foreign_cell.id,
        }, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('cell', response.data)

    def test_cell_must_belong_to_selected_warehouse(self):
        other = Warehouse.objects.create(company=self.company, name='Иккинчи омбор')
        response = self.api.post(MATERIALS, {
            'name': 'Гранит', 'unit': 'm2',
            'warehouse': other.id, 'cell': self.cell_a1.id,
        }, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('cell', response.data)

    def test_cell_without_warehouse_fills_warehouse_automatically(self):
        response = self.api.post(MATERIALS, {
            'name': 'Гранит', 'unit': 'm2', 'cell': self.cell_a1.id,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['warehouse'], self.warehouse.id)

    def test_single_default_warehouse_per_company(self):
        response = self.api.post(WAREHOUSES, {
            'name': 'Иккинчи омбор', 'is_default': True,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.warehouse.refresh_from_db()
        self.assertFalse(self.warehouse.is_default, 'старый склад перестаёт быть основным')

    def test_warehouse_with_materials_not_archived(self):
        RawMaterial.objects.create(
            company=self.company, name='Гранит', unit='m2', quantity=Decimal('1'),
            warehouse=self.warehouse,
        )
        response = self.api.delete(f'{WAREHOUSES}{self.warehouse.id}/')
        self.assertEqual(response.status_code, 403)
        self.warehouse.refresh_from_db()
        self.assertFalse(self.warehouse.is_archived)

    def test_empty_warehouse_archived_not_deleted(self):
        empty = Warehouse.objects.create(company=self.company, name='Пустой')
        response = self.api.delete(f'{WAREHOUSES}{empty.id}/')
        self.assertEqual(response.status_code, 204)
        empty.refresh_from_db()
        self.assertTrue(empty.is_archived)

    def test_other_company_warehouses_invisible(self):
        other_company = Company.objects.create(name='Other')
        Warehouse.objects.create(company=other_company, name='Чужой склад')
        response = self.api.get(WAREHOUSES)
        names = [row['name'] for row in (response.data['results'] if 'results' in response.data else response.data)]
        self.assertNotIn('Чужой склад', names)


class StockSeverityTests(TestCase):
    """Градация остатка «критично / ниже минимума / норма» (макет «Минимум қолдиқлар»)."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='Granit')
        cls.owner = User.objects.create_user(
            username='sev_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )

    def _material(self, quantity, min_stock, required=0):
        return RawMaterial.objects.create(
            company=self.company, name='Гранит', unit='m2',
            quantity=Decimal(quantity), min_stock=Decimal(min_stock),
            required_for_orders=Decimal(required),
        )

    def test_ok_when_stock_above_minimum(self):
        self.assertEqual(self._material('100', '10').stock_severity, 'ok')

    def test_low_when_at_minimum(self):
        self.assertEqual(self._material('10', '10').stock_severity, 'low')

    def test_critical_when_below_half_minimum(self):
        self.assertEqual(self._material('4', '10').stock_severity, 'critical')

    def test_critical_when_orders_consume_everything(self):
        self.assertEqual(self._material('10', '2', required='10').stock_severity, 'critical')

    def test_severity_exposed_in_api(self):
        self._material('4', '10')
        api = APIClient()
        api.force_authenticate(self.owner)
        response = api.get(MATERIALS)
        rows = response.data['results'] if 'results' in response.data else response.data
        self.assertEqual(rows[0]['stock_severity'], 'critical')


class QuickStatsAndDailySummaryTests(TestCase):
    """
    «Тезкор маълумот» и «Склад якуний (бугун)» из макета «Хом ашё омбори».

    Раньше summary отдавал только остатки по единицам и стоимость: сколько
    позиций на минимуме, сколько критично мало, что пришло и ушло сегодня —
    приходилось считать глазами по списку.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='Granit')
        cls.owner = User.objects.create_user(
            username='qs_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_quick_stats_counts_severity_recent_and_reserved(self):
        from datetime import timedelta

        from django.utils import timezone

        RawMaterial.objects.create(
            company=self.company, name='Норма', unit='m2',
            quantity=Decimal('100'), min_stock=Decimal('10'),
        )
        RawMaterial.objects.create(
            company=self.company, name='Минимум', unit='m2',
            quantity=Decimal('10'), min_stock=Decimal('10'),
        )
        RawMaterial.objects.create(
            company=self.company, name='Критично', unit='m2',
            quantity=Decimal('2'), min_stock=Decimal('10'),
        )
        RawMaterial.objects.create(
            company=self.company, name='Недавний приход', unit='m2',
            quantity=Decimal('50'), min_stock=Decimal('1'),
            arrival_date=timezone.localdate() - timedelta(days=2),
        )
        RawMaterial.objects.create(
            company=self.company, name='В резерве', unit='m2',
            quantity=Decimal('80'), min_stock=Decimal('1'),
            required_for_orders=Decimal('20'),
        )

        stats = self.api.get('/api/v1/warehouse/raw-materials/summary/').data['quick_stats']
        self.assertEqual(stats['low_stock_count'], 1)
        self.assertEqual(stats['critical_count'], 1)
        self.assertEqual(stats['recent_arrivals_count'], 1)
        self.assertEqual(stats['reserved_count'], 1)

    def test_today_summary_counts_incoming_and_outgoing(self):
        material = RawMaterial.objects.create(
            company=self.company, name='Гранит', unit='m2', quantity=Decimal('0'),
        )
        self.api.post(
            f'/api/v1/warehouse/raw-materials/{material.id}/incoming/',
            {'quantity': '45.20'}, format='json',
        )
        self.api.post(
            f'/api/v1/warehouse/raw-materials/{material.id}/outgoing/',
            {'quantity': '18.75'}, format='json',
        )
        today = self.api.get('/api/v1/warehouse/raw-materials/summary/').data['today']
        self.assertEqual(Decimal(str(today['incoming'])), Decimal('45.200'))
        self.assertEqual(Decimal(str(today['outgoing'])), Decimal('18.750'))
        self.assertEqual(Decimal(str(today['net'])), Decimal('26.450'))


class MaterialReturnTests(TestCase):
    """Возврат на склад — отдельный тип движения (вкладка «Қайтарилган»)."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='Granit')
        cls.owner = User.objects.create_user(
            username='ret_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='ret_worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.material = RawMaterial.objects.create(
            company=self.company, name='Гранит', unit='m2',
            quantity=Decimal('10'), avg_cost_price=Decimal('100.00'),
        )

    def test_return_increases_stock_with_return_movement(self):
        from apps.warehouse.models import StockMovement

        response = self.api.post(
            f'/api/v1/warehouse/raw-materials/{self.material.id}/returned/',
            {'quantity': '3', 'reason': 'Цех вернул остаток'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('13.000'))

        movement = StockMovement.objects.filter(material=self.material).latest('created_at')
        self.assertEqual(movement.movement_type, StockMovement.MovementType.RETURN)

    def test_return_does_not_change_average_cost(self):
        """Возврат — не поставка: себестоимость он пересчитывать не должен."""
        self.api.post(
            f'/api/v1/warehouse/raw-materials/{self.material.id}/returned/',
            {'quantity': '5'}, format='json',
        )
        self.material.refresh_from_db()
        self.assertEqual(self.material.avg_cost_price, Decimal('100.00'))

    def test_worker_cannot_return(self):
        api = APIClient()
        api.force_authenticate(self.worker)
        response = api.post(
            f'/api/v1/warehouse/raw-materials/{self.material.id}/returned/',
            {'quantity': '1'}, format='json',
        )
        self.assertEqual(response.status_code, 403)

    def test_return_history_filterable_by_type(self):
        self.api.post(
            f'/api/v1/warehouse/raw-materials/{self.material.id}/returned/',
            {'quantity': '2'}, format='json',
        )
        response = self.api.get('/api/v1/warehouse/stock-movements/', {'movement_type': 'return'})
        rows = response.data['results'] if 'results' in response.data else response.data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['movement_type'], 'return')


class MaterialConditionTests(TestCase):
    """Состояние партии «Аъло / Яхши / Қуйида / Критик» (макет «Хом ашё омбори»)."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='Granit')
        cls.owner = User.objects.create_user(
            username='cond_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )

    def test_condition_saved_and_returned(self):
        api = APIClient()
        api.force_authenticate(self.owner)
        response = api.post(MATERIALS, {
            'name': 'Гранит', 'unit': 'm2', 'condition': 'poor',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['condition'], 'poor')
        self.assertTrue(response.data['condition_display'])

    def test_unknown_condition_rejected(self):
        api = APIClient()
        api.force_authenticate(self.owner)
        response = api.post(MATERIALS, {
            'name': 'Гранит', 'unit': 'm2', 'condition': 'broken',
        }, format='json')
        self.assertEqual(response.status_code, 400)
