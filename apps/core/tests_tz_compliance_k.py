"""
Аудит соответствия ТЗ: сквозные проверки того, что система обещает.

Это не юнит-тесты отдельных функций, а проверки требований целиком, каждая
из которых бьёт по реальному API от лица конкретной роли:

* финансовая изоляция — администратор и работник не получают денег НИГДЕ,
  включая списки, карточки, сводки, аналитику, отчёты и экспорт;
* изоляция компаний — данные чужого tenant недоступны даже по прямому id;
* производство — только через подтверждение, атомарно, с историей склада;
* переспрос (overbooking) и нехватка считаются корректно;
* начисление работнику = количество × ставка;
* формулы владельца (валовая/чистая прибыль, касса) сходятся.

Подход «сканируем ответ на запрещённые ключи» выбран намеренно: точечная
проверка полей пропускает утечку через вложенный сериализатор, аннотацию или
новый эндпоинт, а сканирование ловит их автоматически.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client, Payment
from apps.companies.models import Company
from apps.finance.models import Expense, ExpenseCategory, LaborRate, WorkerPayment
from apps.orders.models import Order
from apps.production.models import Task, TaskStatus, WorkRecord
from apps.warehouse.models import (
    FinishedProduct, RawMaterial, Recipe, RecipeItem, StockMovement,
)

# Ключи, которых в ответе НЕ должно быть у ролей без доступа к финансам.
# Составлены по ТЗ: «прибыль, выручка, себестоимость, закупочные цены,
# расходы, касса, зарплаты, долги в деньгах, финансовая история».
FORBIDDEN_MONEY_KEYS = {
    'purchase_price', 'avg_cost_price', 'cost_price', 'sale_price', 'price',
    'price_per_unit', 'total_amount', 'paid_amount', 'debt', 'total_debt',
    'revenue', 'profit', 'gross_profit', 'net_profit', 'cash',
    'labor_cost', 'labor_rate', 'rate_per_unit', 'amount', 'salary',
    'total_value', 'expenses_total', 'owner_withdrawal', 'taxes',
    'client_debts', 'worker_debts', 'worker_payments', 'cost_of_goods',
}


def collect_money_keys(payload, path='', found=None):
    """Рекурсивно ищет запрещённые денежные ключи в ответе API."""
    if found is None:
        found = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            here = f'{path}.{key}' if path else key
            if key in FORBIDDEN_MONEY_KEYS and value not in (None, '', [], {}):
                found.append(here)
            collect_money_keys(value, here, found)
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            collect_money_keys(item, f'{path}[{index}]', found)
    return found


class TzScenarioMixin:
    """Общая компания с деньгами, складом, заказом и работой."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='Granit')
        cls.owner = User.objects.create_user(
            username='tz_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='tz_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='tz_worker', password='pw', role=User.Role.WORKER,
            company=cls.company, full_name='Али',
        )
        cls.other_worker = User.objects.create_user(
            username='tz_worker2', password='pw', role=User.Role.WORKER,
            company=cls.company, full_name='Вали',
        )

        cls.material = RawMaterial.objects.create(
            company=cls.company, name='Гранит', unit='m2',
            quantity=Decimal('100'), min_stock=Decimal('10'),
            purchase_price=Decimal('50.00'), avg_cost_price=Decimal('50.00'),
        )
        cls.product = FinishedProduct.objects.create(
            company=cls.company, name='Столешница', unit='sht',
            quantity=Decimal('5'), cost_price=Decimal('200.00'),
            sale_price=Decimal('500.00'),
        )
        cls.recipe = Recipe.objects.create(
            company=cls.company, product=cls.product, name='Столешница 2000x600',
        )
        RecipeItem.objects.create(
            recipe=cls.recipe, material=cls.material,
            quantity_required=Decimal('2'), unit='m2',
        )
        cls.client_obj = Client.objects.create(
            company=cls.company, name='Акбаров', phone='+998901112233',
        )
        cls.order = Order.objects.create(
            company=cls.company, client=cls.client_obj, product=cls.product,
            quantity=Decimal('2'), unit='sht', total_amount=Decimal('1000.00'),
            deadline=timezone.now() + timezone.timedelta(days=3),
        )
        Payment.objects.create(
            company=cls.company, client=cls.client_obj, order=cls.order,
            amount=Decimal('400.00'), payment_date=timezone.now(),
        )
        Expense.objects.create(
            company=cls.company, category=ExpenseCategory.RENT,
            amount=Decimal('100.00'), created_by=cls.owner,
            date=timezone.now().date(),
        )
        # Ставка труда привязана к паре «товар + операция» (см. модель).
        cls.rate = LaborRate.objects.create(
            company=cls.company, product=cls.product,
            operation=LaborRate.OperationType.POLISHING,
            unit='m2', rate_per_unit=Decimal('150.00'),
        )

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api


class FinancialIsolationTests(TzScenarioMixin, TestCase):
    """Администратор и работник не получают финансовых данных нигде."""

    # Эндпоинты, которые роль ИМЕЕТ право открывать; финансов в них быть не должно.
    READ_ENDPOINTS = [
        '/api/v1/warehouse/raw-materials/',
        '/api/v1/warehouse/raw-materials/summary/',
        '/api/v1/warehouse/finished-products/',
        '/api/v1/warehouse/stock-movements/',
        '/api/v1/warehouse/warehouses/',
        '/api/v1/warehouse/cells/',
        '/api/v1/warehouse/recipes/',
        '/api/v1/production/tasks/',
        '/api/v1/production/works/',
        '/api/v1/messaging/notifications/',
        '/api/v1/messaging/conversations/',
        # Каталог операций администратору нужен (он оформляет работы),
        # но ставки в сомах в ответе быть не должно.
        '/api/v1/finance/labor-rates/',
    ]

    def test_owner_sees_finance(self):
        """Контрольный случай: у владельца деньги ЕСТЬ (иначе тест ниже бессмыслен)."""
        api = self.api_as(self.owner)
        materials = api.get('/api/v1/warehouse/raw-materials/').data
        rows = materials['results'] if 'results' in materials else materials
        self.assertIn('purchase_price', rows[0])

        analytics = api.get('/api/v1/reports/analytics/owner/?period=month')
        self.assertEqual(analytics.status_code, 200)
        for key in ('revenue', 'net_profit', 'cash', 'client_debts'):
            self.assertIn(key, analytics.data)

    def test_admin_gets_no_money_from_readable_endpoints(self):
        api = self.api_as(self.admin)
        leaks = []
        for endpoint in self.READ_ENDPOINTS:
            response = api.get(endpoint)
            self.assertIn(response.status_code, (200, 403), f'{endpoint} -> {response.status_code}')
            if response.status_code == 200:
                leaks += [f'{endpoint}: {key}' for key in collect_money_keys(response.data)]
        self.assertFalse(leaks, 'администратор получил денежные поля:\n  ' + '\n  '.join(leaks))

    def test_worker_gets_no_money_from_readable_endpoints(self):
        api = self.api_as(self.worker)
        leaks = []
        # Ставка своей операции работнику видна намеренно: по ТЗ он видит
        # собственный заработок, а «Начислено = количество × ставка» без
        # ставки посчитать нельзя. Чужих финансов это не раскрывает.
        endpoints = [e for e in self.READ_ENDPOINTS if 'labor-rates' not in e]
        for endpoint in endpoints:
            response = api.get(endpoint)
            if response.status_code == 200:
                leaks += [f'{endpoint}: {key}' for key in collect_money_keys(response.data)]
        self.assertFalse(leaks, 'работник получил денежные поля:\n  ' + '\n  '.join(leaks))

    def test_admin_denied_on_finance_endpoints(self):
        """Финансовые разделы администратору закрыты полностью, а не «спрятаны»."""
        api = self.api_as(self.admin)
        for endpoint in (
            '/api/v1/finance/expenses/',
            '/api/v1/finance/worker-payments/',
            '/api/v1/finance/worker-payments/settlements/',
            '/api/v1/reports/analytics/owner/',
            '/api/v1/reports/analytics/revenue-timeline/',
            '/api/v1/reports/export/finance/',
            '/api/v1/clients/clients/debt_summary/',
            '/api/v1/clients/payments/',
        ):
            response = api.get(endpoint)
            self.assertEqual(response.status_code, 403, f'{endpoint} -> {response.status_code}')

    def test_worker_denied_on_finance_endpoints(self):
        api = self.api_as(self.worker)
        for endpoint in (
            '/api/v1/finance/expenses/',
            '/api/v1/finance/worker-payments/',
            '/api/v1/reports/analytics/owner/',
            '/api/v1/reports/export/finance/',
            '/api/v1/clients/clients/',
            '/api/v1/clients/payments/',
        ):
            response = api.get(endpoint)
            self.assertEqual(response.status_code, 403, f'{endpoint} -> {response.status_code}')

    def test_admin_client_card_has_no_money(self):
        """Клиент для администратора: имя, телефон, адрес, статус — без сумм."""
        api = self.api_as(self.admin)
        response = api.get(f'/api/v1/clients/clients/{self.client_obj.id}/')
        if response.status_code == 200:
            self.assertFalse(
                collect_money_keys(response.data),
                f'карточка клиента отдала админу деньги: {collect_money_keys(response.data)}',
            )

    def test_admin_orders_have_no_amounts(self):
        api = self.api_as(self.admin)
        response = api.get('/api/v1/orders/orders/')
        self.assertEqual(response.status_code, 200)
        rows = response.data['results'] if 'results' in response.data else response.data
        self.assertTrue(rows)
        leaks = collect_money_keys(rows)
        self.assertFalse(leaks, f'заказы отдали админу деньги: {leaks}')

    def test_admin_exports_have_no_money(self):
        """Экспорт тоже подчиняется правам: в CSV админа нет ни одной суммы."""
        api = self.api_as(self.admin)
        for endpoint in ('/api/v1/reports/export/stock/?format=csv',
                         '/api/v1/reports/export/orders/?format=csv',
                         '/api/v1/reports/export/work/?format=csv'):
            response = api.get(endpoint)
            self.assertEqual(response.status_code, 200, endpoint)
            body = response.content.decode('utf-8')
            for money in ('50.00', '200.00', '500.00', '1000.00', '400.00'):
                self.assertNotIn(money, body, f'{endpoint} содержит сумму {money}')

    def test_admin_analytics_has_no_money(self):
        api = self.api_as(self.admin)
        response = api.get('/api/v1/reports/analytics/admin/')
        self.assertEqual(response.status_code, 200)
        leaks = collect_money_keys(response.data)
        self.assertFalse(leaks, f'операционная аналитика отдала деньги: {leaks}')

    def test_worker_sees_only_own_earnings(self):
        """Работник видит свой заработок и не видит чужой."""
        WorkRecord.objects.create(
            company=self.company, worker=self.worker, product=self.product,
            quantity=Decimal('2'), unit='m2', status=WorkRecord.WorkStatus.CONFIRMED,
            labor_cost=Decimal('300.00'),
        )
        WorkRecord.objects.create(
            company=self.company, worker=self.other_worker, product=self.product,
            quantity=Decimal('5'), unit='m2', status=WorkRecord.WorkStatus.CONFIRMED,
            labor_cost=Decimal('750.00'),
        )
        api = self.api_as(self.worker)
        earnings = api.get('/api/v1/production/works/my_earnings/')
        self.assertEqual(earnings.status_code, 200)
        body = str(earnings.data)
        self.assertNotIn('750', body, 'работник увидел чужой заработок')

        works = api.get('/api/v1/production/works/')
        rows = works.data['results'] if 'results' in works.data else works.data
        self.assertTrue(all(row['worker'] == self.worker.id for row in rows),
                        'работник видит чужие работы')


class TenantIsolationTests(TzScenarioMixin, TestCase):
    """Компания A не достаёт данные компании B — ни списком, ни по прямому id."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other_company = Company.objects.create(name='OtherCo')
        cls.other_owner = User.objects.create_user(
            username='other_owner', password='pw', role=User.Role.OWNER,
            company=cls.other_company,
        )
        cls.other_material = RawMaterial.objects.create(
            company=cls.other_company, name='Чужой гранит', unit='m2',
            quantity=Decimal('10'),
        )
        cls.other_client = Client.objects.create(
            company=cls.other_company, name='Чужой клиент',
        )
        cls.other_order = Order.objects.create(
            company=cls.other_company, client=cls.other_client,
            custom_product_name='Чужой заказ', quantity=Decimal('1'), unit='sht',
            total_amount=Decimal('999.00'),
            deadline=timezone.now() + timezone.timedelta(days=1),
        )

    def test_lists_are_scoped(self):
        api = self.api_as(self.owner)
        materials = api.get('/api/v1/warehouse/raw-materials/').data
        rows = materials['results'] if 'results' in materials else materials
        self.assertNotIn('Чужой гранит', [row['name'] for row in rows])

    def test_direct_id_access_denied(self):
        api = self.api_as(self.owner)
        for endpoint in (
            f'/api/v1/warehouse/raw-materials/{self.other_material.id}/',
            f'/api/v1/clients/clients/{self.other_client.id}/',
            f'/api/v1/orders/orders/{self.other_order.id}/',
        ):
            response = api.get(endpoint)
            self.assertIn(response.status_code, (403, 404), f'{endpoint} -> {response.status_code}')

    def test_cannot_write_into_foreign_tenant(self):
        """Заказ на чужого клиента не создаётся (mass assignment по id)."""
        api = self.api_as(self.owner)
        response = api.post('/api/v1/orders/orders/', {
            'client': self.other_client.id,
            'custom_product_name': 'Подмена',
            'quantity': '1', 'unit': 'sht', 'total_amount': '10.00',
        }, format='json')
        self.assertIn(response.status_code, (400, 403), response.data)

    def test_company_field_cannot_be_forged(self):
        """Явно переданная чужая компания игнорируется, а не принимается."""
        api = self.api_as(self.owner)
        response = api.post('/api/v1/warehouse/raw-materials/', {
            'name': 'Подмена', 'unit': 'm2', 'company': self.other_company.id,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        created = RawMaterial.objects.get(pk=response.data['id'])
        self.assertEqual(created.company_id, self.company.id)


class ProductionIntegrityTests(TzScenarioMixin, TestCase):
    """Производство только через подтверждение: атомарно и с историей."""

    def _submit_work(self, quantity='1'):
        api = self.api_as(self.worker)
        task = Task.objects.create(
            company=self.company, order=self.order, worker=self.worker,
            assigned_by=self.owner, status=TaskStatus.ACCEPTED, title='Столешница',
        )
        response = api.post('/api/v1/production/works/', {
            'task': task.id, 'product': self.product.id,
            'quantity': quantity, 'unit': 'sht',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return WorkRecord.objects.get(pk=response.data['id'])

    def test_submitted_work_does_not_touch_stock(self):
        material_before = self.material.quantity
        product_before = self.product.quantity
        work = self._submit_work()
        self.material.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.material.quantity, material_before)
        self.assertEqual(self.product.quantity, product_before)
        self.assertEqual(work.status, WorkRecord.WorkStatus.AWAITING_CONFIRMATION)

    def test_confirmation_writes_off_materials_and_adds_product(self):
        work = self._submit_work(quantity='2')
        api = self.api_as(self.owner)
        response = api.post(f'/api/v1/production/works/{work.id}/confirm/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)

        self.material.refresh_from_db()
        self.product.refresh_from_db()
        # Рецепт: 2 м² гранита на изделие, изготовлено 2 штуки -> списано 4.
        self.assertEqual(self.material.quantity, Decimal('96.000'))
        self.assertEqual(self.product.quantity, Decimal('7.000'))

        # История склада обязана появиться на обе стороны операции.
        self.assertTrue(StockMovement.objects.filter(
            material=self.material,
            movement_type=StockMovement.MovementType.PRODUCTION_OUT,
        ).exists())
        self.assertTrue(StockMovement.objects.filter(
            product=self.product,
            movement_type=StockMovement.MovementType.PRODUCTION_IN,
        ).exists())

    def test_rejected_work_changes_nothing(self):
        work = self._submit_work(quantity='2')
        material_before = self.material.quantity
        product_before = self.product.quantity
        movements_before = StockMovement.objects.count()

        api = self.api_as(self.owner)
        response = api.post(
            f'/api/v1/production/works/{work.id}/reject/',
            {'reason': 'Брак кромки'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

        self.material.refresh_from_db()
        self.product.refresh_from_db()
        work.refresh_from_db()
        self.assertEqual(self.material.quantity, material_before)
        self.assertEqual(self.product.quantity, product_before)
        self.assertEqual(StockMovement.objects.count(), movements_before)
        self.assertEqual(work.status, WorkRecord.WorkStatus.REJECTED)
        self.assertEqual(work.labor_cost, Decimal('0.00'))

    def test_confirmation_is_atomic_when_material_missing(self):
        """
        Не хватило сырья — не должно остаться ни готовой продукции, ни начисления.

        Частичное применение здесь опаснее отказа: товар появился бы из воздуха.
        """
        self.material.quantity = Decimal('1')
        self.material.save(update_fields=['quantity'])
        work = self._submit_work(quantity='2')
        product_before = self.product.quantity

        api = self.api_as(self.owner)
        response = api.post(f'/api/v1/production/works/{work.id}/confirm/', {}, format='json')
        self.assertEqual(response.status_code, 400, response.data)

        self.material.refresh_from_db()
        self.product.refresh_from_db()
        work.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('1.000'))
        self.assertEqual(self.product.quantity, product_before)
        self.assertEqual(work.status, WorkRecord.WorkStatus.AWAITING_CONFIRMATION)
        self.assertEqual(work.labor_cost, Decimal('0.00'))

    def test_worker_cannot_confirm_own_work(self):
        work = self._submit_work()
        api = self.api_as(self.worker)
        response = api.post(f'/api/v1/production/works/{work.id}/confirm/', {}, format='json')
        self.assertEqual(response.status_code, 403)


class OverbookingAndShortageTests(TzScenarioMixin, TestCase):
    """Спрос может превышать склад: это не ошибка, а нехватка."""

    def test_required_may_exceed_quantity(self):
        self.product.quantity = Decimal('1')
        self.product.required_for_orders = Decimal('5')
        self.product.save(update_fields=['quantity', 'required_for_orders'])
        self.product.refresh_from_db()
        self.assertEqual(self.product.shortage_quantity, Decimal('4'))

    def test_material_shortage_formula(self):
        self.material.quantity = Decimal('3')
        self.material.required_for_orders = Decimal('10')
        self.material.save(update_fields=['quantity', 'required_for_orders'])
        self.material.refresh_from_db()
        self.assertEqual(self.material.shortage_quantity, Decimal('7'))
        self.assertTrue(self.material.is_low_stock)

    def test_no_shortage_when_stock_is_enough(self):
        self.material.quantity = Decimal('100')
        self.material.required_for_orders = Decimal('10')
        self.material.save(update_fields=['quantity', 'required_for_orders'])
        self.material.refresh_from_db()
        self.assertEqual(self.material.shortage_quantity, Decimal('0'))

    def test_order_marks_material_shortage(self):
        """Заказ, которому не хватает сырья, помечается для красной карточки."""
        self.material.quantity = Decimal('0')
        self.material.save(update_fields=['quantity'])
        api = self.api_as(self.owner)
        response = api.post('/api/v1/orders/orders/', {
            'client': self.client_obj.id, 'product': self.product.id,
            'quantity': '10', 'unit': 'sht', 'total_amount': '5000.00',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        detail = api.get(f"/api/v1/orders/orders/{response.data['id']}/").data
        self.assertTrue(detail['has_material_shortage'] or detail['shortage_quantity'])


class PayrollAndFinanceFormulaTests(TzScenarioMixin, TestCase):
    """Начислено = количество × ставка; формулы владельца сходятся."""

    def test_labor_accrual_uses_rate(self):
        task = Task.objects.create(
            company=self.company, order=self.order, worker=self.worker,
            assigned_by=self.owner, status=TaskStatus.ACCEPTED, title='Полировка',
        )
        api = self.api_as(self.worker)
        response = api.post('/api/v1/production/works/', {
            'task': task.id, 'product': self.product.id,
            'quantity': '3', 'unit': 'm2', 'operation': 'polishing',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        work = WorkRecord.objects.get(pk=response.data['id'])

        self.api_as(self.owner).post(
            f'/api/v1/production/works/{work.id}/confirm/', {}, format='json',
        )
        work.refresh_from_db()
        # 3 м² × 150 сом = 450 сом
        self.assertEqual(work.labor_cost, Decimal('450.00'))

    def test_owner_analytics_formulas(self):
        """
        Проверяем арифметику отчёта на подготовленных цифрах:
            валовая прибыль = выручка − себестоимость,
            чистая прибыль  = выручка − себестоимость − расходы − выплаты,
            касса           = оплаты − расходы − выплаты − вывод владельца.
        """
        WorkerPayment.objects.create(
            company=self.company, worker=self.worker, amount=Decimal('200.00'),
            payment_date=timezone.now().date(),
        )
        api = self.api_as(self.owner)
        data = api.get('/api/v1/reports/analytics/owner/?period=month').data

        revenue = Decimal(str(data['revenue']))
        cogs = Decimal(str(data['cost_of_goods']))
        expenses = Decimal(str(data['expenses_total']))
        payouts = Decimal(str(data['worker_payments']))
        withdrawal = Decimal(str(data['owner_withdrawal']))

        self.assertEqual(Decimal(str(data['gross_profit'])), revenue - cogs)
        self.assertEqual(
            Decimal(str(data['net_profit'])),
            revenue - cogs - expenses - payouts,
        )
        self.assertEqual(
            Decimal(str(data['cash'])),
            revenue - expenses - payouts - withdrawal,
        )

    def test_money_is_decimal_not_float(self):
        """Деньги считаются Decimal: float дал бы 0.1+0.2 != 0.3."""
        api = self.api_as(self.owner)
        data = api.get('/api/v1/reports/analytics/owner/?period=month').data
        for key in ('revenue', 'net_profit', 'cash'):
            value = data[key]
            self.assertNotIsInstance(value, float, f'{key} пришёл float')


class AuditAndSoftDeleteTests(TzScenarioMixin, TestCase):
    """Важные записи архивируются, а не удаляются; действия попадают в журнал."""

    def test_material_delete_is_archive(self):
        api = self.api_as(self.owner)
        response = api.delete(f'/api/v1/warehouse/raw-materials/{self.material.id}/')
        self.assertIn(response.status_code, (200, 204))
        self.material.refresh_from_db()  # запись на месте
        self.assertTrue(self.material.is_archived)

    def test_client_delete_is_archive(self):
        api = self.api_as(self.owner)
        response = api.delete(f'/api/v1/clients/clients/{self.client_obj.id}/')
        self.assertIn(response.status_code, (200, 204, 400, 403))
        self.assertTrue(Client.objects.filter(pk=self.client_obj.pk).exists())

    def test_audit_log_written_on_create(self):
        from apps.audit.models import AuditLog

        api = self.api_as(self.owner)
        api.post('/api/v1/warehouse/raw-materials/', {
            'name': 'Мрамор', 'unit': 'm2',
        }, format='json')
        self.assertTrue(
            AuditLog.objects.filter(action=AuditLog.Action.CREATE).exists(),
            'создание материала не попало в журнал аудита',
        )

    def test_audit_log_not_readable_by_worker(self):
        api = self.api_as(self.worker)
        response = api.get('/api/v1/audit/logs/')
        self.assertEqual(response.status_code, 403)


class QuarterlyReportRoleTests(TzScenarioMixin, TestCase):
    """Квартальный отчёт: владельцу — финансовый, администратору — операционный."""

    URL = '/api/v1/reports/analytics/quarterly/'

    def test_owner_gets_financial_quarter(self):
        api = self.api_as(self.owner)
        today = timezone.localdate()
        response = api.get(self.URL, {'year': today.year, 'quarter': (today.month - 1) // 3 + 1})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['kind'], 'financial')
        for key in ('total_revenue', 'total_net_profit', 'total_expenses'):
            self.assertIn(key, response.data)

    def test_admin_gets_operational_quarter_without_money(self):
        api = self.api_as(self.admin)
        today = timezone.localdate()
        response = api.get(self.URL, {'year': today.year, 'quarter': (today.month - 1) // 3 + 1})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['kind'], 'operational')
        self.assertIn('orders_total', response.data)
        leaks = collect_money_keys(response.data)
        self.assertFalse(leaks, f'операционный квартал отдал деньги: {leaks}')
        for money_key in ('total_revenue', 'total_net_profit', 'total_cogs'):
            self.assertNotIn(money_key, response.data)

    def test_worker_denied(self):
        response = self.api_as(self.worker).get(self.URL)
        self.assertEqual(response.status_code, 403)

    def test_invalid_quarter_is_validation_error_not_500(self):
        response = self.api_as(self.owner).get(self.URL, {'quarter': 9})
        self.assertEqual(response.status_code, 400)


class ClientArchiveRuleTests(TzScenarioMixin, TestCase):
    """Архив клиента: только когда заказ завершён, выдан и долг закрыт."""

    def test_client_with_debt_not_archived(self):
        api = self.api_as(self.owner)
        self.client_obj.debt = Decimal('600.00')
        self.client_obj.save(update_fields=['debt'])
        response = api.post(f'/api/v1/clients/clients/{self.client_obj.id}/archive/')
        self.assertEqual(response.status_code, 400, response.data)
        self.client_obj.refresh_from_db()
        self.assertFalse(self.client_obj.is_archived)

    def test_client_with_unfinished_order_not_archived(self):
        api = self.api_as(self.owner)
        self.client_obj.debt = Decimal('0')
        self.client_obj.save(update_fields=['debt'])
        # Заказ из setUpTestData ещё в работе.
        response = api.post(f'/api/v1/clients/clients/{self.client_obj.id}/archive/')
        self.assertEqual(response.status_code, 400, response.data)
        self.client_obj.refresh_from_db()
        self.assertFalse(self.client_obj.is_archived)

    def test_client_archived_when_everything_closed(self):
        api = self.api_as(self.owner)
        self.client_obj.debt = Decimal('0')
        self.client_obj.save(update_fields=['debt'])
        self.order.status = Order.Status.DELIVERED
        self.order.save(update_fields=['status'])

        response = api.post(f'/api/v1/clients/clients/{self.client_obj.id}/archive/')
        self.assertEqual(response.status_code, 200, response.data)
        self.client_obj.refresh_from_db()
        self.assertTrue(self.client_obj.is_archived)
        self.assertIsNotNone(self.client_obj.archived_at)


class IdempotencyAndRaceTests(TzScenarioMixin, TestCase):
    """
    Повтор операции не должен применяться дважды.

    Двойной клик, ретрай мобильной сети или повторно отправленная форма — самый
    частый источник «двойного списания»: склад уезжает, а работнику начисляют
    дважды.
    """

    def _confirmed_work(self):
        api = self.api_as(self.worker)
        task = Task.objects.create(
            company=self.company, order=self.order, worker=self.worker,
            assigned_by=self.owner, status=TaskStatus.ACCEPTED, title='Столешница',
        )
        response = api.post('/api/v1/production/works/', {
            'task': task.id, 'product': self.product.id,
            'quantity': '1', 'unit': 'sht',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return WorkRecord.objects.get(pk=response.data['id'])

    def test_double_confirm_applies_once(self):
        work = self._confirmed_work()
        api = self.api_as(self.owner)

        first = api.post(f'/api/v1/production/works/{work.id}/confirm/', {}, format='json')
        self.assertEqual(first.status_code, 200, first.data)
        self.material.refresh_from_db()
        self.product.refresh_from_db()
        material_after_first = self.material.quantity
        product_after_first = self.product.quantity

        second = api.post(f'/api/v1/production/works/{work.id}/confirm/', {}, format='json')
        self.assertEqual(second.status_code, 400, 'повторное подтверждение должно отклоняться')

        self.material.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.material.quantity, material_after_first)
        self.assertEqual(self.product.quantity, product_after_first)

    def test_confirmed_work_cannot_be_rejected_afterwards(self):
        work = self._confirmed_work()
        api = self.api_as(self.owner)
        api.post(f'/api/v1/production/works/{work.id}/confirm/', {}, format='json')
        response = api.post(
            f'/api/v1/production/works/{work.id}/reject/', {'reason': 'передумал'}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_double_delivery_does_not_double_write_off(self):
        api = self.api_as(self.owner)
        self.product.quantity = Decimal('10')
        self.product.save(update_fields=['quantity'])

        first = api.post(f'/api/v1/orders/orders/{self.order.id}/deliver/', {}, format='json')
        self.product.refresh_from_db()
        after_first = self.product.quantity

        second = api.post(f'/api/v1/orders/orders/{self.order.id}/deliver/', {}, format='json')
        self.product.refresh_from_db()
        self.assertIn(first.status_code, (200, 400))
        if first.status_code == 200:
            self.assertEqual(second.status_code, 400, 'повторная выдача должна отклоняться')
        self.assertEqual(self.product.quantity, after_first)

    def test_overpayment_rejected(self):
        """Оплата больше долга — ошибка валидации, а не «отрицательный долг»."""
        api = self.api_as(self.owner)
        response = api.post('/api/v1/clients/payments/', {
            'client': self.client_obj.id, 'order': self.order.id,
            'amount': '100000.00',
        }, format='json')
        self.assertEqual(response.status_code, 400, response.data)

    def test_negative_quantities_rejected(self):
        """Отрицательные количества — 400, а не 500 и не порча остатка."""
        api = self.api_as(self.owner)
        for payload in (
            {'quantity': '-5'},
            {'quantity': '0'},
        ):
            response = api.post(
                f'/api/v1/warehouse/raw-materials/{self.material.id}/incoming/',
                payload, format='json',
            )
            self.assertEqual(response.status_code, 400, response.data)


class LanguageAndLocaleTests(TzScenarioMixin, TestCase):
    """Язык хранится на сервере и переживает выход; локали содержат оба языка."""

    def test_language_persisted_for_user(self):
        api = self.api_as(self.owner)
        response = api.post('/api/v1/accounts/me/language/', {'language': 'ru'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.language, 'ru')

        # Повторный вход отдаёт сохранённый язык — переключение не теряется.
        fresh = self.api_as(self.owner).get('/api/v1/accounts/me/')
        self.assertEqual(fresh.data['language'], 'ru')

    def test_unknown_language_rejected(self):
        api = self.api_as(self.owner)
        response = api.post('/api/v1/accounts/me/language/', {'language': 'fr'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_locale_endpoint_serves_both_required_languages(self):
        api = self.api_as(self.owner)
        for lang in ('uz_cyrl', 'ru'):
            response = api.get(f'/api/v1/core/locale/{lang}/')
            self.assertEqual(response.status_code, 200)
            self.assertIn('common', response.json())

    def test_russian_falls_back_to_uzbek_for_missing_key(self):
        """Пропуск в ru.json не должен превращаться в пустоту — есть fallback."""
        from core.utils import get_locale

        ru = get_locale('ru')
        uz = get_locale('uz_cyrl')
        # get_locale сливает ru поверх uz: набор ключей совпадает.
        self.assertEqual(set(uz.keys()) - set(ru.keys()), set())


class ChatRoutingTests(TzScenarioMixin, TestCase):
    """Маршрутизация чата по ролям (ТЗ: кто с кем может переписываться)."""

    def test_owner_sees_all_employees(self):
        api = self.api_as(self.owner)
        response = api.get('/api/v1/messaging/employees/')
        self.assertEqual(response.status_code, 200)
        rows = response.data['results'] if 'results' in response.data else response.data
        usernames = {row['username'] for row in rows}
        self.assertIn('tz_admin', usernames)
        self.assertIn('tz_worker', usernames)

    def test_worker_sees_staff_contacts(self):
        api = self.api_as(self.worker)
        response = api.get('/api/v1/messaging/employees/')
        self.assertEqual(response.status_code, 200)
        rows = response.data['results'] if 'results' in response.data else response.data
        usernames = {row['username'] for row in rows}
        self.assertIn('tz_admin', usernames)
        self.assertIn('tz_owner', usernames)

    def test_contacts_are_company_scoped(self):
        other_company = Company.objects.create(name='OtherCo2')
        User.objects.create_user(
            username='foreign_admin', password='pw', role=User.Role.ADMIN,
            company=other_company,
        )
        api = self.api_as(self.owner)
        rows = api.get('/api/v1/messaging/employees/').data
        rows = rows['results'] if 'results' in rows else rows
        self.assertNotIn('foreign_admin', {row['username'] for row in rows})

    def test_cannot_post_message_into_foreign_conversation(self):
        """IDOR в чате: беседа чужой компании недоступна даже по прямому id."""
        from apps.messaging.models import Conversation

        other_company = Company.objects.create(name='OtherCo3')
        foreign = Conversation.objects.create(
            company=other_company, kind=Conversation.Kind.GENERAL,
        )
        api = self.api_as(self.owner)
        response = api.post('/api/v1/messaging/messages/', {
            'conversation': foreign.id, 'content': 'подмена',
        }, format='json')
        self.assertIn(response.status_code, (400, 403, 404), response.data)
