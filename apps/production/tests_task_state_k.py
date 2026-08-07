"""
Задача: гварды жизненного цикла (задача не воскрешает закрытые заказы,
cancel/refuse принимаются только в активных стадиях).

Воспроизведено до правки:
1. Задача по ВЫДАННОМУ/ОТМЕНЁННОМУ заказу создавалась и молча переводила
   его обратно в sent_to_worker — «воскрешала» закрытую сделку (товар уже
   списан при выдаче, резервы сняты при отмене).
2. cancel сданной задачи (работа на подтверждении) «убивал» задачу, а
   заказ зависал в awaiting_confirmation; затем confirm_work молча
   воскрешал задачу из CANCELLED обратно в CONFIRMED.
3. cancel задачи оставлял заказ в sent_to_worker без задачи — из этого
   статуса обратного перехода нет, заказ застревал.
4. refuse принимался повторно у отказанной задачи (владелец вернул заказ
   в new — повторный отказ снова отбросил его в worker_refused) и у
   сданной задачи (работа висит, а заказ откатился).
5. Работник создавал задачу с привязкой к заказу и сдачей работы двигал
   неназначенный заказ (order.worker пуст) к READY.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.orders.models import Order
from apps.production.models import Task, TaskStatus
from apps.warehouse.models import FinishedProduct, RawMaterial

WORKS = '/api/v1/production/works/'
TASKS = '/api/v1/production/tasks/'
ORDERS = '/api/v1/orders/orders/'


class _Base(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='TaskA', is_active=True)
        self.owner = User.objects.create_user(username='task_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='task_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.material = RawMaterial.objects.create(company=self.company, name='Мрамор',
                                                   stone_type='мрамор', unit='m2', quantity=100)
        self.product = FinishedProduct.objects.create(company=self.company, name='Столешница',
                                                      unit='dona', quantity=10)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        resp = self.api.post('/api/v1/warehouse/recipes/', {
            'product': self.product.id, 'name': 'R1', 'is_active': True,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        resp = self.api.post('/api/v1/warehouse/recipe-items/', {
            'recipe': resp.data['id'], 'material': self.material.id,
            'quantity_required': 1, 'unit': 'm2',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        resp = self.api.post('/api/v1/finance/labor-rates/', {
            'product': self.product.id, 'operation': 'cutting',
            'rate_per_unit': '1000', 'unit': 'dona',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.worker_api = APIClient()
        self.worker_api.force_authenticate(self.worker)

    def _order(self, quantity=1):
        from apps.clients.models import Client
        client = Client.objects.create(company=self.company, name='Клиент')
        resp = self.api.post(ORDERS, {
            'client': client.id, 'product': self.product.id,
            'quantity': str(quantity), 'unit': 'dona', 'total_amount': '100000',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.json()['id']

    def _task(self, order_id):
        resp = self.api.post(TASKS, {'order': order_id, 'worker': self.worker.id}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.json()['id']

    def _submitted_work(self, task_id):
        resp = self.worker_api.post(f'{TASKS}{task_id}/accept/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        resp = self.worker_api.post(WORKS, {
            'task': task_id, 'product': self.product.id, 'operation': 'cutting',
            'quantity': '1', 'unit': 'dona',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.json()['id']


class ZombieOrderTaskTests(_Base):
    def test_task_for_delivered_order_rejected(self):
        order_id = self._order()
        resp = self.api.post(f'{ORDERS}{order_id}/deliver/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        resp = self.api.post(TASKS, {'order': order_id, 'worker': self.worker.id}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('order', resp.data)
        self.assertEqual(Order.objects.get(pk=order_id).status, Order.Status.DELIVERED)

    def test_task_for_cancelled_order_rejected(self):
        order_id = self._order()
        resp = self.api.post(f'{ORDERS}{order_id}/cancel/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        resp = self.api.post(TASKS, {'order': order_id, 'worker': self.worker.id}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(Order.objects.get(pk=order_id).status, Order.Status.CANCELLED)


class CancelTaskGuardTests(_Base):
    def test_cancel_submitted_task_rejected_and_confirm_still_works(self):
        order_id = self._order()
        task_id = self._task(order_id)
        work_id = self._submitted_work(task_id)
        self.assertEqual(Task.objects.get(pk=task_id).status, TaskStatus.COMPLETED)

        resp = self.api.post(f'{TASKS}{task_id}/cancel/', {}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(Task.objects.get(pk=task_id).status, TaskStatus.COMPLETED)

        resp = self.api.post(f'{WORKS}{work_id}/confirm/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        task = Task.objects.get(pk=task_id)
        self.assertEqual(task.status, TaskStatus.CONFIRMED)
        self.assertEqual(task.order.status, Order.Status.READY)

    def test_cancel_finished_task_rejected(self):
        """CONFIRMED/REFUSED/REJECTED — история, отмене не подлежит."""
        order_id = self._order()
        task_id = self._task(order_id)
        resp = self.worker_api.post(f'{TASKS}{task_id}/refuse/', {'reason': 'no_time'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        resp = self.api.post(f'{TASKS}{task_id}/cancel/', {}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(Task.objects.get(pk=task_id).status, TaskStatus.REFUSED)

    def test_cancel_pending_task_returns_order_to_queue(self):
        order_id = self._order()
        task_id = self._task(order_id)
        order = Order.objects.get(pk=order_id)
        self.assertEqual(order.status, Order.Status.SENT_TO_WORKER)
        self.assertEqual(order.worker_id, self.worker.id)

        resp = self.api.post(f'{TASKS}{task_id}/cancel/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.NEW, 'заказ возвращается в очередь')
        self.assertIsNone(order.worker_id, 'исполнитель снимается')


class RefuseTaskGuardTests(_Base):
    def test_double_refuse_rejected(self):
        order_id = self._order()
        task_id = self._task(order_id)
        resp = self.worker_api.post(f'{TASKS}{task_id}/refuse/', {'reason': 'no_time'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        resp = self.api.patch(f'{ORDERS}{order_id}/transition/', {'status': 'new'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(Order.objects.get(pk=order_id).status, Order.Status.NEW)

        resp = self.worker_api.post(f'{TASKS}{task_id}/refuse/', {'reason': 'no_time'}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(Order.objects.get(pk=order_id).status, Order.Status.NEW,
                         'повторный отказ не откатывает заказ')

    def test_refuse_after_work_submitted_rejected(self):
        order_id = self._order()
        task_id = self._task(order_id)
        self._submitted_work(task_id)
        self.assertEqual(Order.objects.get(pk=order_id).status, Order.Status.AWAITING_CONFIRMATION)

        resp = self.worker_api.post(f'{TASKS}{task_id}/refuse/', {'reason': 'no_time'}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(Order.objects.get(pk=order_id).status, Order.Status.AWAITING_CONFIRMATION,
                         'сданная работа не откатывает заказ')


class WorkerSelfTaskTests(_Base):
    def test_worker_cannot_create_task_with_order(self):
        order_id = self._order()
        resp = self.worker_api.post(TASKS, {'order': order_id, 'worker': self.worker.id}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('order', resp.data)
        self.assertEqual(Order.objects.get(pk=order_id).status, Order.Status.NEW)
        self.assertIsNone(Order.objects.get(pk=order_id).worker_id)

    def test_worker_self_task_without_order_ok(self):
        resp = self.worker_api.post(TASKS, {'worker': self.worker.id}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        task = Task.objects.get(pk=resp.json()['id'])
        self.assertTrue(task.is_self_assigned)
        self.assertEqual(task.status, TaskStatus.ACCEPTED)

    def test_owner_task_for_active_order_ok(self):
        order_id = self._order()
        resp = self.api.post(TASKS, {'order': order_id, 'worker': self.worker.id}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        order = Order.objects.get(pk=order_id)
        self.assertEqual(order.status, Order.Status.SENT_TO_WORKER)
        self.assertEqual(order.worker_id, self.worker.id)
