"""
Панель фильтра склада и экран «Минимум қолдиқлар».

Фильтры серверные: отбор загруженной страницы показывал бы чужие позиции
начиная со второй. stock_severity считается тем же SQL, что и
summary.quick_stats / RawMaterial.stock_severity — иначе шапка и список
расходились бы.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.core.tests_tz_compliance_k import collect_money_keys
from apps.warehouse.models import RawMaterial

MATERIALS = '/api/v1/warehouse/raw-materials/'
SUMMARY = '/api/v1/warehouse/raw-materials/summary/'


class WarehouseListFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='FilterCo')
        cls.owner = User.objects.create_user(
            username='wf_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='wf_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='wf_worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )
        cls.ok = cls._material(
            'Норма', quantity='100', min_stock='10',
            stone_type='marble', color='Белый', size='300x200',
            unit='m2', condition='excellent',
        )
        cls.low = cls._material(
            'Минимум', quantity='10', min_stock='10',
            stone_type='granite', color='Серый', size='600x400',
            unit='m2', condition='good',
        )
        cls.critical = cls._material(
            'Критично', quantity='4', min_stock='10',
            stone_type='granite', color='Чёрный', size='600x400',
            unit='kg', condition='poor',
        )
        cls.other_company = Company.objects.create(name='OtherFilterCo')
        cls._material(
            'Чужой критичный', quantity='1', min_stock='10',
            stone_type='granite', color='Серый', company=cls.other_company,
        )

    @classmethod
    def _material(cls, name, quantity='10', min_stock='0', required='0',
                  stone_type='marble', color='', size='', unit='m2',
                  condition='', company=None):
        return RawMaterial.objects.create(
            company=company or cls.company, name=name, stone_type=stone_type,
            color=color, size=size, unit=unit, condition=condition or '',
            quantity=Decimal(quantity), min_stock=Decimal(min_stock),
            required_for_orders=Decimal(required),
        )

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def names(self, user, params):
        rows = self.api_as(user).get(MATERIALS, params).data
        rows = rows['results'] if 'results' in rows else rows
        return {row['name'] for row in rows}

    def test_stone_type_is_exact_server_filter(self):
        names = self.names(self.owner, {'is_archived': 'false', 'stone_type': 'granite'})
        self.assertEqual(names, {'Минимум', 'Критично'})

    def test_color_is_icontains(self):
        # Подстрока, не точное совпадение: «Бел» находит «Белый».
        # Регистр кириллицы на SQLite не сворачивается — в проде PostgreSQL
        # icontains регистронезависим; здесь проверяем сам contains.
        names = self.names(self.owner, {'is_archived': 'false', 'color': 'Бел'})
        self.assertEqual(names, {'Норма'})

    def test_size_is_icontains(self):
        names = self.names(self.owner, {'is_archived': 'false', 'size': '600'})
        self.assertEqual(names, {'Минимум', 'Критично'})

    def test_unit_and_condition(self):
        names = self.names(self.owner, {'is_archived': 'false', 'unit': 'kg'})
        self.assertEqual(names, {'Критично'})
        names = self.names(self.owner, {'is_archived': 'false', 'condition': 'good'})
        self.assertEqual(names, {'Минимум'})

    def test_stock_severity_matches_model_and_summary(self):
        expected = {
            m.name: m.stock_severity
            for m in RawMaterial.objects.filter(company=self.company, is_archived=False)
        }
        self.assertEqual(expected['Норма'], 'ok')
        self.assertEqual(expected['Минимум'], 'low')
        self.assertEqual(expected['Критично'], 'critical')

        self.assertEqual(
            self.names(self.owner, {'stock_severity': 'ok'}), {'Норма'},
        )
        self.assertEqual(
            self.names(self.owner, {'stock_severity': 'low'}), {'Минимум'},
        )
        self.assertEqual(
            self.names(self.owner, {'stock_severity': 'critical'}), {'Критично'},
        )
        self.assertEqual(
            self.names(self.owner, {'stock_severity': 'below_min'}),
            {'Минимум', 'Критично'},
        )

        stats = self.api_as(self.owner).get(SUMMARY).data['quick_stats']
        self.assertEqual(stats['low_stock_count'], 1)
        self.assertEqual(stats['critical_count'], 1)

    def test_unknown_stock_severity_returns_empty_not_all(self):
        names = self.names(self.owner, {'stock_severity': 'magic'})
        self.assertEqual(names, set())

    def test_filters_are_tenant_scoped(self):
        names = self.names(self.owner, {'stock_severity': 'critical'})
        self.assertNotIn('Чужой критичный', names)
        names = self.names(self.owner, {'color': 'Серый'})
        self.assertEqual(names, {'Минимум'})

    def test_admin_and_worker_can_filter_without_money(self):
        for user in (self.admin, self.worker):
            response = self.api_as(user).get(
                MATERIALS, {'is_archived': 'false', 'stock_severity': 'below_min'},
            )
            self.assertEqual(response.status_code, 200, user.username)
            leaks = collect_money_keys(response.data)
            self.assertFalse(leaks, f'{user.username} получил деньги: {leaks}')
            rows = response.data['results'] if 'results' in response.data else response.data
            self.assertEqual({row['name'] for row in rows}, {'Минимум', 'Критично'})
