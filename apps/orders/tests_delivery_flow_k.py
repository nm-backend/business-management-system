"""
Сквозной путь «заказ → работник → готовая работа → выдача клиенту».

Жалоба с боевого использования: не получилось отправить готовую работу
заказчику. Кнопка «Выдать» в интерфейсе появляется ТОЛЬКО когда заказ в статусе
ready (static/js/components/orders.js), поэтому любой обрыв цепочки статусов
раньше этого места делает выдачу невозможной. Этот тест проходит весь путь
ролями через API и показывает, где именно он рвётся.

Цепочка по коду:
  owner отправляет заказ работнику  -> создаётся Task, заказ sent_to_worker
  работник принимает задачу          -> Task.accept()   -> заказ accepted
  работник сдаёт работу (WorkRecord) -> Task.complete() -> заказ awaiting_confirmation
  owner подтверждает работу          -> Task.confirm()  -> заказ ready
  owner выдаёт заказ                 -> deliver         -> заказ delivered
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.orders.models import Order
from apps.production.models import Task, WorkRecord
from apps.warehouse.models import FinishedProduct


class OrderDeliveryFlowTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='FlowCo', is_active=True)
        self.owner = User.objects.create_user(username='flow_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='flow_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Заказчик')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('0'),
            cost_price=Decimal('1000'))
        self.order = Order.objects.create(
            company=self.company, client=self.client_obj, product=self.product,
            quantity=Decimal('2'), unit='dona', total_amount=Decimal('5000'),
            deadline=datetime.datetime(2026, 12, 1, tzinfo=datetime.timezone.utc))

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_full_flow_reaches_delivered(self):
        owner, worker = self.api(self.owner), self.api(self.worker)

        # 1. Владелец отправляет заказ работнику (создаётся задача).
        resp = owner.post('/api/v1/production/tasks/',
                          {'order': self.order.id, 'worker': self.worker.id}, format='json')
        self.assertIn(resp.status_code, (200, 201), f'создание задачи: {resp.status_code} {resp.content[:300]}')
        task_id = resp.json()['id']
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.SENT_TO_WORKER)

        # 2. Работник принимает задачу.
        resp = worker.post(f'/api/v1/production/tasks/{task_id}/accept/')
        self.assertEqual(resp.status_code, 200, f'принятие задачи: {resp.content[:300]}')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.ACCEPTED)

        # 3. Работник сдаёт выполненную работу.
        resp = worker.post('/api/v1/production/works/', {
            'task': task_id, 'product': self.product.id,
            'quantity': '2', 'unit': 'dona',
        }, format='json')
        self.assertIn(resp.status_code, (200, 201), f'сдача работы: {resp.status_code} {resp.content[:300]}')
        work_id = resp.json()['id']
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.AWAITING_CONFIRMATION,
                         'после сдачи работы заказ должен ждать подтверждения')

        # 4. Владелец подтверждает работу — заказ становится готовым.
        resp = owner.post(f'/api/v1/production/works/{work_id}/confirm/', {}, format='json')
        self.assertEqual(resp.status_code, 200, f'подтверждение работы: {resp.content[:300]}')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.READY,
                         'подтверждённая работа обязана переводить заказ в «Готов» — '
                         'иначе кнопка «Выдать» не появляется и работу нельзя отдать клиенту')

        # 5. Владелец выдаёт заказ клиенту.
        resp = owner.post(f'/api/v1/orders/orders/{self.order.id}/deliver/')
        self.assertEqual(resp.status_code, 200, f'выдача: {resp.content[:300]}')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.DELIVERED)
        self.assertIsNotNone(self.order.delivered_at)

    def test_work_without_task_still_lets_owner_deliver(self):
        """
        Работу можно сдать и без задачи (прямая запись). Тогда статус заказа сам
        не двигается — владелец обязан иметь возможность выдать заказ вручную.
        """
        owner = self.api(self.owner)
        WorkRecord.objects.create(
            company=self.company, worker=self.worker, product=self.product,
            quantity=Decimal('1'), unit='dona')
        resp = owner.post(f'/api/v1/orders/orders/{self.order.id}/deliver/')
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.DELIVERED)

    def test_worker_cannot_deliver(self):
        resp = self.api(self.worker).post(f'/api/v1/orders/orders/{self.order.id}/deliver/')
        self.assertEqual(resp.status_code, 403)
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.status, Order.Status.DELIVERED)


class DeliverButtonContractTests(TestCase):
    """
    Интерфейс не должен прятать выдачу там, где API её разрешает.

    Кнопка «Выдать» показывалась только при статусе ready. Заказ, который не
    проходил через задачу и подтверждение работы (например, товар уже был на
    складе), в статусе ready никогда не оказывался — и отдать его клиенту из
    интерфейса было нельзя, хотя API это позволяет.
    """
    def setUp(self):
        self.company = Company.objects.create(name='BtnCo', is_active=True)
        self.owner = User.objects.create_user(username='btn_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.cli = Client.objects.create(company=self.company, name='К')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='П', quantity=Decimal('5'))

    def _order(self, status):
        return Order.objects.create(
            company=self.company, client=self.cli, product=self.product,
            quantity=Decimal('1'), unit='dona', total_amount=Decimal('100'), status=status)

    def test_api_allows_delivery_from_every_non_terminal_status(self):
        c = APIClient()
        c.force_authenticate(self.owner)
        for st in (Order.Status.NEW, Order.Status.AWAITING_MATERIAL,
                   Order.Status.SENT_TO_WORKER, Order.Status.ACCEPTED,
                   Order.Status.IN_PROGRESS, Order.Status.AWAITING_CONFIRMATION,
                   Order.Status.READY):
            order = self._order(st)
            resp = c.post(f'/api/v1/orders/orders/{order.id}/deliver/')
            self.assertEqual(resp.status_code, 200, f'{st}: {resp.content[:200]}')
            order.refresh_from_db()
            self.assertEqual(order.status, Order.Status.DELIVERED)

    def test_cancelled_order_cannot_be_delivered(self):
        c = APIClient()
        c.force_authenticate(self.owner)
        order = self._order(Order.Status.CANCELLED)
        resp = c.post(f'/api/v1/orders/orders/{order.id}/deliver/')
        self.assertEqual(resp.status_code, 400)

    def test_ui_shows_deliver_button_for_every_non_terminal_status(self):
        """Условие показа кнопки в orders.js должно совпадать с контрактом API."""
        from pathlib import Path

        from django.conf import settings

        js = (Path(settings.STATICFILES_DIRS[0]) / 'js' / 'components' / 'orders.js').read_text(encoding='utf-8')
        anchor = js.index('id="deliver-order"')
        condition = js[js.rindex('${', 0, anchor):anchor]
        self.assertIn("!['delivered', 'cancelled'].includes(o.status)", condition)
        self.assertNotIn("o.status === 'ready'", condition)
