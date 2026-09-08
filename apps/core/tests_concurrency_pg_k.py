"""
Adversarial-проверка конкурентности на НАСТОЯЩЕМ PostgreSQL.

Зачем отдельный файл: sqlite сериализует записи на уровне файла, поэтому
«параллельные» тесты там всегда зелёные и дают ложную уверенность. Реальные
гонки — потерянные обновления, двойное списание, дубликаты и взаимоблокировки —
воспроизводятся только на движке с построчными блокировками.

Каждый тест запускает N ПОТОКОВ, синхронизированных барьером, чтобы запросы
входили в критическую секцию одновременно, и проверяет ИНВАРИАНТ (сколько
операций реально применилось и в каком состоянии остались данные), а не просто
код ответа.

Тесты пропускаются, если БД не PostgreSQL — молча «зеленеть» на sqlite они не
должны.
"""
import threading
from decimal import Decimal

from django.db import connection, connections
from django.test import TransactionTestCase, tag
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client, Payment
from apps.companies.models import Company
from apps.finance.models import LaborRate, WorkerPayment
from apps.orders.models import Order
from apps.production.models import Task, TaskStatus, WorkRecord
from apps.warehouse.models import (
    FinishedProduct, RawMaterial, Recipe, RecipeItem, StockMovement,
)

IS_POSTGRES = connection.vendor == 'postgresql'
SKIP_REASON = 'Гонки проверяются только на PostgreSQL: sqlite сериализует записи'


def run_concurrently(func, threads=2):
    """
    Запускает func(i) в нескольких потоках одновременно.

    Барьер выравнивает старт: без него первый поток успевает завершить
    транзакцию раньше, чем второй её начнёт, и гонки просто не возникает.
    Возвращает список результатов/исключений в порядке завершения.
    """
    barrier = threading.Barrier(threads)
    results = []
    lock = threading.Lock()

    def runner(index):
        try:
            barrier.wait(timeout=30)
            outcome = func(index)
        except Exception as exc:  # noqa: BLE001 — фиксируем любое исключение как результат
            outcome = exc
        finally:
            # Соединение потока обязательно закрываем: иначе TransactionTestCase
            # не сможет очистить БД (висящие сессии блокируют TRUNCATE).
            connections.close_all()
        with lock:
            results.append(outcome)

    workers = [threading.Thread(target=runner, args=(i,)) for i in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=60)
    return results


class ConcurrencyScenarioMixin:
    """Компания с сырьём, рецептом, товаром, клиентом и заказом."""

    def setUp(self):
        super().setUp()
        self.company = Company.objects.create(name='RaceCo')
        self.owner = User.objects.create_user(
            username='race_owner', password='pw', role=User.Role.OWNER, company=self.company,
        )
        self.admin = User.objects.create_user(
            username='race_admin', password='pw', role=User.Role.ADMIN, company=self.company,
        )
        self.worker = User.objects.create_user(
            username='race_worker', password='pw', role=User.Role.WORKER, company=self.company,
        )
        self.material = RawMaterial.objects.create(
            company=self.company, name='Гранит', unit='m2',
            quantity=Decimal('100'), avg_cost_price=Decimal('50.00'),
        )
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', unit='sht',
            quantity=Decimal('0'), cost_price=Decimal('0'), sale_price=Decimal('500.00'),
        )
        recipe = Recipe.objects.create(
            company=self.company, product=self.product, name='Столешница',
        )
        RecipeItem.objects.create(
            recipe=recipe, material=self.material,
            quantity_required=Decimal('2'), unit='m2',
        )
        LaborRate.objects.create(
            company=self.company, product=self.product,
            operation=LaborRate.OperationType.POLISHING,
            rate_per_unit=Decimal('150.00'), unit='sht',
        )
        self.client_obj = Client.objects.create(company=self.company, name='Акбаров')
        self.order = Order.objects.create(
            company=self.company, client=self.client_obj, product=self.product,
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('1000.00'),
            deadline=timezone.now() + timezone.timedelta(days=3),
        )

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def make_work(self, quantity='1'):
        task = Task.objects.create(
            company=self.company, order=self.order, worker=self.worker,
            assigned_by=self.owner, status=TaskStatus.ACCEPTED, title='Столешница',
        )
        return WorkRecord.objects.create(
            company=self.company, task=task, worker=self.worker, product=self.product,
            quantity=Decimal(quantity), unit='sht',
            operation=LaborRate.OperationType.POLISHING,
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION,
        )


@tag('postgres')
class ProductionConfirmRaceTests(ConcurrencyScenarioMixin, TransactionTestCase):
    """Одна работа, два одновременных подтверждения."""

    def setUp(self):
        if not IS_POSTGRES:
            self.skipTest(SKIP_REASON)
        super().setUp()

    def test_double_confirm_applies_exactly_once(self):
        work = self.make_work(quantity='3')

        def confirm(_):
            api = self.api_as(self.owner)
            response = api.post(f'/api/v1/production/works/{work.id}/confirm/', {}, format='json')
            return response.status_code

        statuses = run_concurrently(confirm, threads=2)
        codes = sorted(s for s in statuses if isinstance(s, int))
        # 409 Conflict — корректный ответ проигравшего запроса гонки.
        self.assertEqual(codes[0], 200, f'одно подтверждение должно пройти: {statuses}')
        self.assertIn(codes[1], (400, 409), f'второе должно быть отклонено: {statuses}')

        self.material.refresh_from_db()
        self.product.refresh_from_db()
        work.refresh_from_db()
        # Рецепт 2 м² × 3 шт = 6 м² ровно ОДИН раз.
        self.assertEqual(self.material.quantity, Decimal('94.000'))
        self.assertEqual(self.product.quantity, Decimal('3.000'))
        self.assertEqual(work.status, WorkRecord.WorkStatus.CONFIRMED)
        self.assertEqual(work.labor_cost, Decimal('450.00'))

        # Движений склада тоже ровно по одному на сторону — дубликатов нет.
        self.assertEqual(StockMovement.objects.filter(
            movement_type=StockMovement.MovementType.PRODUCTION_OUT,
            related_production_id=work.id,
        ).count(), 1)
        self.assertEqual(StockMovement.objects.filter(
            movement_type=StockMovement.MovementType.PRODUCTION_IN,
            related_production_id=work.id,
        ).count(), 1)

    def test_confirm_and_reject_race_resolves_to_one_outcome(self):
        """Подтверждение и отклонение одновременно: побеждает ровно одно."""
        work = self.make_work(quantity='2')

        def act(index):
            api = self.api_as(self.owner)
            if index == 0:
                return ('confirm', api.post(
                    f'/api/v1/production/works/{work.id}/confirm/', {}, format='json',
                ).status_code)
            return ('reject', api.post(
                f'/api/v1/production/works/{work.id}/reject/',
                {'reason': 'брак'}, format='json',
            ).status_code)

        results = run_concurrently(act, threads=2)
        ok = [r for r in results if isinstance(r, tuple) and r[1] == 200]
        self.assertEqual(len(ok), 1, f'должна пройти ровно одна операция: {results}')

        work.refresh_from_db()
        self.material.refresh_from_db()
        if work.status == WorkRecord.WorkStatus.CONFIRMED:
            self.assertEqual(self.material.quantity, Decimal('96.000'))
        else:
            self.assertEqual(work.status, WorkRecord.WorkStatus.REJECTED)
            self.assertEqual(self.material.quantity, Decimal('100.000'))

    def test_two_different_works_do_not_deadlock(self):
        """
        Две разные работы по одному материалу подтверждаются одновременно.

        Классический источник взаимоблокировки: строки берутся в разном
        порядке. Проверяем, что обе проходят и остаток сходится.
        """
        work_a = self.make_work(quantity='2')
        work_b = self.make_work(quantity='3')

        def confirm(index):
            work = work_a if index == 0 else work_b
            api = self.api_as(self.owner)
            response = api.post(f'/api/v1/production/works/{work.id}/confirm/', {}, format='json')
            return response.status_code

        results = run_concurrently(confirm, threads=2)
        self.assertEqual(sorted(r for r in results if isinstance(r, int)), [200, 200], results)

        self.material.refresh_from_db()
        # (2 + 3) изделия × 2 м² = 10 м²
        self.assertEqual(self.material.quantity, Decimal('90.000'))


@tag('postgres')
class StockRaceTests(ConcurrencyScenarioMixin, TransactionTestCase):
    """Склад: одновременные списания, приходы и возвраты."""

    def setUp(self):
        if not IS_POSTGRES:
            self.skipTest(SKIP_REASON)
        super().setUp()

    def test_parallel_write_offs_cannot_exceed_stock(self):
        """
        Двое списывают по 60 м² при остатке 100: пройти должно только одно.

        Без блокировки строки оба запроса прочитали бы «доступно 100», и
        остаток ушёл бы в минус.
        """
        self.material.quantity = Decimal('100')
        self.material.save(update_fields=['quantity'])

        def write_off(_):
            api = self.api_as(self.owner)
            return api.post(
                f'/api/v1/warehouse/raw-materials/{self.material.id}/outgoing/',
                {'quantity': '60'}, format='json',
            ).status_code

        results = run_concurrently(write_off, threads=2)
        codes = sorted(r for r in results if isinstance(r, int))
        self.assertEqual(codes, [200, 400], f'ожидались 200 и 400: {results}')

        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('40.000'))
        self.assertGreaterEqual(self.material.quantity, Decimal('0'))

    def test_parallel_incoming_are_both_applied(self):
        """
        Два прихода по 10 обязаны дать +20 (проверка на потерянное обновление).

        Именно здесь раньше терялась поставка: количество складывал браузер и
        присылал абсолютное значение.
        """
        self.material.quantity = Decimal('0')
        self.material.save(update_fields=['quantity'])

        def incoming(_):
            api = self.api_as(self.owner)
            return api.post(
                f'/api/v1/warehouse/raw-materials/{self.material.id}/incoming/',
                {'quantity': '10'}, format='json',
            ).status_code

        results = run_concurrently(incoming, threads=2)
        self.assertEqual(sorted(r for r in results if isinstance(r, int)), [200, 200], results)

        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('20.000'))
        self.assertEqual(StockMovement.objects.filter(
            material=self.material,
            movement_type=StockMovement.MovementType.INCOMING,
        ).count(), 2)

    def test_parallel_returns_are_both_applied(self):
        self.material.quantity = Decimal('5')
        self.material.save(update_fields=['quantity'])

        def do_return(_):
            api = self.api_as(self.owner)
            return api.post(
                f'/api/v1/warehouse/raw-materials/{self.material.id}/returned/',
                {'quantity': '3'}, format='json',
            ).status_code

        results = run_concurrently(do_return, threads=2)
        self.assertEqual(sorted(r for r in results if isinstance(r, int)), [200, 200], results)
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('11.000'))


@tag('postgres')
class OrderDeliveryRaceTests(ConcurrencyScenarioMixin, TransactionTestCase):
    """Одновременная выдача одного заказа."""

    def setUp(self):
        if not IS_POSTGRES:
            self.skipTest(SKIP_REASON)
        super().setUp()

    def test_double_delivery_writes_off_once(self):
        self.product.quantity = Decimal('10')
        self.product.save(update_fields=['quantity'])
        self.order.status = Order.Status.READY
        self.order.save(update_fields=['status'])

        def deliver(_):
            api = self.api_as(self.owner)
            return api.post(
                f'/api/v1/orders/orders/{self.order.id}/deliver/', {}, format='json',
            ).status_code

        results = run_concurrently(deliver, threads=2)
        codes = sorted(r for r in results if isinstance(r, int))
        self.assertEqual(codes.count(200), 1, f'выдача должна пройти один раз: {results}')

        self.product.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('9.000'))
        self.assertEqual(self.order.status, Order.Status.DELIVERED)


@tag('postgres')
class PaymentRaceTests(ConcurrencyScenarioMixin, TransactionTestCase):
    """Оплаты клиента и выплаты работнику под конкуренцией."""

    def setUp(self):
        if not IS_POSTGRES:
            self.skipTest(SKIP_REASON)
        super().setUp()

    def test_parallel_payments_cannot_overpay_order(self):
        """
        Два платежа по 700 при долге 1000: суммарно оплачено не больше долга.

        Без блокировки заказа оба прочитали бы «оплачено 0» и записали 1400.
        """
        def pay(_):
            api = self.api_as(self.owner)
            return api.post('/api/v1/clients/payments/', {
                'client': self.client_obj.id,
                'order': self.order.id,
                'amount': '700.00',
                'payment_date': timezone.now().isoformat(),
            }, format='json').status_code

        results = run_concurrently(pay, threads=2)
        codes = [r for r in results if isinstance(r, int)]
        self.order.refresh_from_db()
        total_paid = sum(
            (p.amount for p in Payment.objects.filter(order=self.order)), Decimal('0')
        )
        self.assertLessEqual(
            total_paid, self.order.total_amount,
            f'переплата при гонке: оплачено {total_paid} при сумме {self.order.total_amount} ({codes})',
        )
        self.assertLessEqual(self.order.paid_amount, self.order.total_amount)

    def test_parallel_worker_payments_are_both_recorded_without_corruption(self):
        """
        Две выплаты работнику одновременно: обе записаны, сумма сходится.

        Проверяем отсутствие потерянного обновления в агрегате «выплачено».
        """
        WorkRecord.objects.create(
            company=self.company, worker=self.worker, product=self.product,
            quantity=Decimal('10'), unit='sht', status=WorkRecord.WorkStatus.CONFIRMED,
            labor_cost=Decimal('1500.00'),
        )

        def pay(_):
            api = self.api_as(self.owner)
            return api.post('/api/v1/finance/worker-payments/', {
                'worker': self.worker.id,
                'amount': '500.00',
                'payment_date': timezone.now().date().isoformat(),
            }, format='json').status_code

        results = run_concurrently(pay, threads=2)
        created = [r for r in results if isinstance(r, int) and r == 201]
        payments = WorkerPayment.objects.filter(worker=self.worker)
        self.assertEqual(payments.count(), len(created), f'записей больше, чем успешных ответов: {results}')

        total = sum((p.amount for p in payments), Decimal('0'))
        earnings = self.api_as(self.worker).get('/api/v1/production/works/my_earnings/').data
        self.assertEqual(Decimal(str(earnings['paid_out'])), total,
                         'агрегат «выплачено» разошёлся с фактическими выплатами')

    def test_payment_over_debt_rejected_under_race(self):
        """Долг закрывается первым платежом — второй такой же обязан отпасть."""
        def pay(_):
            api = self.api_as(self.owner)
            return api.post('/api/v1/clients/payments/', {
                'client': self.client_obj.id,
                'order': self.order.id,
                'amount': '1000.00',
                'payment_date': timezone.now().isoformat(),
            }, format='json').status_code

        results = run_concurrently(pay, threads=2)
        codes = sorted(r for r in results if isinstance(r, int))
        self.assertEqual(codes.count(201), 1, f'принят должен быть ровно один платёж: {results}')

        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal('1000.00'))
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.debt, Decimal('0.00'))


@tag('postgres')
class DecimalOnPostgresTests(ConcurrencyScenarioMixin, TransactionTestCase):
    """numeric в PostgreSQL: деньги не превращаются в float."""

    def setUp(self):
        if not IS_POSTGRES:
            self.skipTest(SKIP_REASON)
        super().setUp()

    def test_money_columns_are_numeric(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT data_type FROM information_schema.columns
                WHERE table_name = 'orders_order' AND column_name = 'total_amount'
            """)
            self.assertEqual(cursor.fetchone()[0], 'numeric')

    def test_decimal_arithmetic_has_no_binary_drift(self):
        """0.1 + 0.2 в деньгах обязано дать ровно 0.30, а не 0.30000000000000004."""
        client = Client.objects.create(company=self.company, name='Копейки')
        order = Order.objects.create(
            company=self.company, client=client, product=self.product,
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('0.30'),
            deadline=timezone.now() + timezone.timedelta(days=1),
        )
        api = self.api_as(self.owner)
        for amount in ('0.10', '0.20'):
            response = api.post('/api/v1/clients/payments/', {
                'client': client.id, 'order': order.id, 'amount': amount,
                'payment_date': timezone.now().isoformat(),
            }, format='json')
            self.assertEqual(response.status_code, 201, response.data)

        order.refresh_from_db()
        client.refresh_from_db()
        self.assertEqual(order.paid_amount, Decimal('0.30'))
        self.assertEqual(client.debt, Decimal('0.00'))
        self.assertIsInstance(order.paid_amount, Decimal)


@tag('postgres')
class HighContentionTests(ConcurrencyScenarioMixin, TransactionTestCase):
    """
    Усиленное давление: 8 потоков на одну строку.

    Два потока могут «разъехаться» по времени и не создать гонки вовсе —
    тест тогда зелёный, но ничего не доказывает. Восемь одновременных
    запросов почти гарантированно пересекаются в критической секции.
    """

    def setUp(self):
        if not IS_POSTGRES:
            self.skipTest(SKIP_REASON)
        super().setUp()

    def test_eight_write_offs_respect_stock_exactly(self):
        """
        Остаток 100, восемь запросов по 20 — пройти обязаны ровно пять.

        Инвариант жёсткий: сумма успешных списаний равна убыли остатка, а сам
        остаток не уходит ниже нуля.
        """
        self.material.quantity = Decimal('100')
        self.material.save(update_fields=['quantity'])

        def write_off(_):
            api = self.api_as(self.owner)
            return api.post(
                f'/api/v1/warehouse/raw-materials/{self.material.id}/outgoing/',
                {'quantity': '20'}, format='json',
            ).status_code

        results = run_concurrently(write_off, threads=8)
        codes = [r for r in results if isinstance(r, int)]
        successes = codes.count(200)

        self.material.refresh_from_db()
        self.assertEqual(successes, 5, f'должно пройти ровно пять списаний: {results}')
        self.assertEqual(self.material.quantity, Decimal('0.000'))
        self.assertGreaterEqual(self.material.quantity, Decimal('0'))
        self.assertEqual(
            StockMovement.objects.filter(
                material=self.material,
                movement_type=StockMovement.MovementType.OUTGOING,
            ).count(),
            successes,
            'число движений склада разошлось с числом успешных операций',
        )

    def test_eight_incoming_sum_exactly(self):
        """Восемь приходов по 5 обязаны дать ровно +40 (ни одна поставка не потеряна)."""
        self.material.quantity = Decimal('0')
        self.material.save(update_fields=['quantity'])

        def incoming(_):
            api = self.api_as(self.owner)
            return api.post(
                f'/api/v1/warehouse/raw-materials/{self.material.id}/incoming/',
                {'quantity': '5'}, format='json',
            ).status_code

        results = run_concurrently(incoming, threads=8)
        successes = [r for r in results if isinstance(r, int) and r == 200]
        self.assertEqual(len(successes), 8, f'все приходы должны пройти: {results}')

        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('40.000'))

    def test_eight_confirms_of_one_work_apply_once(self):
        work = self.make_work(quantity='1')

        def confirm(_):
            api = self.api_as(self.owner)
            return api.post(
                f'/api/v1/production/works/{work.id}/confirm/', {}, format='json',
            ).status_code

        results = run_concurrently(confirm, threads=8)
        codes = [r for r in results if isinstance(r, int)]
        self.assertEqual(codes.count(200), 1, f'подтвердиться должно ровно раз: {results}')

        self.material.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('98.000'))
        self.assertEqual(self.product.quantity, Decimal('1.000'))
        self.assertEqual(WorkRecord.objects.get(pk=work.pk).labor_cost, Decimal('150.00'))

    def test_eight_payments_never_overpay(self):
        """Восемь платежей по 200 при долге 1000: суммарно не больше долга."""
        def pay(_):
            api = self.api_as(self.owner)
            return api.post('/api/v1/clients/payments/', {
                'client': self.client_obj.id,
                'order': self.order.id,
                'amount': '200.00',
                'payment_date': timezone.now().isoformat(),
            }, format='json').status_code

        results = run_concurrently(pay, threads=8)
        codes = [r for r in results if isinstance(r, int)]
        self.order.refresh_from_db()
        total_paid = sum(
            (p.amount for p in Payment.objects.filter(order=self.order)), Decimal('0')
        )
        self.assertLessEqual(
            total_paid, self.order.total_amount,
            f'переплата под нагрузкой: {total_paid} > {self.order.total_amount} ({codes})',
        )
        self.assertEqual(self.order.paid_amount, total_paid,
                         'агрегат заказа разошёлся с суммой платежей')

    def test_no_deadlock_on_mixed_operations(self):
        """
        Смешанная нагрузка на один материал: приход, расход, возврат, подтверждение.

        Разный порядок захвата строк — классическая причина взаимоблокировки.
        Проверяем, что ни один запрос не упал с deadlock/ошибкой сервера.
        """
        work = self.make_work(quantity='1')

        def mixed(index):
            api = self.api_as(self.owner)
            if index % 4 == 0:
                return api.post(
                    f'/api/v1/warehouse/raw-materials/{self.material.id}/incoming/',
                    {'quantity': '5'}, format='json').status_code
            if index % 4 == 1:
                return api.post(
                    f'/api/v1/warehouse/raw-materials/{self.material.id}/outgoing/',
                    {'quantity': '5'}, format='json').status_code
            if index % 4 == 2:
                return api.post(
                    f'/api/v1/warehouse/raw-materials/{self.material.id}/returned/',
                    {'quantity': '5'}, format='json').status_code
            return api.post(
                f'/api/v1/production/works/{work.id}/confirm/', {}, format='json').status_code

        results = run_concurrently(mixed, threads=8)
        server_errors = [r for r in results if isinstance(r, int) and r >= 500]
        exceptions = [r for r in results if isinstance(r, Exception)]
        self.assertFalse(server_errors, f'ответы 5xx под нагрузкой: {results}')
        self.assertFalse(exceptions, f'исключения (deadlock?) под нагрузкой: {exceptions}')

        self.material.refresh_from_db()
        self.assertGreaterEqual(self.material.quantity, Decimal('0'))


@tag('postgres')
class TransactionUsageTests(ConcurrencyScenarioMixin, TransactionTestCase):
    """
    select_for_update обязан вызываться внутри транзакции.

    Найдено аудитом: Task.confirm() использовал select_for_update, но своей
    транзакции не открывал. Работало лишь потому, что единственный вызывающий
    (confirm_work) обёрнут в atomic; прямой вызов из любой вьюхи давал
    TransactionManagementError и 500.
    """

    def setUp(self):
        if not IS_POSTGRES:
            self.skipTest(SKIP_REASON)
        super().setUp()

    def test_task_confirm_works_outside_transaction(self):
        task = Task.objects.create(
            company=self.company, order=self.order, worker=self.worker,
            assigned_by=self.owner, status=TaskStatus.ACCEPTED, title='Столешница',
        )
        self.product.quantity = Decimal('5')
        self.product.save(update_fields=['quantity'])

        # Вызов В АВТОКОММИТЕ — именно так его сделает новая вьюха.
        task.confirm(self.owner)

        task.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.CONFIRMED)
        self.assertEqual(self.order.status, Order.Status.READY)

    def test_no_select_for_update_outside_atomic_in_codebase(self):
        """
        Статический страж: ни один select_for_update не должен оказаться вне
        atomic-блока. Дешевле поймать разбором AST, чем ловить 500 на бою.
        """
        import ast
        import pathlib

        from django.conf import settings

        root = pathlib.Path(settings.BASE_DIR) / 'apps'
        offenders = []

        class Checker(ast.NodeVisitor):
            def __init__(self, path):
                self.path = path
                self.depth = 0

            def _is_atomic(self, node):
                return (
                    (isinstance(node, ast.Attribute) and node.attr == 'atomic')
                    or (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == 'atomic')
                )

            def visit_FunctionDef(self, node):
                decorated = any(self._is_atomic(d) for d in node.decorator_list)
                self.depth += int(decorated)
                self.generic_visit(node)
                self.depth -= int(decorated)

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_With(self, node):
                inside = any(self._is_atomic(item.context_expr) for item in node.items)
                self.depth += int(inside)
                self.generic_visit(node)
                self.depth -= int(inside)

            def visit_Call(self, node):
                if isinstance(node.func, ast.Attribute) and node.func.attr == 'select_for_update':
                    if self.depth == 0:
                        offenders.append(f'{self.path}:{node.lineno}')
                self.generic_visit(node)

        for path in sorted(root.rglob('*.py')):
            if 'tests' in path.name or 'migrations' in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            Checker(path.relative_to(settings.BASE_DIR)).visit(tree)

        self.assertFalse(
            offenders,
            'select_for_update вне транзакции (упадёт TransactionManagementError):\n  '
            + '\n  '.join(offenders),
        )
