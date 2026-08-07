"""
Расследование: тенант-изоляция работы, отказ подтверждённой задачи, товар работы.

Воспроизведено до правки:
1. PATCH работы перепривязывал product на товар ЧУЖОЙ компании — confirm_work
   списывал чужое сырьё и приходовал чужой склад.
2. refuse принимался у подтверждённой задачи: готовый заказ откатывался в
   worker_refused, хотя сырьё уже списано и товар приходован.
3. Работа по задаче с товаром ≠ товару заказа принималась и подтверждалась —
   «производился» не тот товар, заказ оставался без партии.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.orders.models import Order
from apps.production.models import Task, TaskStatus, WorkRecord
from apps.warehouse.models import FinishedProduct

WORKS = '/api/v1/production/works/'
TASKS = '/api/v1/production/tasks/'


class _Base(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(name='ProdA', is_active=True)
        self.company_b = Company.objects.create(name='ProdB', is_active=True)
        self.owner_a = User.objects.create_user(username='pa_owner', password='p',
                                                role=User.Role.OWNER, company=self.company_a)
        self.owner_b = User.objects.create_user(username='pb_owner', password='p',
                                                role=User.Role.OWNER, company=self.company_b)
        self.worker = User.objects.create_user(username='pa_worker', password='p',
                                               role=User.Role.WORKER, company=self.company_a)
        self.product_a = FinishedProduct.objects.create(
            company=self.company_a, name='Столешница A', quantity=Decimal('0'), unit='dona')
        self.product_b = FinishedProduct.objects.create(
            company=self.company_b, name='Изделие B', quantity=Decimal('0'), unit='dona')
        self.api = APIClient()
        self.api.force_authenticate(self.owner_a)
        resp = self.api.post('/api/v1/finance/labor-rates/', {
            'product': self.product_a.id, 'operation': 'cutting',
            'rate_per_unit': '1000', 'unit': 'dona',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.worker_api = APIClient()
        self.worker_api.force_authenticate(self.worker)

    def _order(self, product, quantity=1):
        from apps.clients.models import Client
        client = Client.objects.create(company=self.company_a, name='Клиент')
        resp = self.api.post('/api/v1/orders/orders/', {
            'client': client.id, 'product': product.id, 'quantity': str(quantity),
            'unit': 'dona', 'total_amount': '100000',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.json()['id']

    def _task(self, order_id):
        resp = self.api.post(TASKS, {'order': order_id, 'worker': self.worker.id}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.json()['id']

    def _accepted_work(self, task_id, product, quantity=1):
        resp = self.worker_api.post(f'{TASKS}{task_id}/accept/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        resp = self.worker_api.post(WORKS, {
            'task': task_id, 'product': product.id, 'operation': 'cutting',
            'quantity': str(quantity), 'unit': 'dona',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.json()['id']


class WorkProductIsolationTests(_Base):
    def test_patch_work_product_of_foreign_company_rejected(self):
        order_id = self._order(self.product_a)
        task_id = self._task(order_id)
        work_id = self._accepted_work(task_id, self.product_a)

        resp = self.api.patch(f'{WORKS}{work_id}/', {'product': self.product_b.id}, format='json')
        self.assertEqual(resp.status_code, 403, resp.data)
        # Никаких «сюрпризов» на чужом складе не было.
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_b.quantity, Decimal('0.000'))
        self.assertFalse(WorkRecord.objects.filter(pk=work_id, product=self.product_b).exists())

    def test_patch_work_comment_still_allowed(self):
        """Легитимная правка работы до подтверждения не ломается."""
        order_id = self._order(self.product_a)
        task_id = self._task(order_id)
        work_id = self._accepted_work(task_id, self.product_a)
        resp = self.api.patch(f'{WORKS}{work_id}/', {'comment': 'доработал кромку'},
                              format='json')
        self.assertEqual(resp.status_code, 200, resp.data)


class RefuseConfirmedTaskTests(_Base):
    def test_refuse_confirmed_task_rejected(self):
        order_id = self._order(self.product_a)
        task_id = self._task(order_id)
        work_id = self._accepted_work(task_id, self.product_a)
        resp = self.api.post(f'{WORKS}{work_id}/confirm/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        task = Task.objects.get(pk=task_id)
        self.assertEqual(task.status, TaskStatus.CONFIRMED)
        self.assertEqual(task.order.status, Order.Status.READY)

        resp = self.worker_api.post(f'{TASKS}{task_id}/refuse/', {'reason': 'no_time'}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.CONFIRMED)
        self.assertEqual(task.order.status, Order.Status.READY, 'готовый заказ не откатывается')


class WorkProductMustMatchOrderTests(_Base):
    def test_create_work_with_wrong_product_rejected(self):
        other = FinishedProduct.objects.create(company=self.company_a, name='Подоконник',
                                               quantity=Decimal('0'), unit='dona')
        order_id = self._order(self.product_a)
        task_id = self._task(order_id)
        self.worker_api.post(f'{TASKS}{task_id}/accept/', {}, format='json')
        resp = self.worker_api.post(WORKS, {
            'task': task_id, 'product': other.id, 'operation': 'cutting',
            'quantity': '1', 'unit': 'dona',
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('product', resp.data)

    def test_patch_work_to_wrong_product_rejected(self):
        other = FinishedProduct.objects.create(company=self.company_a, name='Подоконник',
                                               quantity=Decimal('0'), unit='dona')
        order_id = self._order(self.product_a)
        task_id = self._task(order_id)
        work_id = self._accepted_work(task_id, self.product_a)
        resp = self.api.patch(f'{WORKS}{work_id}/', {'product': other.id}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('product', resp.data)
