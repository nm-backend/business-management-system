"""
Счётчики и агрегаты склада (шапка макета «Хом ашё омбори»).

Макет: «Турлари 28 · Материаллар 156 · Қиймати 985 450 000 сўм» и чипы видов
камня с остатком («Оқ мрамор 250.75 м²»).

Семантика зафиксирована здесь, потому что «сколько типов» можно понять
по-разному:
  * Материаллар — число НЕархивных позиций справочника материалов;
  * Турлари — число РАЗНЫХ непустых значений stone_type среди них
    (незаполненный тип видом камня не считается);
  * чипы — сумма остатка по виду; при смешанных единицах суммы нет, только
    разбивка (складывать м² с кг бессмысленно).

Никаких выдуманных чисел: всё считается из реальных строк склада.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.warehouse.models import RawMaterial

SUMMARY = '/api/v1/warehouse/raw-materials/summary/'


class SummaryCountersTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='CounterCo')
        cls.owner = User.objects.create_user(
            username='sc_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='sc_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def material(self, name, stone_type='marble', unit='m2', quantity='10',
                 min_stock='0', required='0', archived=False, company=None,
                 avg_cost='0', arrival=None):
        return RawMaterial.objects.create(
            company=company or self.company, name=name, stone_type=stone_type,
            unit=unit, quantity=Decimal(quantity), min_stock=Decimal(min_stock),
            required_for_orders=Decimal(required), is_archived=archived,
            avg_cost_price=Decimal(avg_cost), arrival_date=arrival,
        )

    # ── Семантика счётчиков ─────────────────────────────────────────────────

    def test_counts_materials_and_distinct_types(self):
        self.material('Оқ мрамор', 'marble')
        self.material('Беж мрамор', 'marble')
        self.material('Қора гранит', 'granite')
        self.material('Травертин', 'travertine')

        data = self.api_as(self.owner).get(SUMMARY).data
        self.assertEqual(data['materials_count'], 4)
        self.assertEqual(data['types_count'], 3, 'мрамор дважды — это один вид камня')

    def test_empty_stone_type_is_not_a_type(self):
        self.material('Без типа', stone_type='')
        self.material('Гранит', 'granite')

        data = self.api_as(self.owner).get(SUMMARY).data
        self.assertEqual(data['materials_count'], 2)
        self.assertEqual(data['types_count'], 1)

    def test_archived_excluded_from_all_counters(self):
        self.material('Активный', 'granite', quantity='10')
        self.material('Архивный', 'onyx', quantity='999', archived=True)

        data = self.api_as(self.owner).get(SUMMARY).data
        self.assertEqual(data['materials_count'], 1)
        self.assertEqual(data['types_count'], 1)
        self.assertEqual(
            [row['quantity'] for row in data['unit_totals']],
            [Decimal('10.000')],
            'архивный остаток попал в итог',
        )
        self.assertNotIn('onyx', [t['stone_type'] for t in data['type_totals']])

    def test_empty_warehouse_returns_zeros_not_nulls(self):
        data = self.api_as(self.owner).get(SUMMARY).data
        self.assertEqual(data['materials_count'], 0)
        self.assertEqual(data['types_count'], 0)
        self.assertEqual(data['type_totals'], [])

    # ── Чипы видов камня ────────────────────────────────────────────────────

    def test_type_totals_sum_quantity_per_type(self):
        self.material('Оқ мрамор', 'marble', quantity='250.75')
        self.material('Беж мрамор', 'marble', quantity='120.00')
        self.material('Қора гранит', 'granite', quantity='180.30')

        types = {t['stone_type']: t for t in self.api_as(self.owner).get(SUMMARY).data['type_totals']}
        self.assertEqual(Decimal(str(types['marble']['quantity'])), Decimal('370.750'))
        self.assertEqual(types['marble']['unit'], 'm2')
        self.assertEqual(types['marble']['materials_count'], 2)
        self.assertEqual(Decimal(str(types['granite']['quantity'])), Decimal('180.300'))

    def test_mixed_units_within_type_have_no_single_total(self):
        """м² и кг одного вида складывать нельзя — отдаём разбивку, не сумму."""
        self.material('Гранит плита', 'granite', unit='m2', quantity='75.20')
        self.material('Гранит крошка', 'granite', unit='kg', quantity='300')

        granite = next(
            t for t in self.api_as(self.owner).get(SUMMARY).data['type_totals']
            if t['stone_type'] == 'granite'
        )
        self.assertIsNone(granite['quantity'])
        self.assertIsNone(granite['unit'])
        self.assertEqual(len(granite['unit_totals']), 2)
        self.assertEqual(
            sorted(u['unit'] for u in granite['unit_totals']), ['kg', 'm2'],
        )

    # ── Совпадение SQL и модели ─────────────────────────────────────────────

    def test_sql_severity_counters_match_model_property(self):
        """
        Счётчики из SQL обязаны совпасть со свойством stock_severity.

        Раньше они считались перебором в Python; при переносе в SQL легко
        разойтись в граничных случаях — тест сверяет оба способа.
        """
        self.material('Норма', quantity='100', min_stock='10')
        self.material('Минимум', quantity='10', min_stock='10')
        self.material('Критично', quantity='4', min_stock='10')
        self.material('Всё в резерве', quantity='10', min_stock='2', required='10')
        self.material('Без минимума', quantity='0', min_stock='0')

        expected_low = sum(
            1 for m in RawMaterial.objects.filter(company=self.company, is_archived=False)
            if m.stock_severity == 'low'
        )
        expected_critical = sum(
            1 for m in RawMaterial.objects.filter(company=self.company, is_archived=False)
            if m.stock_severity == 'critical'
        )

        stats = self.api_as(self.owner).get(SUMMARY).data['quick_stats']
        self.assertEqual(stats['low_stock_count'], expected_low)
        self.assertEqual(stats['critical_count'], expected_critical)

    def test_recent_and_reserved_counters(self):
        self.material('Недавний', quantity='5', arrival=timezone.localdate())
        self.material('Старый', quantity='5',
                      arrival=timezone.localdate() - timezone.timedelta(days=30))
        self.material('В резерве', quantity='50', min_stock='1', required='20')

        stats = self.api_as(self.owner).get(SUMMARY).data['quick_stats']
        self.assertEqual(stats['recent_arrivals_count'], 1)
        self.assertEqual(stats['reserved_count'], 1)

    # ── Изоляция и права ────────────────────────────────────────────────────

    def test_other_company_materials_not_counted(self):
        other = Company.objects.create(name='OtherCounterCo')
        self.material('Свой', 'granite', quantity='10')
        self.material('Чужой', 'onyx', quantity='999', company=other)

        data = self.api_as(self.owner).get(SUMMARY).data
        self.assertEqual(data['materials_count'], 1)
        self.assertEqual(data['types_count'], 1)
        self.assertNotIn('onyx', [t['stone_type'] for t in data['type_totals']])

    def test_admin_gets_counters_without_value(self):
        """Количества администратору положены, стоимость склада — нет."""
        self.material('Гранит', 'granite', quantity='10', avg_cost='100')
        data = self.api_as(self.admin).get(SUMMARY).data
        self.assertEqual(data['materials_count'], 1)
        self.assertNotIn('total_value', data)

    def test_owner_gets_total_value(self):
        self.material('Гранит', 'granite', quantity='10', avg_cost='100')
        data = self.api_as(self.owner).get(SUMMARY).data
        self.assertEqual(Decimal(str(data['total_value'])), Decimal('1000'))

    # ── Производительность ──────────────────────────────────────────────────

    def test_summary_query_count_does_not_grow_with_data(self):
        """
        Число запросов не должно зависеть от количества материалов.

        Прежний вариант тянул все строки и считал severity в Python: на складе
        из сотен позиций это заметно. Теперь всё считает SQL.
        """
        for index in range(30):
            self.material(f'Материал {index}', 'granite', quantity='5')

        api = self.api_as(self.owner)
        api.get(SUMMARY)  # прогреваем кеш подключений/сессии
        with self.assertNumQueries(6):
            api.get(SUMMARY)

        # Данных стало вдвое больше — число запросов то же самое.
        for index in range(30, 60):
            self.material(f'Материал {index}', 'granite', quantity='5')
        with self.assertNumQueries(6):
            api.get(SUMMARY)
