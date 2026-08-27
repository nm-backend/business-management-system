"""
Финальная перепроверка аудита (этап 8): работник не может привязать работу
к чужой задаче; выдача заказа при нехватке товара возвращает резерв сырья;
готовый товар не принимает отрицательные стартовые остатки.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.orders.models import Order
from apps.production.models import Task, TaskStatus, WorkRecord
from apps.warehouse.models import FinishedProduct, RawMaterial, Recipe, RecipeItem

WORKS = '/api/v1/production/works/'
PRODUCTS = '/api/v1/warehouse/finished-products/'


class WorkForeignTaskTests(TestCase):
    """Работа привязывается только к задаче своего исполнителя."""

    def setUp(self):
        self.company = Company.objects.create(name='WFT', is_active=True)
        self.owner = User.objects.create_user(username='wft_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker_a = User.objects.create_user(username='wft_a', password='p',
                                                 role=User.Role.WORKER, company=self.company)
        self.worker_b = User.objects.create_user(username='wft_b', password='p',
                                                 role=User.Role.WORKER, company=self.company)
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Изделие', quantity=Decimal('0'), unit='dona')
        self.client_obj = None

    def _order_and_task(self, worker):
        from apps.clients.models import Client
        if self.client_obj is None:
            self.client_obj = Client.objects.create(company=self.company, name='Клиент WFT')
        order = Order.objects.create(
            company=self.company, client=self.client_obj, product=self.product,
            quantity=Decimal('1'), status=Order.Status.SENT_TO_WORKER,
        )
        task = Task.objects.create(company=self.company, order=order, worker=worker)
        return order, task

    def test_worker_cannot_attach_work_to_foreign_task(self):
        _, task_b = self._order_and_task(self.worker_b)
        api = APIClient()
        api.force_authenticate(self.worker_a)
        resp = api.post(WORKS, {
            'product': self.product.id,
            'task': task_b.id,
            'quantity': 1,
            'unit': 'dona',
        }, format='json')
        self.assertIn(resp.status_code, (400, 403))
        # Задача B не тронута, работа не создана.
        task_b.refresh_from_db()
        self.assertEqual(task_b.status, TaskStatus.PENDING)
        self.assertFalse(WorkRecord.objects.filter(worker=self.worker_a).exists())

    def test_worker_can_attach_work_to_own_task(self):
        _, task_a = self._order_and_task(self.worker_a)
        api = APIClient()
        api.force_authenticate(self.worker_a)
        resp = api.post(WORKS, {
            'product': self.product.id,
            'task': task_a.id,
            'quantity': 1,
            'unit': 'dona',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        task_a.refresh_from_db()
        self.assertEqual(task_a.status, TaskStatus.COMPLETED)

    def test_owner_cannot_mix_task_and_worker(self):
        _, task_b = self._order_and_task(self.worker_b)
        api = APIClient()
        api.force_authenticate(self.owner)
        resp = api.post(WORKS, {
            'product': self.product.id,
            'task': task_b.id,
            'worker': self.worker_a.id,
            'quantity': 1,
            'unit': 'dona',
        }, format='json')
        self.assertIn(resp.status_code, (400, 403))


class DeliverRestoresRawMaterialReserveTests(TestCase):
    """При отказе выдачи (нехватка товара) резерв сырья возвращается."""

    def setUp(self):
        self.company = Company.objects.create(name='DRR', is_active=True)
        self.owner = User.objects.create_user(username='drr_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.material = RawMaterial.objects.create(
            company=self.company, name='Гранит', quantity=Decimal('10'), unit='m2')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('5'), unit='dona',
            required_for_orders=Decimal('0'))
        recipe = Recipe.objects.create(company=self.company, product=self.product, is_active=True)
        RecipeItem.objects.create(recipe=recipe, material=self.material,
                                  quantity_required=Decimal('2'), unit='m2')
        from apps.clients.models import Client
        self.client_obj = Client.objects.create(company=self.company, name='Клиент DRR')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _order(self):
        order = Order.objects.create(
            company=self.company, client=self.client_obj, product=self.product,
            quantity=Decimal('2'), status=Order.Status.READY,
        )
        order.apply_product_requirement()
        order.apply_raw_material_requirements()
        return order

    def test_reserve_restored_when_deliver_fails(self):
        order = self._order()
        self.material.refresh_from_db()
        self.product.refresh_from_db()
        material_reserved = self.material.required_for_orders
        product_reserved = self.product.required_for_orders
        self.assertGreater(material_reserved, 0)

        # Товар целиком недоступен: списываем остаток в ноль.
        self.product.quantity = Decimal('0')
        self.product.save()

        resp = self.api.post(f'/api/v1/orders/orders/{order.id}/deliver/')
        self.assertEqual(resp.status_code, 400)

        self.material.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.material.required_for_orders, material_reserved)
        self.assertEqual(self.product.required_for_orders, product_reserved)
        order.refresh_from_db()
        self.assertNotEqual(order.status, Order.Status.DELIVERED)


class FinishedProductNegativeQuantityTests(TestCase):
    """Готовый товар не принимает отрицательный стартовый остаток и min_stock."""

    def setUp(self):
        self.company = Company.objects.create(name='FPNQ', is_active=True)
        self.owner = User.objects.create_user(username='fpnq_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_negative_quantity_rejected(self):
        resp = self.api.post(PRODUCTS, {
            'name': 'Товар с минусом', 'quantity': '-5', 'unit': 'dona',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_negative_min_stock_rejected(self):
        resp = self.api.post(PRODUCTS, {
            'name': 'Товар', 'quantity': '5', 'min_stock': '-3', 'unit': 'dona',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_valid_product_still_created(self):
        resp = self.api.post(PRODUCTS, {
            'name': 'Товар', 'quantity': '5', 'min_stock': '2', 'unit': 'dona',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:300])
