"""
Гонки при выдаче и отмене заказа (полный аудит).

ПОДТВЕРЖДЁННЫЕ ГОНКИ: deliver и cancel не блокировали строку заказа.

1. Два параллельных deliver заказа в статусе ready оба проходили проверку
   «заказ ещё не выдан» и каждый списывал товар через record_outgoing —
   остаток падал вдвое, в журнале появлялись две записи «Выдача заказа №…».

2. Два параллельных cancel выданного заказа оба видели DELIVERED и каждый
   приходовал товар через record_incoming — остаток завышался вдвое.

Исправлено: transaction.atomic + select_for_update на строке заказа,
статус перепроверяется под блокировкой.

ВАЖНО: тесты требуют PostgreSQL (как apps/core/tests_race.py). На SQLite
select_for_update не блокирует, и конкуренция не воспроизводится — тесты
пропускаются.
"""
import threading
from decimal import Decimal

from django.db import connection, connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct, StockMovement

IS_POSTGRES = connection.vendor == 'postgresql'
ORDERS = '/api/v1/orders/orders/'


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
class OrderDeliveryCancelRaceTests(TransactionTestCase):
    reset_sequences = False

    def setUp(self):
        if not IS_POSTGRES:
            self.skipTest('Конкуренция проверяется только на PostgreSQL')
        self.company = Company.objects.create(name='RaceOrders', is_active=True)
        self.owner = User.objects.create_user(username='ro_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('10'), unit='dona')

    def _create_order(self):
        api = APIClient()
        api.force_authenticate(self.owner)
        resp = api.post(ORDERS, {
            'client': self.client_obj.id, 'product': self.product.id,
            'quantity': '3', 'unit': 'dona', 'total_amount': '1000',
            'deadline': '2026-12-31T00:00:00Z',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        return resp.json()['id']

    def _call(self, order_id, action):
        api = APIClient()
        api.force_authenticate(self.owner)
        return api.post(f'{ORDERS}{order_id}/{action}/').status_code

    def test_concurrent_deliver_deducts_stock_once(self):
        """6 параллельных выдач: списание и запись в журнал ровно один раз."""
        order_id = self._create_order()
        results = run_parallel(lambda i: self._call(order_id, 'deliver'), n=6)

        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('7.000'),
                         'ГОНКА: товар списан больше одного раза')
        movements = StockMovement.objects.filter(
            product=self.product,
            movement_type=StockMovement.MovementType.OUTGOING,
            reason__icontains=f'#{order_id}')
        self.assertEqual(movements.count(), 1,
                         'ГОНКА: в журнале больше одной записи о выдаче')
        order = Order.objects.get(pk=order_id)
        self.assertEqual(order.status, Order.Status.DELIVERED)
        self.assertEqual(sum(1 for r in results if r == 200), 1,
                         f'успешной должна быть ровно одна выдача, было: {results}')

    def test_concurrent_cancel_of_delivered_returns_stock_once(self):
        """6 параллельных отмен выданного заказа: возврат товара ровно один раз."""
        order_id = self._create_order()
        self.assertEqual(self._call(order_id, 'deliver'), 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('7.000'))

        results = run_parallel(lambda i: self._call(order_id, 'cancel'), n=6)

        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('10.000'),
                         'ГОНКА: товар возвращён больше одного раза')
        movements = StockMovement.objects.filter(
            product=self.product,
            movement_type=StockMovement.MovementType.INCOMING,
            reason__icontains=f'#{order_id}')
        self.assertEqual(movements.count(), 1,
                         'ГОНКА: в журнале больше одной записи о возврате')
        self.assertEqual(Order.objects.get(pk=order_id).status, Order.Status.CANCELLED)
