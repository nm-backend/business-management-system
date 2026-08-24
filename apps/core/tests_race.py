"""
Регрессионные тесты состояний гонки (ЭТАП 4).

ПОДТВЕРЖДЁННАЯ ГОНКА (исправлена): issue_access_key без транзакции и блокировки
давал ДО 3 одновременно активных Access Key (16 потоков, 6 повторов). Два
процесса успевали отозвать «всё активное» (каждый видел пустой набор) и затем
оба вставляли новый ключ. Исправлено: @transaction.atomic + select_for_update
на строке сотрудника.

ВАЖНО: тесты требуют PostgreSQL. На SQLite select_for_update не блокирует, и
конкуренция не воспроизводится — поэтому тесты пропускаются.
"""
import threading
from decimal import Decimal

from django.db import connection, connections
from django.test import TransactionTestCase, skipUnlessDBFeature

from apps.accounts.access_keys import issue_access_key, redeem_access_key
from apps.accounts.models import AccessKey, User
from apps.companies.models import Company

IS_POSTGRES = connection.vendor == 'postgresql'


def run_parallel(fn, n=8):
    """Запускает fn в n потоках со стартом по барьеру."""
    results, lock, barrier = [], threading.Lock(), threading.Barrier(n)

    def worker(i):
        try:
            barrier.wait()
            r = fn(i)
        except Exception as e:
            r = f'EXC:{type(e).__name__}'
        finally:
            connections.close_all()
        with lock:
            results.append(r)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return results


@skipUnlessDBFeature('has_select_for_update')
class AccessKeyRaceTests(TransactionTestCase):
    reset_sequences = False

    def setUp(self):
        if not IS_POSTGRES:
            self.skipTest('Конкуренция проверяется только на PostgreSQL')
        self.company = Company.objects.create(name='RaceCo')
        self.owner = User.objects.create_user(username='race_o', password='p',
                                              role=User.Role.OWNER, company=self.company)
        # Ключи выдаются только приглашённым (без рабочего пароля). Созданный
        # с паролем worker вызывал ValueError в issue_access_key, и оба теста
        # этого класса падали на PostgreSQL (на SQLite они пропускаются).
        self.worker = User.objects.create_user(
            username='race_w', role=User.Role.WORKER, company=self.company,
        )
        self.worker.set_unusable_password()
        self.worker.save()

    def test_only_one_active_key_under_concurrent_issue(self):
        """РЕГРЕССИЯ подтверждённой гонки: 16 потоков -> ровно 1 активный ключ."""
        run_parallel(lambda i: issue_access_key(user=self.worker, created_by=self.owner).pk, n=16)
        active = AccessKey.objects.filter(user=self.worker, status=AccessKey.Status.ACTIVE).count()
        self.assertEqual(active, 1, f'ГОНКА: одновременно активно {active} ключей')

    def test_key_can_be_redeemed_only_once_concurrently(self):
        """Одноразовость под конкуренцией: активация проходит ровно один раз."""
        code = issue_access_key(user=self.worker, created_by=self.owner).key
        res = run_parallel(
            lambda i: redeem_access_key(code=code, new_password=f'Str0ng!Pass{i}9')[0] is not None,
            n=8,
        )
        self.assertEqual(sum(1 for r in res if r is True), 1)
        self.assertEqual(AccessKey.objects.filter(key=code, status=AccessKey.Status.USED).count(), 1)


@skipUnlessDBFeature('has_select_for_update')
class WarehouseRaceTests(TransactionTestCase):
    reset_sequences = False

    def setUp(self):
        if not IS_POSTGRES:
            self.skipTest('Конкуренция проверяется только на PostgreSQL')
        self.company = Company.objects.create(name='RaceWh')
        self.owner = User.objects.create_user(username='rw_o', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='rw_w', password='p',
                                               role=User.Role.WORKER, company=self.company)

    def test_confirm_work_deducts_stock_exactly_once(self):
        """Подтверждение одной работы 6 потоками не должно списать материал дважды."""
        from apps.production.models import WorkRecord
        from apps.production.services import confirm_work
        from apps.warehouse.models import FinishedProduct, RawMaterial, Recipe, RecipeItem

        product = FinishedProduct.objects.create(company=self.company, name='P', quantity=Decimal('0'))
        # Подтверждение требует ставки: без неё оно отказывает, чтобы
        # работнику не начислялся молча ноль. Тест про гонку, а не про оплату.
        from apps.finance.models import LaborRate
        LaborRate.objects.create(company=self.company, product=product,
                                 operation=LaborRate.OperationType.OTHER,
                                 rate_per_unit=Decimal('100'), unit=product.unit)
        material = RawMaterial.objects.create(company=self.company, name='M', quantity=Decimal('10'))
        recipe = Recipe.objects.create(company=self.company, product=product, name='R')
        RecipeItem.objects.create(recipe=recipe, material=material, quantity_required=Decimal('2'))
        work = WorkRecord.objects.create(company=self.company, worker=self.worker,
                                         product=product, quantity=Decimal('1'))

        run_parallel(lambda i: confirm_work(work, self.owner) and True, n=6)

        material.refresh_from_db()
        product.refresh_from_db()
        self.assertEqual(material.quantity, Decimal('8.000'), 'двойное списание материала')
        self.assertEqual(product.quantity, Decimal('1.000'), 'двойное оприходование продукции')

    def test_general_conversation_created_once(self):
        """Одновременные обращения не должны создать два общих чата компании."""
        from apps.messaging.models import Conversation
        from apps.messaging.services import ensure_general_conversation

        run_parallel(lambda i: ensure_general_conversation(self.company).pk, n=8)
        self.assertEqual(
            Conversation.objects.filter(company=self.company, kind='general').count(), 1)


@skipUnlessDBFeature('has_select_for_update')
class PaymentRaceTests(TransactionTestCase):
    """Гонка потери обновления при одновременных оплатах одного заказа."""
    reset_sequences = False

    def setUp(self):
        if not IS_POSTGRES:
            self.skipTest('Конкуренция проверяется только на PostgreSQL')
        import datetime
        from apps.clients.models import Client
        from apps.orders.models import Order
        from apps.warehouse.models import FinishedProduct

        self.company = Company.objects.create(name='RacePay')
        self.owner = User.objects.create_user(username='rp_o', password='p',
                                              role=User.Role.OWNER, company=self.company)
        client = Client.objects.create(company=self.company, name='C')
        product = FinishedProduct.objects.create(company=self.company, name='P',
                                                 quantity=Decimal('1'))
        self.order = Order.objects.create(
            company=self.company, client=client, product=product, quantity=Decimal('1'),
            unit='sht', total_amount=Decimal('100'), deadline=datetime.date(2026, 1, 1))

        # Подтверждение работы требует заданной ставки: без неё оно
        # отказывает, чтобы работнику не начислялся молча ноль.
        from apps.finance.models import LaborRate
        for _p in FinishedProduct.objects.filter(company=self.company):
            LaborRate.objects.get_or_create(
                company=self.company, product=_p,
                operation=LaborRate.OperationType.OTHER,
                defaults={'rate_per_unit': Decimal('100'), 'unit': _p.unit})
    def test_concurrent_payments_are_not_lost(self):
        """16 одновременных оплат по 1 -> paid_amount ровно 16 (без потери)."""
        from apps.orders.models import Order
        pk = self.order.pk
        run_parallel(
            lambda i: (Order.objects.get(pk=pk).apply_payment_amount(Decimal('1')), True)[1],
            n=16,
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal('16.00'),
                         f'ПОТЕРЯ ОБНОВЛЕНИЯ: paid_amount={self.order.paid_amount}, ожидалось 16')
