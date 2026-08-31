"""
Stage 1 — ФИНАНСОВАЯ ИЗОЛЯЦИЯ: расширенные тесты (v2).

Покрывают:
- Утечку labor_rate через WorkRecordLimitedSerializer (админ НЕ должен видеть)
- Prod-серверные поля в production/works/ по ролям
- Прямой доступ к finance API для non-owner → 403
- Экспортные отчёты: admin/worker не видят финансовые колонки
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.clients.models import Client
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct, RawMaterial, Recipe, RecipeItem
from apps.finance.models import LaborRate
from apps.production.models import Task, TaskStatus, WorkRecord, WorkPhoto


# ── Утилиты ──────────────────────────────────────────────────────

FINANCIAL_KEYS = {
    'labor_rate', 'labor_cost', 'purchase_price', 'avg_cost_price',
    'cost_price', 'sale_price', 'total_amount', 'paid_amount',
    'total_orders_amount', 'total_paid', 'debt', 'price_per_unit',
    'rate_per_unit',
}


def deep_find_keys(obj, keys, path=''):
    """Рекурсивно ищет ключи из `keys` во вложенном JSON."""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys:
                found.append(f'{path}.{k}')
            found += deep_find_keys(v, keys, f'{path}.{k}')
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += deep_find_keys(v, keys, f'{path}[{i}]')
    return found


# ── Базовый setUp для всех тестов isolation v2 ────────────────────

class _IsolationBase(TestCase):
    """Создаёт компанию, 3 роли и минимальную инфраструктуру склада/производства."""

    def setUp(self):
        self.company = Company.objects.create(name='IsolCo')

        self.owner = User.objects.create_user(
            username='iso_owner', password='pw', role=User.Role.OWNER,
            company=self.company,
        )
        self.admin = User.objects.create_user(
            username='iso_admin', password='pw', role=User.Role.ADMIN,
            company=self.company,
        )
        self.worker = User.objects.create_user(
            username='iso_worker', password='pw', role=User.Role.WORKER,
            company=self.company,
        )

        # Склад
        self.material = RawMaterial.objects.create(
            company=self.company, name='Мрамор белый',
            quantity=Decimal('100'), purchase_price=Decimal('5000'),
            avg_cost_price=Decimal('3500'), unit='m2',
        )
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница',
            quantity=Decimal('10'), cost_price=Decimal('12000'),
            sale_price=Decimal('25000'), unit='izdelie',
        )

        # Рецепт
        self.recipe = Recipe.objects.create(
            company=self.company, product=self.product,
            name='Стандарт', is_active=True,
        )
        RecipeItem.objects.create(
            recipe=self.recipe, material=self.material,
            quantity_required=Decimal('2.5'), unit='m2',
        )

        # Ставка труда
        self.labor_rate = LaborRate.objects.create(
            company=self.company, product=self.product,
            operation=LaborRate.OperationType.CUTTING,
            rate_per_unit=Decimal('8000'), unit='izdelie',
        )

        # Клиент + заказ
        self.client_obj = Client.objects.create(
            company=self.company, name='ТестКлиент',
        )
        self.order = Order.objects.create(
            company=self.company, client=self.client_obj,
            product=self.product, quantity=Decimal('3'),
            unit='izdelie', status=Order.Status.IN_PROGRESS,
            total_amount=Decimal('75000'), paid_amount=Decimal('0'),
            deadline=datetime.date(2026, 12, 31),
        )

        # Задача + работа
        self.task = Task.objects.create(
            company=self.company, order=self.order,
            worker=self.worker, assigned_by=self.owner,
            status=TaskStatus.PENDING,
        )
        self.work = WorkRecord.objects.create(
            company=self.company, task=self.task,
            worker=self.worker, product=self.product,
            operation=LaborRate.OperationType.CUTTING,
            quantity=Decimal('3'), defect_quantity=Decimal('0'),
            unit='izdelie', labor_cost=Decimal('24000'),
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION,
        )

    def _api(self, user):
        api = APIClient()
        api.force_authenticate(user=user)
        return api


# ── Тесты утечки labor_rate ──────────────────────────────────────

class LaborRateLeakTests(_IsolationBase):
    """Admin НЕ должен видеть labor_rate и labor_cost в production/works/."""

    def test_admin_works_no_labor_rate(self):
        """Админ: /production/works/ — ни labor_rate, ни labor_cost."""
        resp = self._api(self.admin).get('/api/v1/production/works/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        leaks = deep_find_keys(data, {'labor_rate', 'labor_cost'})
        self.assertEqual(leaks, [], f'Admin увидел финансовые поля: {leaks}')

    def test_admin_works_has_is_confirmed(self):
        """Админ: /production/works/ — булевый статус is_confirmed на месте."""
        resp = self._api(self.admin).get('/api/v1/production/works/')
        self.assertEqual(resp.status_code, 200)
        results = resp.json().get('results', resp.json())
        if isinstance(results, dict) and 'results' in results:
            results = results['results']
        self.assertTrue(len(results) >= 1)
        work = results[0]
        self.assertIn('is_confirmed', work)
        self.assertFalse(work['is_confirmed'])

    def test_owner_works_has_labor_fields(self):
        """Владелец: /production/works/ — labor_rate И labor_cost на месте."""
        resp = self._api(self.owner).get('/api/v1/production/works/')
        self.assertEqual(resp.status_code, 200)
        results = resp.json().get('results', resp.json())
        if isinstance(results, dict) and 'results' in results:
            results = results['results']
        work = results[0]
        self.assertIn('labor_rate', work)
        self.assertIn('labor_cost', work)
        self.assertEqual(work['labor_cost'], '24000.00')

    def test_worker_works_sees_own_labor_cost(self):
        """Работник: /production/works/ — видит свой labor_cost."""
        resp = self._api(self.worker).get('/api/v1/production/works/')
        self.assertEqual(resp.status_code, 200)
        results = resp.json().get('results', resp.json())
        if isinstance(results, dict) and 'results' in results:
            results = results['results']
        work = results[0]
        self.assertIn('labor_cost', work)

    def test_manager_works_no_financial_data(self):
        """Менеджер: /production/works/ — без labor_rate и labor_cost."""
        manager = User.objects.create_user(
            username='iso_manager', password='pw', role=User.Role.MANAGER,
            company=self.company,
        )
        resp = self._api(manager).get('/api/v1/production/works/')
        self.assertEqual(resp.status_code, 200)
        leaks = deep_find_keys(resp.json(), {'labor_rate', 'labor_cost'})
        self.assertEqual(leaks, [], f'Manager увидел финансовые поля: {leaks}')


# ── Тесты утечки на складе ──────────────────────────────────────

class WarehouseLeakTests(_IsolationBase):
    """Admin/worker не видят purchase_price, avg_cost_price на складе."""

    def test_raw_material_admin_no_prices(self):
        resp = self._api(self.admin).get('/api/v1/warehouse/raw-materials/')
        self.assertEqual(resp.status_code, 200)
        leaks = deep_find_keys(resp.json(), {'purchase_price', 'avg_cost_price'})
        self.assertEqual(leaks, [], f'Admin увидел цены: {leaks}')

    def test_raw_material_worker_no_prices(self):
        resp = self._api(self.worker).get('/api/v1/warehouse/raw-materials/')
        self.assertEqual(resp.status_code, 200)
        leaks = deep_find_keys(resp.json(), {'purchase_price', 'avg_cost_price'})
        self.assertEqual(leaks, [], f'Worker увидел цены: {leaks}')

    def test_finished_product_admin_no_cost(self):
        resp = self._api(self.admin).get('/api/v1/warehouse/finished-products/')
        self.assertEqual(resp.status_code, 200)
        leaks = deep_find_keys(resp.json(), {'cost_price', 'sale_price'})
        self.assertEqual(leaks, [], f'Admin увидел себестоимость: {leaks}')

    def test_raw_material_owner_sees_prices(self):
        resp = self._api(self.owner).get('/api/v1/warehouse/raw-materials/')
        self.assertEqual(resp.status_code, 200)
        results = resp.json().get('results', resp.json())
        if isinstance(results, dict) and 'results' in results:
            results = results['results']
        item = results[0]
        self.assertIn('purchase_price', item)
        self.assertIn('avg_cost_price', item)

    def test_stock_movement_admin_no_price(self):
        """StockMovement: admin не видит price_per_unit."""
        from apps.warehouse.models import StockMovement
        StockMovement.objects.create(
            company=self.company, material=self.material,
            movement_type=StockMovement.MovementType.INCOMING,
            quantity=Decimal('10'), price_per_unit=Decimal('5000'),
            created_by=self.owner, reason='Тест',
        )
        resp = self._api(self.admin).get('/api/v1/warehouse/stock-movements/')
        self.assertEqual(resp.status_code, 200)
        leaks = deep_find_keys(resp.json(), {'price_per_unit'})
        self.assertEqual(leaks, [], f'Admin увидел price_per_unit: {leaks}')


# ── Тесты утечки в заказах ──────────────────────────────────────

class OrderLeakTests(_IsolationBase):
    """Admin/worker не видят total_amount, paid_amount в заказах."""

    def test_order_admin_no_amounts(self):
        resp = self._api(self.admin).get('/api/v1/orders/orders/')
        self.assertEqual(resp.status_code, 200)
        leaks = deep_find_keys(resp.json(), {'total_amount', 'paid_amount'})
        self.assertEqual(leaks, [], f'Admin увидел суммы: {leaks}')

    def test_order_worker_no_amounts(self):
        resp = self._api(self.worker).get('/api/v1/orders/orders/')
        self.assertEqual(resp.status_code, 200)
        leaks = deep_find_keys(resp.json(), {'total_amount', 'paid_amount'})
        self.assertEqual(leaks, [], f'Worker увидел суммы: {leaks}')

    def test_order_admin_sees_payment_status_string(self):
        """Admin видит текстовый payment_status, но не числовые суммы."""
        resp = self._api(self.admin).get('/api/v1/orders/orders/')
        self.assertEqual(resp.status_code, 200)
        results = resp.json().get('results', resp.json())
        if isinstance(results, dict) and 'results' in results:
            results = results['results']
        order = results[0]
        self.assertIn('payment_status', order)
        self.assertIn(order['payment_status'], ['unpaid', 'partial', 'paid'])


# ── Тесты утечки в клиентах ─────────────────────────────────────

class ClientLeakTests(_IsolationBase):
    """Admin не видит debt, total_paid, total_orders_amount."""

    def test_client_admin_no_financial_aggregates(self):
        resp = self._api(self.admin).get('/api/v1/clients/clients/')
        self.assertEqual(resp.status_code, 200)
        leaks = deep_find_keys(resp.json(), {'debt', 'total_paid', 'total_orders_amount'})
        self.assertEqual(leaks, [], f'Admin увидел финагрегаты: {leaks}')

    def test_client_admin_sees_has_debt_boolean(self):
        resp = self._api(self.admin).get('/api/v1/clients/clients/')
        self.assertEqual(resp.status_code, 200)
        results = resp.json().get('results', resp.json())
        if isinstance(results, dict) and 'results' in results:
            results = results['results']
        client = results[0]
        self.assertIn('has_debt', client)
        self.assertIsInstance(client['has_debt'], bool)


# ── Прямой доступ к finance API → 403 ───────────────────────────

class FinanceEndpointLockTests(_IsolationBase):
    """Все finance/эндпоинты закрыты для admin и worker (403)."""

    def test_finance_endpoints_403_for_admin_worker(self):
        endpoints = [
            '/api/v1/finance/expenses/',
            '/api/v1/finance/worker-payments/',
            '/api/v1/finance/worker-payments/settlements/',
        ]
        for user in (self.admin, self.worker):
            api = self._api(user)
            for url in endpoints:
                with self.subTest(role=user.role, url=url):
                    resp = api.get(url)
                    self.assertEqual(resp.status_code, 403,
                                     f'{user.role} получил {resp.status_code} на {url}')

    def test_reports_owner_endpoint_403_for_admin(self):
        resp = self._api(self.admin).get('/api/v1/reports/analytics/owner/')
        self.assertEqual(resp.status_code, 403)

    def test_reports_owner_endpoint_403_for_worker(self):
        resp = self._api(self.worker).get('/api/v1/reports/analytics/owner/')
        self.assertEqual(resp.status_code, 403)

    def test_export_finance_403_for_admin(self):
        resp = self._api(self.admin).get('/api/v1/reports/export/finance/')
        self.assertEqual(resp.status_code, 403)


# ── Экспортные отчёты: admin не видит финансовые колонки ─────────

class ExportLeakTests(_IsolationBase):
    """Экспорт orders/work для admin не содержит финансовых данных."""

    def test_orders_export_admin_no_debt_column(self):
        """Экспорт заказов admin: колонка «Қарз» отсутствует."""
        resp = self._api(self.admin).get(
            '/api/v1/reports/export/orders/', {'format': 'csv'},
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertNotIn('Қарз', content)

    def test_work_export_admin_no_accrued(self):
        """Экспорт работ admin: колонка «Начислено» отсутствует."""
        resp = self._api(self.admin).get(
            '/api/v1/reports/export/work/', {'format': 'csv'},
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertNotIn('Начислено', content)
