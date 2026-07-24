"""
Детальная проверка финансовой изоляции в реальном API SkladPro.Nod.

Проверяет, что сервер НЕ отправляет финансовые данные:
- Администратору (Admin) — нигде
- Работнику (Worker) — кроме своего заработка
- Владелец (Owner) видит всё

Тестируемые эндпоинты:
- /api/v1/warehouse/raw-materials/
- /api/v1/warehouse/finished-products/
- /api/v1/warehouse/stock-movements/
- /api/v1/orders/orders/
- /api/v1/clients/clients/
- /api/v1/production/works/
- /api/v1/production/tasks/
- /api/v1/finance/expenses/
- /api/v1/finance/labor-rates/
- /api/v1/finance/worker-payments/
- /api/v1/reports/analytics/owner/
- /api/v1/reports/analytics/admin/
- /api/v1/reports/export/finance/
- /api/v1/clients/payments/
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company

# Все финансовые поля, которые НЕ должны утекать к Admin/Worker
OWNER_ONLY_FIELDS = {
    'purchase_price',      # закупочная цена (RawMaterial)
    'avg_cost_price',       # средняя себестоимость (RawMaterial)
    'cost_price',          # себестоимость (FinishedProduct)
    'sale_price',          # продажная цена (FinishedProduct)
    'total_amount',        # сумма заказа (Order)
    'paid_amount',         # оплачено по заказу (Order)
    'total_orders_amount', # сумма всех заказов клиента (Client)
    'total_paid',          # всего оплачено клиентом (Client)
    'debt',                # долг клиента (Client)
    'labor_cost',          # стоимость труда (WorkRecord)
    'rate_per_unit',       # ставка за единицу (LaborRate)
    'price_per_unit',      # цена за единицу (StockMovement)
    'amount',              # сумма (Expense, WorkerPayment, Payment)
}


def api_results(response):
    """Извлекает список результатов из пагинированного DRF-ответа."""
    data = response.json()
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and 'results' in data:
        return data['results']
    return data


def deep_find(obj, keys, path=''):
    """Рекурсивно ищет ключи из keys в obj, возвращает пути найденных."""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys:
                found.append(f'{path}.{k}' if path else k)
            found += deep_find(v, keys, f'{path}.{k}' if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += deep_find(v, keys, f'{path}[{i}]')
    return found


class DetailedMoneyIsolationTests(TestCase):
    """Проверка, что Admin и Worker не получают финансовые поля через API."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='IsolationCo')

        # Создаём роли
        cls.owner = User.objects.create_user(
            username='owner', password='pass123',
            role=User.Role.OWNER, company=cls.company,
            phone='+998901111111',
        )
        cls.admin = User.objects.create_user(
            username='admin_x', password='pass123',
            role=User.Role.ADMIN, company=cls.company,
            phone='+998902222222',
        )
        cls.worker = User.objects.create_user(
            username='worker_x', password='pass123',
            role=User.Role.WORKER, company=cls.company,
            phone='+998903333333',
        )
        # Ещё один работник для проверки изоляции заработка
        cls.other_worker = User.objects.create_user(
            username='worker_y', password='pass123',
            role=User.Role.WORKER, company=cls.company,
            phone='+998904444444',
        )

        # ── Склад сырья ──
        from apps.warehouse.models import RawMaterial, UnitChoices
        cls.material = RawMaterial.objects.create(
            company=cls.company, name='Мрамор белый',
            stone_type='мрамор', color='белый',
            size='200x300', thickness=2,
            unit=UnitChoices.SHT,
            quantity=Decimal('100'),
            storage_location='Стеллаж А1',
            min_stock=Decimal('10'),
            purchase_price=Decimal('50000'),     # только owner
            avg_cost_price=Decimal('48000'),     # только owner
        )

        # ── Готовая продукция ──
        from apps.warehouse.models import FinishedProduct
        cls.product = FinishedProduct.objects.create(
            company=cls.company, name='Столешница белая',
            category='столешницы',
            unit=UnitChoices.IZDELIE,
            quantity=Decimal('10'),
            min_stock=Decimal('2'),
            cost_price=Decimal('150000'),        # только owner
            sale_price=Decimal('300000'),        # только owner
        )

        # ── Рецепт ──
        from apps.warehouse.models import Recipe, RecipeItem
        cls.recipe = Recipe.objects.create(
            company=cls.company, name='Рецепт столешницы',
            product=cls.product, is_active=True,
        )
        RecipeItem.objects.create(
            recipe=cls.recipe, material=cls.material,
            quantity_required=Decimal('2'), unit=UnitChoices.SHT,
        )

        # ── Клиент ──
        from apps.clients.models import Client
        cls.client = Client.objects.create(
            company=cls.company, name='ООО СтройСервис',
            phone='+998905555555',
            total_orders_amount=Decimal('600000'),  # только owner
            total_paid=Decimal('200000'),            # только owner
            debt=Decimal('400000'),                  # только owner
        )

        # ── Заказ ──
        from apps.orders.models import Order
        cls.order = Order.objects.create(
            company=cls.company, client=cls.client,
            product=cls.product, quantity=Decimal('2'),
            unit='izdelie',
            total_amount=Decimal('600000'),   # только owner
            paid_amount=Decimal('200000'),    # только owner
            worker=cls.worker,
            status=Order.Status.IN_PROGRESS,
            deadline=datetime.date(2026, 6, 1),
        )

        # ── Задача и Работа (WorkRecord) ──
        from apps.production.models import Task, WorkRecord, TaskStatus
        cls.task = Task.objects.create(
            company=cls.company, order=cls.order,
            worker=cls.worker, assigned_by=cls.admin,
            status=TaskStatus.IN_PROGRESS,
        )
        # Работа, ожидающая подтверждения (с незакрытым заработком)
        cls.work_record = WorkRecord.objects.create(
            company=cls.company, task=cls.task,
            worker=cls.worker, product=cls.product,
            quantity=Decimal('2'), unit='izdelie',
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION,
            labor_cost=Decimal('50000'),  # только owner / сам worker
        )
        # Подтверждённая работа того же работника (для my_earnings)
        cls.confirmed_work = WorkRecord.objects.create(
            company=cls.company, worker=cls.worker,
            product=cls.product, quantity=Decimal('3'),
            unit='izdelie',
            status=WorkRecord.WorkStatus.CONFIRMED,
            labor_cost=Decimal('75000'),
        )
        # Работа другого работника (worker не должен её видеть)
        cls.other_work = WorkRecord.objects.create(
            company=cls.company, worker=cls.other_worker,
            product=cls.product, quantity=Decimal('1'),
            unit='izdelie',
            status=WorkRecord.WorkStatus.CONFIRMED,
            labor_cost=Decimal('99999'),
        )

        # ── Расход ──
        from apps.finance.models import Expense
        cls.expense = Expense.objects.create(
            company=cls.company, category='rent',
            amount=Decimal('2000000'), date=datetime.date.today(),
            comment='Аренда за июль',
        )

        # ── Ставка труда ──
        from apps.finance.models import LaborRate
        cls.labor_rate = LaborRate.objects.create(
            company=cls.company, product=cls.product,
            operation='резка', rate_per_unit=Decimal('50000'),
            unit='izdelie',
        )

        # ── Выплата работнику ──
        from apps.finance.models import WorkerPayment
        cls.payment = WorkerPayment.objects.create(
            company=cls.company, worker=cls.worker,
            amount=Decimal('300000'), payment_date=datetime.date.today(),
            payment_type='salary',
        )

    def _api(self, user):
        api = APIClient()
        api.force_authenticate(user=user)
        return api

    def _first_item(self, user, url):
        """GET от user и возвращает первый элемент из пагинированного ответа."""
        resp = self._api(user).get(url)
        self.assertEqual(resp.status_code, 200)
        results = api_results(resp)
        self.assertGreater(len(results), 0, f'Пустой ответ от {url}')
        return results[0]

    # ═══════════════════════════════════════════════════════════
    # 1. СКЛАД СЫРЬЯ (RawMaterial)
    # ═══════════════════════════════════════════════════════════

    def test_01_admin_raw_materials_no_prices(self):
        """Admin видит склад сырья, но БЕЗ purchase_price и avg_cost_price."""
        item = self._first_item(self.admin, '/api/v1/warehouse/raw-materials/')
        self.assertIn('name', item)
        self.assertIn('quantity', item)
        self.assertNotIn('purchase_price', item,
                         'Admin НЕ должен видеть закупочную цену!')
        self.assertNotIn('avg_cost_price', item,
                         'Admin НЕ должен видеть среднюю себестоимость!')

    def test_02_worker_raw_materials_no_prices(self):
        """Worker видит склад сырья, но БЕЗ цен."""
        item = self._first_item(self.worker, '/api/v1/warehouse/raw-materials/')
        self.assertNotIn('purchase_price', item)
        self.assertNotIn('avg_cost_price', item)

    def test_03_owner_raw_materials_has_prices(self):
        """Owner видит склад сырья СО ВСЕМИ ценами."""
        item = self._first_item(self.owner, '/api/v1/warehouse/raw-materials/')
        self.assertIn('purchase_price', item,
                      'Owner должен видеть закупочную цену')
        self.assertEqual(item['purchase_price'], '50000.00')
        self.assertIn('avg_cost_price', item,
                      'Owner должен видеть среднюю себестоимость')
        self.assertEqual(item['avg_cost_price'], '48000.00')

    # ═══════════════════════════════════════════════════════════
    # 2. ГОТОВАЯ ПРОДУКЦИЯ (FinishedProduct)
    # ═══════════════════════════════════════════════════════════

    def test_04_admin_finished_products_no_prices(self):
        """Admin видит готовую продукцию, но БЕЗ cost_price и sale_price."""
        item = self._first_item(self.admin, '/api/v1/warehouse/finished-products/')
        self.assertIn('name', item)
        self.assertIn('quantity', item)
        self.assertNotIn('cost_price', item,
                         'Admin НЕ должен видеть себестоимость!')
        self.assertNotIn('sale_price', item,
                         'Admin НЕ должен видеть продажную цену!')

    def test_05_worker_finished_products_no_prices(self):
        """Worker видит готовую продукцию, но БЕЗ цен."""
        item = self._first_item(self.worker, '/api/v1/warehouse/finished-products/')
        self.assertNotIn('cost_price', item)
        self.assertNotIn('sale_price', item)

    def test_06_owner_finished_products_has_prices(self):
        """Owner видит готовую продукцию СО ВСЕМИ ценами."""
        item = self._first_item(self.owner, '/api/v1/warehouse/finished-products/')
        self.assertIn('cost_price', item,
                      'Owner должен видеть себестоимость')
        self.assertEqual(item['cost_price'], '150000.00')
        self.assertIn('sale_price', item,
                      'Owner должен видеть продажную цену')
        self.assertEqual(item['sale_price'], '300000.00')

    # ═══════════════════════════════════════════════════════════
    # 3. ДВИЖЕНИЯ СКЛАДА (StockMovement)
    # ═══════════════════════════════════════════════════════════

    def test_07_admin_stock_movements_no_price(self):
        """Admin видит историю движений, но price_per_unit скрыт."""
        resp = self._api(self.admin).get('/api/v1/warehouse/stock-movements/')
        self.assertEqual(resp.status_code, 200)
        results = api_results(resp)
        if len(results) > 0:
            self.assertNotIn('price_per_unit', results[0],
                             'Admin НЕ должен видеть price_per_unit!')

    # ═══════════════════════════════════════════════════════════
    # 4. ЗАКАЗЫ (Order)
    # ═══════════════════════════════════════════════════════════

    def test_08_admin_orders_no_amounts(self):
        """Admin видит заказы, но БЕЗ total_amount и paid_amount."""
        item = self._first_item(self.admin, '/api/v1/orders/orders/')
        self.assertIn('status', item)
        self.assertIn('payment_status', item)
        self.assertNotIn('total_amount', item,
                         'Admin НЕ должен видеть сумму заказа!')
        self.assertNotIn('paid_amount', item,
                         'Admin НЕ должен видеть оплаченную сумму!')
        # Но должен видеть информацию о нехватке материала
        self.assertIn('has_material_shortage', item)

    def test_09_worker_orders_no_amounts(self):
        """Worker видит свои заказы, но БЕЗ финансовых полей."""
        item = self._first_item(self.worker, '/api/v1/orders/orders/')
        self.assertNotIn('total_amount', item)
        self.assertNotIn('paid_amount', item)

    def test_10_owner_orders_has_amounts(self):
        """Owner видит заказы СО ВСЕМИ суммами."""
        item = self._first_item(self.owner, '/api/v1/orders/orders/')
        self.assertIn('total_amount', item,
                      'Owner должен видеть сумму заказа')
        self.assertEqual(item['total_amount'], '600000.00')
        self.assertIn('paid_amount', item,
                      'Owner должен видеть оплаченную сумму')
        self.assertEqual(item['paid_amount'], '200000.00')

    # ═══════════════════════════════════════════════════════════
    # 5. КЛИЕНТЫ (Client)
    # ═══════════════════════════════════════════════════════════

    def test_11_admin_clients_no_finance(self):
        """Admin видит клиентов, но БЕЗ финансовых полей (долг, суммы)."""
        item = self._first_item(self.admin, '/api/v1/clients/clients/')
        self.assertIn('name', item)
        self.assertIn('phone', item)
        self.assertIn('has_debt', item)        # булевый статус — можно
        self.assertIn('has_active_orders', item)
        self.assertNotIn('total_orders_amount', item,
                         'Admin НЕ должен видеть сумму заказов клиента!')
        self.assertNotIn('total_paid', item,
                         'Admin НЕ должен видеть общую оплату!')
        self.assertNotIn('debt', item,
                         'Admin НЕ должен видеть долг клиента!')
        self.assertNotIn('payments', item,
                         'Admin НЕ должен видеть историю платежей!')

    def test_12_owner_clients_has_finance(self):
        """Owner видит клиентов со ВСЕМИ финансовыми данными."""
        item = self._first_item(self.owner, '/api/v1/clients/clients/')
        self.assertIn('total_orders_amount', item,
                      'Owner должен видеть сумму заказов клиента')
        self.assertIn('total_paid', item,
                      'Owner должен видеть общую оплату')
        self.assertIn('debt', item,
                      'Owner должен видеть долг клиента')
        self.assertIn('payments', item,
                      'Owner должен видеть историю платежей')

    # ═══════════════════════════════════════════════════════════
    # 6. ПРОИЗВОДСТВО (WorkRecord / Task)
    # ═══════════════════════════════════════════════════════════

    def test_13_admin_works_no_labor_cost(self):
        """Admin видит работы, но labor_cost скрыт."""
        item = self._first_item(self.admin, '/api/v1/production/works/')
        self.assertNotIn('labor_cost', item,
                         'Admin НЕ должен видеть стоимость труда!')

    def test_14_worker_sees_own_labor_cost(self):
        """Worker видит СВОЙ labor_cost (только свой заработок)."""
        resp = self._api(self.worker).get('/api/v1/production/works/')
        self.assertEqual(resp.status_code, 200)
        results = api_results(resp)
        # Worker видит только свои работы (2 шт: awaiting + confirmed)
        self.assertEqual(len(results), 2,
                         'Worker должен видеть только свои работы')
        for work in results:
            self.assertIn('labor_cost', work,
                          'Worker должен видеть свой заработок')
            self.assertEqual(work['worker'], self.worker.id,
                             'Worker видит только свои работы')

    def test_15_worker_cannot_see_other_worker_earnings(self):
        """Worker НЕ видит работы другого работника."""
        resp = self._api(self.worker).get('/api/v1/production/works/')
        self.assertEqual(resp.status_code, 200)
        results = api_results(resp)
        for work in results:
            self.assertNotEqual(work['worker'], self.other_worker.id,
                                'Worker не должен видеть чужие работы!')

    def test_16_owner_works_has_labor_cost(self):
        """Owner видит работы СО стоимостью труда."""
        item = self._first_item(self.owner, '/api/v1/production/works/')
        self.assertIn('labor_cost', item,
                      'Owner должен видеть стоимость труда')

    def test_17_worker_my_earnings_endpoint(self):
        """Worker видит свой заработок через my_earnings (только подтверждённые)."""
        resp = self._api(self.worker).get('/api/v1/production/works/my_earnings/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('total_earned', data)
        self.assertIn('paid_out', data)
        self.assertIn('remaining', data)
        # Считаются ТОЛЬКО подтверждённые работы: confirmed_work = 75000
        self.assertEqual(data['total_earned'], 75000.0,
                         'Worker должен видеть сумму подтверждённых работ')

    # ═══════════════════════════════════════════════════════════
    # 7. ФИНАНСЫ — ДОСТУП ТОЛЬКО OWNER
    # ═══════════════════════════════════════════════════════════

    OWNER_ONLY_ENDPOINTS = [
        '/api/v1/finance/expenses/',
        '/api/v1/finance/labor-rates/',
        '/api/v1/finance/worker-payments/',
        '/api/v1/reports/analytics/owner/',
        '/api/v1/reports/export/finance/',
    ]

    def test_18_admin_blocked_from_finance(self):
        """Admin получает 403 на все финансовые эндпоинты."""
        for url in self.OWNER_ONLY_ENDPOINTS:
            with self.subTest(url=url):
                resp = self._api(self.admin).get(url)
                self.assertEqual(resp.status_code, 403,
                                 f'Admin должен получать 403 на {url}')

    def test_19_worker_blocked_from_finance(self):
        """Worker получает 403 на все финансовые эндпоинты."""
        for url in self.OWNER_ONLY_ENDPOINTS:
            with self.subTest(url=url):
                resp = self._api(self.worker).get(url)
                self.assertEqual(resp.status_code, 403,
                                 f'Worker должен получать 403 на {url}')

    def test_20_owner_can_access_finance(self):
        """Owner получает 200 на все финансовые эндпоинты."""
        for url in self.OWNER_ONLY_ENDPOINTS:
            with self.subTest(url=url):
                resp = self._api(self.owner).get(url)
                self.assertEqual(resp.status_code, 200,
                                 f'Owner должен получать 200 на {url}')

    # ═══════════════════════════════════════════════════════════
    # 8. АДМИНИСТРАТОРСКАЯ АНАЛИТИКА (без денег)
    # ═══════════════════════════════════════════════════════════

    def test_21_admin_analytics_no_money_fields(self):
        """Admin получает аналитику, но без денежных полей."""
        resp = self._api(self.admin).get('/api/v1/reports/analytics/admin/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(deep_find(resp.json(), OWNER_ONLY_FIELDS), [],
                         'Admin аналитика не должна содержать деньги')

    def test_22_owner_analytics_accessible(self):
        """Owner получает полную аналитику (200 OK)."""
        resp = self._api(self.owner).get('/api/v1/reports/analytics/owner/')
        self.assertEqual(resp.status_code, 200)

    # ═══════════════════════════════════════════════════════════
    # 9. РАБОТНИК — ОГРАНИЧЕННЫЙ ДОСТУП
    # ═══════════════════════════════════════════════════════════

    def test_23_worker_cannot_access_clients(self):
        """Worker не имеет доступа к клиентам (403)."""
        resp = self._api(self.worker).get('/api/v1/clients/clients/')
        self.assertEqual(resp.status_code, 403)

    def test_24_worker_cannot_post_expense(self):
        """Worker не может создать расход."""
        resp = self._api(self.worker).post(
            '/api/v1/finance/expenses/',
            {'category': 'rent', 'amount': '1000', 'date': '2026-07-24'},
            format='json'
        )
        self.assertEqual(resp.status_code, 403)

    # ═══════════════════════════════════════════════════════════
    # 10. OWNER МОЖЕТ СОЗДАВАТЬ ФИНАНСОВЫЕ ДАННЫЕ
    # ═══════════════════════════════════════════════════════════

    def test_25_owner_can_create_expense(self):
        """Owner может создавать расходы."""
        resp = self._api(self.owner).post(
            '/api/v1/finance/expenses/',
            {'category': 'transport', 'amount': '500000',
             'date': '2026-07-24', 'comment': 'Доставка'},
            format='json'
        )
        self.assertEqual(resp.status_code, 201)

    # ═══════════════════════════════════════════════════════════
    # 11. ПЛАТЕЖИ (Payment) — ТОЛЬКО OWNER
    # ═══════════════════════════════════════════════════════════

    def test_26_admin_blocked_from_payments(self):
        """Admin получает 403 на payments (только owner)."""
        resp = self._api(self.admin).get('/api/v1/clients/payments/')
        self.assertEqual(resp.status_code, 403)

    # ═══════════════════════════════════════════════════════════
    # 12. ГЛОБАЛЬНАЯ ПРОВЕРКА: НИ ОДИН ФИНАНСОВЫЙ КЛЮЧ НЕ УТЕКАЕТ
    # ═══════════════════════════════════════════════════════════

    ADMIN_ENDPOINTS = [
        '/api/v1/warehouse/raw-materials/',
        '/api/v1/warehouse/finished-products/',
        '/api/v1/warehouse/stock-movements/',
        '/api/v1/warehouse/recipes/',
        '/api/v1/orders/orders/',
        '/api/v1/clients/clients/',
        '/api/v1/production/tasks/',
        '/api/v1/production/works/',
        '/api/v1/reports/analytics/admin/',
    ]

    def test_27_admin_zero_money_fields_across_all_endpoints(self):
        """Глобальная проверка: Admin не получает НИ ОДНОГО финансового поля."""
        api = self._api(self.admin)
        for url in self.ADMIN_ENDPOINTS:
            with self.subTest(url=url):
                resp = api.get(url)
                self.assertEqual(resp.status_code, 200)
                leaked = deep_find(resp.json(), OWNER_ONLY_FIELDS)
                self.assertEqual(leaked, [],
                                 f'Утечка финансовых полей в {url}: {leaked}')

    WORKER_ENDPOINTS = [
        '/api/v1/warehouse/raw-materials/',
        '/api/v1/warehouse/finished-products/',
        '/api/v1/orders/orders/',
        '/api/v1/production/tasks/',
        '/api/v1/production/works/',
    ]

    def test_28_worker_zero_money_fields_across_own_endpoints(self):
        """Глобальная проверка: Worker не получает чужих финансовых полей."""
        api = self._api(self.worker)
        for url in self.WORKER_ENDPOINTS:
            with self.subTest(url=url):
                resp = api.get(url)
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                # Worker может видеть labor_cost ТОЛЬКО в своих работах
                leaked = deep_find(data, OWNER_ONLY_FIELDS - {'labor_cost'})
                self.assertEqual(leaked, [],
                                 f'Утечка финансовых полей (кроме labor_cost) в {url}: {leaked}')
