"""
Работы в карточке заказа (фильтр ?order= по связи через задачу).

Баг 12/13: владелец не видел, кто и что сделал по заказу. Теперь карточка
заказа показывает работы по нему (product, quantity, статус, кто подтвердил).
Фильтр ?order= — обратная сторона: API должен отдавать только работы
запрошенного заказа, работник — только свои.
"""
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.orders.models import Order
from apps.production.models import Task, WorkRecord
from apps.warehouse.models import FinishedProduct


class OrderWorkFilterTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='WorkCo', is_active=True)
        self.owner = User.objects.create_user(username='wf_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker1 = User.objects.create_user(username='wf_worker1', password='p',
                                                role=User.Role.WORKER, company=self.company)
        self.worker2 = User.objects.create_user(username='wf_worker2', password='p',
                                                role=User.Role.WORKER, company=self.company)
        self.crm_client = Client.objects.create(company=self.company, name='Алишер',
                                                phone='+998901234567')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Платье', quantity=Decimal('0'), unit='dona')
        self.order1 = Order.objects.create(
            company=self.company, client=self.crm_client, product=self.product,
            quantity=Decimal('2'), unit='dona', total_amount=Decimal('200000'))
        self.order2 = Order.objects.create(
            company=self.company, client=self.crm_client, product=self.product,
            quantity=Decimal('1'), unit='dona', total_amount=Decimal('100000'))

    def _work(self, order, worker, quantity='1'):
        task = Task.objects.create(company=self.company, order=order, worker=worker,
                                   assigned_by=self.owner)
        return WorkRecord.objects.create(
            company=self.company, task=task, worker=worker, product=self.product,
            quantity=Decimal(quantity), unit='dona')

    def test_filter_returns_only_order_works(self):
        """?order=N отдаёт только работы заказа N, не соседнего."""
        w1 = self._work(self.order1, self.worker1, '2')
        w1.status = WorkRecord.WorkStatus.CONFIRMED
        w1.save()
        self._work(self.order2, self.worker2, '1')

        self.client.force_login(self.owner)
        resp = self.client.get(f'/api/v1/production/works/?order={self.order1.id}')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        works = body['results']
        self.assertEqual(body['count'], 1)
        self.assertEqual(len(works), 1)
        self.assertEqual(works[0]['id'], w1.id)
        self.assertEqual(works[0]['product_name'], 'Платье')
        self.assertEqual(works[0]['quantity'], '2.000')

    def test_worker_sees_only_own_works_in_order(self):
        """Работник по чужой работе заказа её не видит даже с фильтром."""
        self._work(self.order1, self.worker1, '2')
        self._work(self.order1, self.worker2, '1')

        self.client.force_login(self.worker2)
        resp = self.client.get(f'/api/v1/production/works/?order={self.order1.id}')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['count'], 1)
        self.assertEqual(body['results'][0]['worker_name'], 'wf_worker2')

    def test_empty_order_returns_empty_list(self):
        """Заказ без работ — пустой список, а не ошибка."""
        self.client.force_login(self.owner)
        resp = self.client.get(f'/api/v1/production/works/?order={self.order2.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['count'], 0)
