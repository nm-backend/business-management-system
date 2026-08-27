"""
Сквозная сверка финансов: DB == API (analytics) == расчёты == экспорт.

Один реалистичный сценарий через публичный API:

  1. Приход сырья (incoming): 100 м² по 50 → средняя себестоимость 50.
  2. Производство: работник сдаёт 5 шт, владелец подтверждает.
     Сырьё -10 м² (по рецепту 2 м²/шт), товар +5 шт, начислено 5 × 1000 = 5000.
     Себестоимость партии = (10×50 + 5000)/5 = 1100 за шт.
  3. Заказ клиента на 5 шт на 100 000.
  4. Частичная оплата 40 000 + доплата 30 000 (итого 70 000, долг 30 000).
  5. Выдача: списание 5 шт, COGS = 5 × 1100 = 5500 (снимок на дату выдачи).
  6. Расход (аренда) 10 000.
  7. Выплата работнику 2 000.

Ожидаемые показатели (месяц):

    revenue        70 000
    cost_of_goods   5 500
    gross_profit   64 500
    expenses       10 000
    worker_payments 2 000
    net_profit     52 500   (= 70000 - 5500 - 10000 - 2000)
    cash           58 000   (= 70000 - 10000 - 2000)
    client_debts   30 000
    worker_debts    3 000   (= начислено 5000 - выплачено 2000, накопительно)

Склад: сырьё 90 м², товар 0 шт (5 произведено, 5 выдано), потребность 0.

Все три среза (БД, analytics-API/дашборд, экспорт) обязаны совпадать.
"""
import datetime
from decimal import Decimal

from django.db.models import Sum
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client, Payment
from apps.companies.models import Company
from apps.finance.models import Expense, ExpenseCategory, LaborRate, WorkerPayment
from apps.production.models import WorkRecord
from apps.warehouse.models import RawMaterial, Recipe, RecipeItem, FinishedProduct, StockMovement

RAW_MATERIALS = '/api/v1/warehouse/raw-materials/'
ORDERS = '/api/v1/orders/orders/'
TASKS = '/api/v1/production/tasks/'
WORKS = '/api/v1/production/works/'
PAYMENTS = '/api/v1/clients/payments/'
EXPENSES = '/api/v1/finance/expenses/'
WORKER_PAYMENTS = '/api/v1/finance/worker-payments/'
SETTLEMENTS = '/api/v1/finance/worker-payments/settlements/'
ANALYTICS = '/api/v1/reports/analytics/owner/'
EXPORT = '/api/v1/reports/export/finance/'


class EndToEndReconciliationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='ReconCo', is_active=True)
        self.owner = User.objects.create_user(username='rec_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='rec_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.client = Client.objects.create(company=self.company, name='Клиент')
        self.material = RawMaterial.objects.create(
            company=self.company, name='Гранит', unit='m2', quantity=Decimal('0'))
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('0'), unit='dona')

        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.wapi = APIClient()
        self.wapi.force_authenticate(self.worker)

        # 1. Приход сырья по цене 50 → средняя себестоимость 50.
        resp = self.api.post(f'{RAW_MATERIALS}{self.material.id}/incoming/',
                             {'quantity': '100', 'price_per_unit': '50'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content[:300])

        # Рецепт (2 м² на 1 шт) и ставка оплаты труда (1000 за шт).
        recipe = Recipe.objects.create(company=self.company, product=self.product,
                                       name='Основной', is_active=True)
        RecipeItem.objects.create(recipe=recipe, material=self.material,
                                  quantity_required=Decimal('2'), unit='m2')
        LaborRate.objects.create(company=self.company, product=self.product,
                                 operation=LaborRate.OperationType.CUTTING,
                                 rate_per_unit=Decimal('1000'), unit='dona')

        # 2. Заказ клиента на 5 шт.
        resp = self.api.post(ORDERS, {
            'client': self.client.id, 'product': self.product.id,
            'quantity': '5', 'unit': 'dona', 'total_amount': '100000',
            'deadline': (timezone.now() + datetime.timedelta(days=5)).isoformat(),
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        self.order_id = resp.json()['id']

        # 3. Производство: задача -> принятие -> сдача -> подтверждение.
        resp = self.api.post(TASKS, {'order': self.order_id, 'worker': self.worker.id},
                             format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        task_id = resp.json()['id']
        self.assertEqual(self.wapi.post(f'{TASKS}{task_id}/accept/', {}, format='json').status_code, 200)
        resp = self.wapi.post(WORKS, {
            'task': task_id, 'product': self.product.id, 'operation': 'cutting',
            'quantity': '5', 'unit': 'dona',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        work_id = resp.json()['id']
        resp = self.api.post(f'{WORKS}{work_id}/confirm/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content[:300])

        # 4. Частичная оплата + доплата.
        for amount in ('40000', '30000'):
            resp = self.api.post(PAYMENTS, {
                'client': self.client.id, 'order': self.order_id, 'amount': amount,
                'payment_method': 'cash', 'payment_date': timezone.localdate().isoformat(),
            }, format='json')
            self.assertEqual(resp.status_code, 201, resp.content[:300])

        # 5. Выдача (COGS снимается по снимку себестоимости на дату выдачи).
        resp = self.api.post(f'{ORDERS}{self.order_id}/deliver/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content[:300])

        # 6. Расход.
        resp = self.api.post(EXPENSES, {
            'category': ExpenseCategory.RENT, 'amount': '10000',
            'date': timezone.localdate().isoformat(),
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:300])

        # 7. Выплата работнику.
        resp = self.api.post(WORKER_PAYMENTS, {
            'worker': self.worker.id, 'amount': '2000',
            'payment_type': WorkerPayment.PaymentType.SALARY,
            'payment_date': timezone.localdate().isoformat(),
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:300])

    # ── Склад ─────────────────────────────────────────────────────────
    def test_stock_reconciliation(self):
        self.material.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('90.000'), 'сырьё: 100 - 10')
        self.assertEqual(self.material.avg_cost_price, Decimal('50.00'))
        self.assertEqual(self.product.quantity, Decimal('0.000'), 'товар: 5 произвели, 5 выдали')
        self.assertEqual(self.product.required_for_orders, Decimal('0.000'))
        self.assertEqual(self.material.required_for_orders, Decimal('0.000'))
        # Журнал движений полон и согласован.
        kinds = set(StockMovement.objects.values_list('movement_type', flat=True))
        self.assertEqual(kinds, {
            StockMovement.MovementType.INCOMING,
            StockMovement.MovementType.PRODUCTION_OUT,
            StockMovement.MovementType.PRODUCTION_IN,
            StockMovement.MovementType.OUTGOING,
        })
        produced = StockMovement.objects.get(movement_type=StockMovement.MovementType.PRODUCTION_IN)
        self.assertEqual(produced.quantity, Decimal('5.000'))

    # ── Деньги: БД == аналитика == расчёты ───────────────────────────
    def test_every_money_figure_matches(self):
        # БД (независимые агрегаты).
        revenue_db = Payment.objects.filter(company=self.company).aggregate(s=Sum('amount'))['s']
        expenses_db = Expense.objects.filter(company=self.company).aggregate(s=Sum('amount'))['s']
        payout_db = WorkerPayment.objects.filter(company=self.company).aggregate(s=Sum('amount'))['s']
        self.client.refresh_from_db()
        work = WorkRecord.objects.get(worker=self.worker)
        self.assertEqual(work.labor_cost, Decimal('5000.00'), '5 × 1000')

        d = self.api.get(ANALYTICS, {'period': 'month'}).json()
        self.assertEqual(Decimal(str(revenue_db)), Decimal('70000.00'))
        self.assertEqual(Decimal(str(d['revenue'])), Decimal(str(revenue_db)))
        self.assertEqual(Decimal(str(d['revenue'])), Decimal('70000'))
        self.assertEqual(Decimal(str(d['cost_of_goods'])), Decimal('5500'))
        self.assertEqual(Decimal(str(d['gross_profit'])), Decimal('64500'))
        self.assertEqual(Decimal(str(d['expenses_total'])), Decimal(str(expenses_db)))
        self.assertEqual(Decimal(str(d['worker_payments'])), Decimal(str(payout_db)))
        self.assertEqual(Decimal(str(d['net_profit'])), Decimal('52500'))
        self.assertEqual(Decimal(str(d['cash'])), Decimal('58000'))
        self.assertEqual(Decimal(str(d['client_debts'])), Decimal(str(self.client.debt)))
        self.assertEqual(Decimal(str(self.client.debt)), Decimal('30000'))

    def test_worker_debt_matches_settlements(self):
        rows = self.api.get(SETTLEMENTS).json()
        mine = [r for r in rows['results'] if r['worker'] == self.worker.id][0]
        self.assertEqual(Decimal(str(mine['accrued'])), Decimal('5000'))
        self.assertEqual(Decimal(str(mine['paid'])), Decimal('2000'))
        self.assertEqual(Decimal(str(mine['balance'])), Decimal('3000'))
        d = self.api.get(ANALYTICS, {'period': 'month'}).json()
        self.assertEqual(Decimal(str(d['worker_debts'])), Decimal(str(rows['total_balance'])))

    def test_export_matches_analytics(self):
        d = self.api.get(ANALYTICS, {'period': 'month'}).json()
        resp = self.api.get(EXPORT, {'format': 'csv'})
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        body = resp.content.decode('utf-8', 'replace').replace(' ', '')
        # Экспорт использует тот же owner_analytics_data: ключевые суммы совпадают.
        for label, value in (
            ('Даромад', '70000'),       # revenue
            ('Таннарх', '5500'),        # COGS
            ('Соффойда', '52500'),      # net profit
            ('Касса', '58000'),         # cash
            ('Мижозларқарзи', '30000'),  # client debt
            ('Ишчиларқарзи', '3000'),    # worker debt
        ):
            self.assertIn(f'{label};{value}', body, f'в экспорте нет {label};{value}')
        # И сверяем с API: те же суммы.
        self.assertEqual(Decimal(str(d['revenue'])), Decimal('70000'))
        self.assertEqual(Decimal(str(d['net_profit'])), Decimal('52500'))
        self.assertEqual(Decimal(str(d['cash'])), Decimal('58000'))


class PeriodBoundaryReconciliationTests(TestCase):
    """
    Границы периодов: DateTimeField (платежи) vs DateField (расходы/выплаты).

    Операция на границе месяца обязана попасть ровно в ОДИН период:
    - платёж 31 июля 23:59:59 (локальное время) — в июль, не в август;
    - платёж 1 августа 00:00:00 — в август, не в июль;
    - расход (DateField) 31 июля и 1 августа — в свои месяцы.
    Сумма месяцев обязана равняться итогу за общий период (без задвоения).
    """
    def setUp(self):
        self.company = Company.objects.create(name='PBoundCo', is_active=True)
        self.owner = User.objects.create_user(username='pb_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.client = Client.objects.create(company=self.company, name='К')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _pay(self, year, month, day, hour, minute, second, amount):
        aware = timezone.make_aware(datetime.datetime(year, month, day, hour, minute, second))
        Payment.objects.create(company=self.company, client=self.client,
                               amount=Decimal(amount), payment_method='cash',
                               payment_date=aware)

    def analytics(self, date_from, date_to):
        resp = self.api.get(ANALYTICS, {'date_from': date_from, 'date_to': date_to})
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        return resp.json()

    def test_payment_at_midnight_boundaries_land_in_one_period(self):
        # Платежи на границе июля/августа.
        self._pay(2026, 7, 31, 23, 59, 59, '1000')   # последняя секунда июля
        self._pay(2026, 8, 1, 0, 0, 0, '2000')       # первая секунда августа
        # Расходы (DateField) по обе стороны границы.
        Expense.objects.create(company=self.company, category=ExpenseCategory.RENT,
                               amount=Decimal('100'), date=datetime.date(2026, 7, 31))
        Expense.objects.create(company=self.company, category=ExpenseCategory.RENT,
                               amount=Decimal('200'), date=datetime.date(2026, 8, 1))

        jul = self.analytics('2026-07-01', '2026-07-31')
        aug = self.analytics('2026-08-01', '2026-08-31')
        both = self.analytics('2026-07-01', '2026-08-31')

        # Каждая операция ровно в одном месяце.
        self.assertEqual(Decimal(str(jul['revenue'])), Decimal('1000'))
        self.assertEqual(Decimal(str(aug['revenue'])), Decimal('2000'))
        self.assertEqual(Decimal(str(jul['expenses_total'])), Decimal('100'))
        self.assertEqual(Decimal(str(aug['expenses_total'])), Decimal('200'))

        # Итог за два месяца = сумма месяцев, без задвоения.
        self.assertEqual(Decimal(str(both['revenue'])), Decimal('3000'))
        self.assertEqual(Decimal(str(both['expenses_total'])), Decimal('300'))

    def test_preset_periods_do_not_double_count(self):
        """Сегодняшняя операция попадает ровно в один пресет (today/week/month/year)."""
        Payment.objects.create(company=self.company, client=self.client,
                               amount=Decimal('500'), payment_method='cash',
                               payment_date=timezone.now())
        Expense.objects.create(company=self.company, category=ExpenseCategory.RENT,
                               amount=Decimal('50'), date=timezone.localdate())
        for period in ('today', 'week', 'month', 'quarter', 'year'):
            d = self.api.get(ANALYTICS, {'period': period}).json()
            self.assertEqual(Decimal(str(d['revenue'])), Decimal('500'), period)
            self.assertEqual(Decimal(str(d['expenses_total'])), Decimal('50'), period)
