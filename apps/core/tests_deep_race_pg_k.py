"""
Второй проход adversarial-аудита на PostgreSQL: то, что не проверялось в первом.

Первый проход бил по очевидным местам (подтверждение работы, списание, выдача,
оплата). Здесь — менее очевидные, где read-modify-write легко пропустить:

* потребность под заказы (`required_for_orders`) при параллельном создании;
* агрегаты клиента при оплате РАЗНЫХ заказов одновременно;
* потолок выплат работнику (две выплаты, каждая в пределах остатка);
* активация по одному ключу доступа двумя запросами;
* выдача двух заказов на один товар при остатке только под один;
* дубликаты: беседа чата и уведомления при параллельных запросах;
* утечка чужого tenant через query-фильтры (?worker=, ?client=, ?product=);
* семантика рецепта при несовпадении единиц измерения.

Все тесты — TransactionTestCase на PostgreSQL: sqlite сериализует записи и
такие гонки там невоспроизводимы.
"""
import threading
from decimal import Decimal

from django.db import connection, connections
from django.test import TransactionTestCase, tag
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import AccessKey, User
from apps.clients.models import Client, Payment
from apps.companies.models import Company
from apps.finance.models import LaborRate, WorkerPayment
from apps.messaging.models import Conversation, Notification
from apps.orders.models import Order
from apps.production.models import Task, TaskStatus, WorkRecord
from apps.warehouse.models import FinishedProduct, RawMaterial, Recipe, RecipeItem

IS_POSTGRES = connection.vendor == 'postgresql'
SKIP_REASON = 'Гонки проверяются только на PostgreSQL: sqlite сериализует записи'


def run_concurrently(func, threads=2):
    """Запускает func(i) в нескольких потоках, стартующих по общему барьеру."""
    barrier = threading.Barrier(threads)
    results = []
    lock = threading.Lock()

    def runner(index):
        try:
            barrier.wait(timeout=30)
            outcome = func(index)
        except Exception as exc:  # noqa: BLE001 — исключение это тоже результат
            outcome = exc
        finally:
            connections.close_all()
        with lock:
            results.append(outcome)

    workers = [threading.Thread(target=runner, args=(i,)) for i in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=60)
    return results


class DeepRaceMixin:
    def setUp(self):
        if not IS_POSTGRES:
            self.skipTest(SKIP_REASON)
        super().setUp()
        self.company = Company.objects.create(name='DeepCo')
        self.owner = User.objects.create_user(
            username='deep_owner', password='pw', role=User.Role.OWNER, company=self.company,
        )
        self.admin = User.objects.create_user(
            username='deep_admin', password='pw', role=User.Role.ADMIN, company=self.company,
        )
        self.worker = User.objects.create_user(
            username='deep_worker', password='pw', role=User.Role.WORKER,
            company=self.company, full_name='Али',
        )
        self.material = RawMaterial.objects.create(
            company=self.company, name='Гранит', unit='m2',
            quantity=Decimal('100'), avg_cost_price=Decimal('50.00'),
        )
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', unit='sht',
            quantity=Decimal('1'), cost_price=Decimal('200.00'), sale_price=Decimal('500.00'),
        )
        recipe = Recipe.objects.create(
            company=self.company, product=self.product, name='Столешница',
        )
        RecipeItem.objects.create(
            recipe=recipe, material=self.material,
            quantity_required=Decimal('2'), unit='m2',
        )
        self.client_obj = Client.objects.create(company=self.company, name='Акбаров')

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def make_order(self, amount='1000.00', quantity='1', status=None):
        order = Order.objects.create(
            company=self.company, client=self.client_obj, product=self.product,
            quantity=Decimal(quantity), unit='sht', total_amount=Decimal(amount),
            deadline=timezone.now() + timezone.timedelta(days=3),
            status=status or Order.Status.NEW,
        )
        return order


@tag('postgres')
class DemandRaceTests(DeepRaceMixin, TransactionTestCase):
    """Потребность под заказы не должна теряться при параллельных заказах."""

    def test_parallel_order_creation_sums_product_demand(self):
        """
        Два заказа по 4 шт создаются одновременно: потребность обязана стать 8.

        Классический lost update: оба читают required_for_orders = 0 и пишут 4.
        """
        self.product.required_for_orders = Decimal('0')
        self.product.save(update_fields=['required_for_orders'])

        def create_order(_):
            api = self.api_as(self.owner)
            return api.post('/api/v1/orders/orders/', {
                'client': self.client_obj.id, 'product': self.product.id,
                'quantity': '4', 'unit': 'sht', 'total_amount': '400.00',
                'deadline': (timezone.now() + timezone.timedelta(days=2)).isoformat(),
            }, format='json').status_code

        results = run_concurrently(create_order, threads=2)
        created = [r for r in results if isinstance(r, int) and r == 201]
        self.assertEqual(len(created), 2, f'оба заказа должны создаться: {results}')

        self.product.refresh_from_db()
        self.assertEqual(self.product.required_for_orders, Decimal('8.000'),
                         'потерянное обновление потребности под заказы')

    def test_parallel_order_creation_sums_material_demand(self):
        """Потребность в сырье по рецепту (2 м² на изделие) тоже суммируется."""
        self.material.required_for_orders = Decimal('0')
        self.material.save(update_fields=['required_for_orders'])

        def create_order(_):
            api = self.api_as(self.owner)
            return api.post('/api/v1/orders/orders/', {
                'client': self.client_obj.id, 'product': self.product.id,
                'quantity': '3', 'unit': 'sht', 'total_amount': '300.00',
                'deadline': (timezone.now() + timezone.timedelta(days=2)).isoformat(),
            }, format='json').status_code

        results = run_concurrently(create_order, threads=4)
        created = [r for r in results if isinstance(r, int) and r == 201]
        self.assertEqual(len(created), 4, f'все заказы должны создаться: {results}')

        self.material.refresh_from_db()
        # 4 заказа × 3 изделия × 2 м² = 24
        self.assertEqual(self.material.required_for_orders, Decimal('24.000'))

    def test_parallel_cancel_does_not_drive_demand_negative(self):
        """Одновременная отмена двух заказов не уводит потребность в минус."""
        orders = [self.make_order(quantity='2') for _ in range(2)]
        for order in orders:
            order.apply_product_requirement()
        self.product.refresh_from_db()
        self.assertEqual(self.product.required_for_orders, Decimal('4.000'))

        def cancel(index):
            api = self.api_as(self.owner)
            return api.post(
                f'/api/v1/orders/orders/{orders[index].id}/cancel/', {}, format='json',
            ).status_code

        run_concurrently(cancel, threads=2)
        self.product.refresh_from_db()
        self.assertGreaterEqual(self.product.required_for_orders, Decimal('0'))
        self.assertEqual(self.product.required_for_orders, Decimal('0.000'))


@tag('postgres')
class ClientAggregateRaceTests(DeepRaceMixin, TransactionTestCase):
    """Агрегаты клиента при параллельных событиях по разным заказам."""

    def test_payments_to_different_orders_keep_client_debt_correct(self):
        """
        Оплата двух РАЗНЫХ заказов одного клиента одновременно.

        Пересчёт агрегатов читает суммы по всем заказам: без блокировки клиента
        второй пересчёт затирал бы результат первого, и долг «проседал».
        """
        order_a = self.make_order(amount='1000.00')
        order_b = self.make_order(amount='500.00')
        self.client_obj.recalculate_financials()
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.debt, Decimal('1500.00'))

        def pay(index):
            api = self.api_as(self.owner)
            order = order_a if index == 0 else order_b
            amount = '400.00' if index == 0 else '500.00'
            return api.post('/api/v1/clients/payments/', {
                'client': self.client_obj.id, 'order': order.id,
                'amount': amount, 'payment_date': timezone.now().isoformat(),
            }, format='json').status_code

        results = run_concurrently(pay, threads=2)
        self.assertEqual([r for r in results if r == 201].__len__(), 2, results)

        self.client_obj.refresh_from_db()
        paid = sum((p.amount for p in Payment.objects.filter(client=self.client_obj)), Decimal('0'))
        self.assertEqual(paid, Decimal('900.00'))
        self.assertEqual(self.client_obj.total_paid, paid,
                         'агрегат «оплачено» разошёлся с платежами')
        self.assertEqual(self.client_obj.debt, Decimal('600.00'),
                         'долг клиента посчитан неверно после параллельных оплат')

    def test_archive_and_payment_race_keeps_state_consistent(self):
        """Архивация и оплата одновременно: клиент не уходит в архив с долгом."""
        order = self.make_order(amount='1000.00', status=Order.Status.DELIVERED)
        self.client_obj.recalculate_financials()

        def act(index):
            api = self.api_as(self.owner)
            if index == 0:
                return api.post(
                    f'/api/v1/clients/clients/{self.client_obj.id}/archive/', {}, format='json',
                ).status_code
            return api.post('/api/v1/clients/payments/', {
                'client': self.client_obj.id, 'order': order.id,
                'amount': '1000.00', 'payment_date': timezone.now().isoformat(),
            }, format='json').status_code

        run_concurrently(act, threads=2)
        self.client_obj.refresh_from_db()
        if self.client_obj.is_archived:
            self.assertEqual(self.client_obj.debt, Decimal('0.00'),
                             'клиент попал в архив с непогашенным долгом')


@tag('postgres')
class PayrollCapRaceTests(DeepRaceMixin, TransactionTestCase):
    """Потолок выплат: нельзя выплатить больше начисленного."""

    def test_cap_enforced_when_payment_type_omitted(self):
        """
        Тип выплаты не прислан — по умолчанию это зарплата, потолок обязан работать.

        Регрессия: perform_create сравнивал validated_data['payment_type'] с
        SALARY, а при отсутствии ключа получал None и пропускал блокирующую
        перепроверку целиком.
        """
        WorkRecord.objects.create(
            company=self.company, worker=self.worker, product=self.product,
            quantity=Decimal('1'), unit='sht', status=WorkRecord.WorkStatus.CONFIRMED,
            labor_cost=Decimal('100.00'),
        )
        api = self.api_as(self.owner)
        response = api.post('/api/v1/finance/worker-payments/', {
            'worker': self.worker.id, 'amount': '500.00',
            'payment_date': timezone.now().date().isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(WorkerPayment.objects.filter(worker=self.worker).count(), 0)

    def test_eight_payments_cannot_exceed_earned(self):
        """Восемь одновременных выплат по 300 при начислении 1000."""
        WorkRecord.objects.create(
            company=self.company, worker=self.worker, product=self.product,
            quantity=Decimal('10'), unit='sht', status=WorkRecord.WorkStatus.CONFIRMED,
            labor_cost=Decimal('1000.00'),
        )

        def pay(_):
            api = self.api_as(self.owner)
            return api.post('/api/v1/finance/worker-payments/', {
                'worker': self.worker.id, 'amount': '300.00',
                'payment_date': timezone.now().date().isoformat(),
            }, format='json').status_code

        results = run_concurrently(pay, threads=8)
        total_paid = sum(
            (p.amount for p in WorkerPayment.objects.filter(worker=self.worker)), Decimal('0')
        )
        self.assertLessEqual(total_paid, Decimal('1000.00'),
                             f'выплачено больше начисленного: {total_paid} ({results})')
        # 1000 / 300 -> проходит ровно три выплаты
        self.assertEqual(total_paid, Decimal('900.00'))

    def test_advance_payment_has_no_cap(self):
        """Аванс по определению выдаётся до работы — на него потолка нет."""
        api = self.api_as(self.owner)
        response = api.post('/api/v1/finance/worker-payments/', {
            'worker': self.worker.id, 'amount': '500.00',
            'payment_type': 'advance',
            'payment_date': timezone.now().date().isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)

    def test_two_payments_cannot_exceed_earned(self):
        """
        Заработано 1000. Две одновременные выплаты по 800 — суммарно не больше 1000.

        Каждая по отдельности «влезает» в остаток, поэтому без блокировки
        проходят обе и работнику переплачивают 600.
        """
        WorkRecord.objects.create(
            company=self.company, worker=self.worker, product=self.product,
            quantity=Decimal('10'), unit='sht', status=WorkRecord.WorkStatus.CONFIRMED,
            labor_cost=Decimal('1000.00'),
        )

        def pay(_):
            api = self.api_as(self.owner)
            return api.post('/api/v1/finance/worker-payments/', {
                'worker': self.worker.id, 'amount': '800.00',
                'payment_date': timezone.now().date().isoformat(),
            }, format='json').status_code

        results = run_concurrently(pay, threads=2)
        total_paid = sum(
            (p.amount for p in WorkerPayment.objects.filter(worker=self.worker)), Decimal('0')
        )
        self.assertLessEqual(
            total_paid, Decimal('1000.00'),
            f'выплачено больше начисленного: {total_paid} ({results})',
        )


@tag('postgres')
class AccessKeyRaceTests(DeepRaceMixin, TransactionTestCase):
    """Один ключ доступа — одна активация."""

    def test_same_access_key_redeemed_only_once(self):
        """
        Два запроса активируют один ключ одновременно.

        Ключ одноразовый: без блокировки оба пройдут, и пароль будет
        установлен дважды — второй перезапишет первый уже после входа.
        """
        from apps.accounts.access_keys import issue_access_key

        # Приглашённый сотрудник: аккаунт создан владельцем, пароля ещё нет.
        employee = User.objects.create(
            username='new_worker', role=User.Role.WORKER,
            company=self.company, is_active=False,
        )
        employee.set_unusable_password()
        employee.save(update_fields=['password'])

        key = issue_access_key(user=employee, created_by=self.owner, expires_in_days=7)
        code = key.key

        def redeem(index):
            api = APIClient()
            return api.post('/api/v1/accounts/access-key/redeem/', {
                'access_key': code, 'new_password': f'Str0ng!Pass{index}9',
            }, format='json').status_code

        results = run_concurrently(redeem, threads=4)
        successes = [r for r in results if isinstance(r, int) and r == 200]
        self.assertEqual(len(successes), 1,
                         f'одноразовый ключ сработал больше одного раза: {results}')

        key.refresh_from_db()
        self.assertEqual(key.status, AccessKey.Status.USED)
        self.assertIsNotNone(key.used_at)

    def test_used_key_cannot_be_reused_later(self):
        """После активации ключ мёртв — повторный запрос обязан отказать."""
        from apps.accounts.access_keys import issue_access_key

        employee = User.objects.create(
            username='new_worker2', role=User.Role.WORKER,
            company=self.company, is_active=False,
        )
        employee.set_unusable_password()
        employee.save(update_fields=['password'])
        key = issue_access_key(user=employee, created_by=self.owner, expires_in_days=7)

        api = APIClient()
        first = api.post('/api/v1/accounts/access-key/redeem/', {
            'access_key': key.key, 'new_password': 'Str0ng!Pass19',
        }, format='json')
        self.assertEqual(first.status_code, 200, first.data)

        second = api.post('/api/v1/accounts/access-key/redeem/', {
            'access_key': key.key, 'new_password': 'Другой!Pass29',
        }, format='json')
        self.assertEqual(second.status_code, 400, 'использованный ключ снова сработал')


@tag('postgres')
class StockDeliveryRaceTests(DeepRaceMixin, TransactionTestCase):
    """Выдача разных заказов на один товар при дефиците остатка."""

    def test_two_orders_one_unit_in_stock(self):
        """
        Остаток 1 шт, два готовых заказа по 1 шт выдаются одновременно.

        Пройти должна ровно одна выдача — иначе остаток уходит в минус
        (переспрос допустим, отгрузка несуществующего товара — нет).
        """
        self.product.quantity = Decimal('1')
        self.product.required_for_orders = Decimal('2')
        self.product.save(update_fields=['quantity', 'required_for_orders'])

        orders = [
            self.make_order(quantity='1', status=Order.Status.READY),
            self.make_order(quantity='1', status=Order.Status.READY),
        ]

        def deliver(index):
            api = self.api_as(self.owner)
            return api.post(
                f'/api/v1/orders/orders/{orders[index].id}/deliver/', {}, format='json',
            ).status_code

        results = run_concurrently(deliver, threads=2)
        codes = [r for r in results if isinstance(r, int)]
        self.product.refresh_from_db()

        self.assertGreaterEqual(self.product.quantity, Decimal('0'),
                                f'остаток ушёл в минус: {self.product.quantity} ({codes})')
        self.assertEqual(codes.count(200), 1, f'выдаться должен ровно один заказ: {results}')


@tag('postgres')
class DuplicateRecordTests(DeepRaceMixin, TransactionTestCase):
    """Дубликаты записей при параллельных одинаковых запросах."""

    def test_parallel_start_direct_creates_single_conversation(self):
        """
        Два запроса «начать личный диалог» с одним собеседником.

        Без защиты появляются две беседы на одну пару, и сообщения
        расходятся по разным веткам.
        """
        def start(_):
            api = self.api_as(self.owner)
            response = api.post('/api/v1/messaging/conversations/start_direct/', {
                'user_id': self.worker.id,
            }, format='json')
            return (response.status_code, response.data.get('id') if response.data else None)

        results = run_concurrently(start, threads=2)
        ok = [r for r in results if isinstance(r, tuple) and r[0] in (200, 201)]
        self.assertTrue(ok, f'диалог должен создаться: {results}')

        direct = Conversation.objects.filter(
            company=self.company, kind=Conversation.Kind.DIRECT,
        )
        self.assertEqual(direct.count(), 1,
                         f'создано {direct.count()} бесед вместо одной')

    def test_parallel_order_creation_does_not_duplicate_notifications(self):
        """Одно событие — одно уведомление получателю, без дублей от гонки."""
        def create_order(_):
            api = self.api_as(self.owner)
            return api.post('/api/v1/orders/orders/', {
                'client': self.client_obj.id, 'product': self.product.id,
                'quantity': '1', 'unit': 'sht', 'total_amount': '100.00',
                'deadline': (timezone.now() + timezone.timedelta(days=2)).isoformat(),
            }, format='json').status_code

        run_concurrently(create_order, threads=3)
        orders_created = Order.objects.filter(company=self.company).count()
        notifications = Notification.objects.filter(
            type=Notification.NotificationType.NEW_ORDER, user=self.owner,
        ).count()
        self.assertEqual(notifications, orders_created,
                         'число уведомлений не совпало с числом заказов')


@tag('postgres')
class FilterTenantLeakTests(DeepRaceMixin, TransactionTestCase):
    """Утечка чужого tenant через query-фильтры."""

    def setUp(self):
        super().setUp()
        self.other_company = Company.objects.create(name='OtherDeepCo')
        self.other_owner = User.objects.create_user(
            username='other_deep_owner', password='pw', role=User.Role.OWNER,
            company=self.other_company,
        )
        self.other_worker = User.objects.create_user(
            username='other_deep_worker', password='pw', role=User.Role.WORKER,
            company=self.other_company,
        )
        self.other_client = Client.objects.create(
            company=self.other_company, name='Чужой клиент',
        )
        self.other_product = FinishedProduct.objects.create(
            company=self.other_company, name='Чужой товар', unit='sht',
            quantity=Decimal('5'), cost_price=Decimal('1.00'),
        )
        self.other_order = Order.objects.create(
            company=self.other_company, client=self.other_client,
            product=self.other_product, quantity=Decimal('1'), unit='sht',
            total_amount=Decimal('9999.00'),
            deadline=timezone.now() + timezone.timedelta(days=1),
        )
        WorkRecord.objects.create(
            company=self.other_company, worker=self.other_worker,
            product=self.other_product, quantity=Decimal('7'), unit='sht',
            status=WorkRecord.WorkStatus.CONFIRMED, labor_cost=Decimal('7777.00'),
        )

    def _rows(self, response):
        data = response.data
        return data['results'] if isinstance(data, dict) and 'results' in data else data

    def test_filters_by_foreign_id_return_nothing(self):
        api = self.api_as(self.owner)
        probes = [
            ('/api/v1/orders/orders/', {'client': self.other_client.id}),
            ('/api/v1/orders/orders/', {'product': self.other_product.id}),
            ('/api/v1/production/works/', {'worker': self.other_worker.id}),
            ('/api/v1/warehouse/stock-movements/', {'material': 999999}),
        ]
        for url, params in probes:
            response = api.get(url, params)
            self.assertIn(response.status_code, (200, 400), f'{url} -> {response.status_code}')
            if response.status_code == 200:
                self.assertEqual(len(self._rows(response)), 0,
                                 f'{url} с чужим id вернул данные: {self._rows(response)}')

    def test_search_does_not_reveal_foreign_records(self):
        api = self.api_as(self.owner)
        for url, term in (
            ('/api/v1/warehouse/raw-materials/', 'Чужой'),
            ('/api/v1/clients/clients/', 'Чужой'),
            ('/api/v1/messaging/employees/', 'other_deep'),
        ):
            response = api.get(url, {'search': term})
            if response.status_code == 200:
                body = str(self._rows(response))
                self.assertNotIn('Чужой', body, f'{url} нашёл чужую запись')
                self.assertNotIn('other_deep', body, f'{url} нашёл чужого сотрудника')

    def test_ordering_param_cannot_dump_foreign_rows(self):
        api = self.api_as(self.owner)
        response = api.get('/api/v1/orders/orders/', {'ordering': '-total_amount'})
        self.assertEqual(response.status_code, 200)
        amounts = [str(row.get('total_amount')) for row in self._rows(response)]
        self.assertNotIn('9999.00', amounts, 'сортировка выдала заказ чужой компании')


@tag('postgres')
class RecipeUnitSemanticsTests(DeepRaceMixin, TransactionTestCase):
    """Единицы измерения в рецепте: расход считается в единицах материала."""

    def test_mismatched_unit_rejected(self):
        """
        Позиция рецепта в ДРУГИХ единицах, чем материал, должна отклоняться.

        Пересчёта единиц в системе нет: «2 кг» у материала в м² молча списали
        бы 2 м² — остаток, себестоимость и расчёт нехватки поехали бы.
        """
        api = self.api_as(self.owner)
        recipe = Recipe.objects.get(product=self.product)
        response = api.post('/api/v1/warehouse/recipe-items/', {
            'recipe': recipe.id, 'material': self.material.id,
            'quantity_required': '2', 'unit': 'kg',   # материал в m2
        }, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('unit', response.data)

    def test_unit_defaults_to_material_unit(self):
        """
        Интерфейс единицу не присылает — она берётся у материала.

        Регрессия: подставлялся дефолт модели «шт», и карточка рецепта
        показывала «требуется 2 шт · доступно 100 м²» для одного и того же
        материала.
        """
        api = self.api_as(self.owner)
        recipe = Recipe.objects.get(product=self.product)
        response = api.post('/api/v1/warehouse/recipe-items/', {
            'recipe': recipe.id, 'material': self.material.id,
            'quantity_required': '2',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        item = RecipeItem.objects.get(pk=response.data['id'])
        self.assertEqual(item.unit, self.material.unit)
        self.assertEqual(item.unit, 'm2')

    def test_patch_cannot_break_unit_consistency(self):
        """Правка позиции тоже не должна разъезжаться с единицей материала."""
        api = self.api_as(self.owner)
        recipe = Recipe.objects.get(product=self.product)
        item = RecipeItem.objects.filter(recipe=recipe).first()
        response = api.patch(
            f'/api/v1/warehouse/recipe-items/{item.id}/', {'unit': 'kg'}, format='json',
        )
        self.assertEqual(response.status_code, 400, response.data)
        item.refresh_from_db()
        self.assertEqual(item.unit, 'm2')

    def test_write_off_matches_recipe_unit(self):
        """Списание идёт ровно в единицах материала: 2 м² × 3 изделия = 6 м²."""
        LaborRate.objects.create(
            company=self.company, product=self.product,
            operation=LaborRate.OperationType.POLISHING,
            rate_per_unit=Decimal('10.00'), unit='sht',
        )
        api = self.api_as(self.owner)
        task = Task.objects.create(
            company=self.company, worker=self.worker, assigned_by=self.owner,
            status=TaskStatus.ACCEPTED, title='Столешница',
        )
        work = WorkRecord.objects.create(
            company=self.company, task=task, worker=self.worker, product=self.product,
            quantity=Decimal('3'), unit='sht',
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION,
        )
        before = self.material.quantity
        response = api.post(f'/api/v1/production/works/{work.id}/confirm/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.material.refresh_from_db()
        self.assertEqual(before - self.material.quantity, Decimal('6.000'))


@tag('postgres')
class OverdueEdgeCaseTests(DeepRaceMixin, TransactionTestCase):
    """Просрочка: какие заказы вообще должны попадать в уведомления."""

    def test_archived_order_does_not_trigger_overdue(self):
        """
        Архивный заказ выведен из активного учёта — беспокоить по нему нельзя.

        Он не виден в списках и отчётах, а уведомление о его просрочке
        отправило бы владельца искать заказ, которого на экранах нет.
        """
        from django.core.management import call_command

        order = self.make_order(amount='1000.00')
        order.deadline = timezone.now() - timezone.timedelta(days=5)
        order.paid_amount = Decimal('0')
        order.is_archived = True
        order.save(update_fields=['deadline', 'paid_amount', 'is_archived'])

        call_command('notify_overdue_debts')
        self.assertEqual(
            Notification.objects.filter(
                type=Notification.NotificationType.OVERDUE_DEBT, related_order=order,
            ).count(),
            0,
            'уведомление о просрочке пришло по архивному заказу',
        )

    def test_delivered_unpaid_order_is_overdue(self):
        """Товар выдан, деньги не получены — это как раз просрочка."""
        from django.core.management import call_command

        order = self.make_order(amount='1000.00', status=Order.Status.DELIVERED)
        order.deadline = timezone.now() - timezone.timedelta(days=5)
        order.paid_amount = Decimal('0')
        order.save(update_fields=['deadline', 'paid_amount'])

        call_command('notify_overdue_debts')
        self.assertGreater(
            Notification.objects.filter(
                type=Notification.NotificationType.OVERDUE_DEBT, related_order=order,
            ).count(),
            0,
        )

    def test_cancelled_order_never_overdue(self):
        from django.core.management import call_command

        order = self.make_order(amount='1000.00', status=Order.Status.CANCELLED)
        order.deadline = timezone.now() - timezone.timedelta(days=5)
        order.paid_amount = Decimal('0')
        order.save(update_fields=['deadline', 'paid_amount'])

        call_command('notify_overdue_debts')
        self.assertEqual(
            Notification.objects.filter(
                type=Notification.NotificationType.OVERDUE_DEBT, related_order=order,
            ).count(),
            0,
        )


@tag('postgres')
class ExportTenantBoundaryTests(DeepRaceMixin, TransactionTestCase):
    """Выгрузка владельца содержит только его компанию."""

    def test_owner_export_excludes_other_company(self):
        other = Company.objects.create(name='ForeignExportCo')
        other_client = Client.objects.create(company=other, name='Чужой клиент')
        RawMaterial.objects.create(
            company=other, name='Чужой мрамор', unit='m2', quantity=Decimal('99'),
        )
        Order.objects.create(
            company=other, client=other_client, custom_product_name='Чужой заказ',
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('98765.43'),
            deadline=timezone.now() + timezone.timedelta(days=1),
        )

        api = self.api_as(self.owner)
        for endpoint in ('/api/v1/reports/export/stock/?format=csv',
                         '/api/v1/reports/export/orders/?format=csv',
                         '/api/v1/reports/export/finance/?format=csv'):
            body = api.get(endpoint).content.decode('utf-8')
            self.assertNotIn('Чужой', body, f'{endpoint}: попали данные другой компании')
            self.assertNotIn('98765', body.replace(' ', ''), f'{endpoint}: чужая сумма')


@tag('postgres')
class MoneyRoundingTests(DeepRaceMixin, TransactionTestCase):
    """Округление денег на numeric: копейки не должны исчезать или размножаться."""

    def test_labor_cost_rounds_to_two_decimals(self):
        """
        Дробное количество × ставка = сумма с двумя знаками.

        0.333 × 150.55 = 50.13315 -> в БД numeric(15,2), нужна корректная
        квантизация, а не обрезка на уровне драйвера.
        """
        LaborRate.objects.create(
            company=self.company, product=self.product,
            operation=LaborRate.OperationType.POLISHING,
            rate_per_unit=Decimal('150.55'), unit='sht',
        )
        task = Task.objects.create(
            company=self.company, worker=self.worker, assigned_by=self.owner,
            status=TaskStatus.ACCEPTED, title='Полировка',
        )
        work = WorkRecord.objects.create(
            company=self.company, task=task, worker=self.worker, product=self.product,
            quantity=Decimal('0.333'), unit='sht',
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION,
        )
        response = self.api_as(self.owner).post(
            f'/api/v1/production/works/{work.id}/confirm/', {}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

        work.refresh_from_db()
        self.assertEqual(work.labor_cost, Decimal('50.13'))
        self.assertEqual(work.labor_cost.as_tuple().exponent, -2,
                         'сумма должна храниться ровно с двумя знаками')

    def test_many_small_payments_sum_exactly(self):
        """Сто платежей по 0.01 дают ровно 1.00, без накопления погрешности."""
        order = self.make_order(amount='1.00')
        api = self.api_as(self.owner)
        for _ in range(100):
            response = api.post('/api/v1/clients/payments/', {
                'client': self.client_obj.id, 'order': order.id,
                'amount': '0.01', 'payment_date': timezone.now().isoformat(),
            }, format='json')
            self.assertEqual(response.status_code, 201, response.data)

        order.refresh_from_db()
        self.client_obj.refresh_from_db()
        self.assertEqual(order.paid_amount, Decimal('1.00'))
        self.assertEqual(self.client_obj.debt, Decimal('0.00'))
