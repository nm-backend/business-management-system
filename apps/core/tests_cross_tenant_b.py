"""
Этап B — регрессия межтенантных записей через вложенные FK.

Аудит нашёл, что несколько write-эндпоинтов проверяли компанию не у всех
связанных объектов: можно было передать id объекта ЧУЖОЙ компании и записать
в него/через него. Проверяем, что теперь каждый такой вектор отклоняется, а
свои-компанийные операции по-прежнему работают.

Векторы:
  - Payment.order — оплата на заказ чужой компании (менялся paid_amount чужого заказа).
  - Order.worker/client/product — заказ на сотрудника/клиента/товар чужой компании (create и update).
  - RecipeItem.recipe/material на update — перепривязка строки к чужому рецепту/материалу.
  - WorkRecord.worker — owner записывает работу на сотрудника чужой компании.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.clients.models import Client
from apps.orders.models import Order
from apps.production.models import WorkRecord
from apps.warehouse.models import FinishedProduct, RawMaterial, Recipe, RecipeItem

# Срок ВСЕГДА в будущем: заказ с прошедшим сроком отклоняется валидацией (400)
# ещё до проверки прав, и тест переставал проверять межтенантный отказ (403).
# Фиксированная дата в коде теста «протухала» с ходом времени.
FUTURE_DEADLINE = (timezone.now() + datetime.timedelta(days=30)).isoformat()


class _TwoCompanies(TestCase):
    def setUp(self):
        self.a = Company.objects.create(name='A')
        self.b = Company.objects.create(name='B')
        self.owner_a = User.objects.create_user(username='b_oa', password='p',
                                                 role=User.Role.OWNER, company=self.a)
        self.worker_a = User.objects.create_user(username='b_wa', password='p',
                                                  role=User.Role.WORKER, company=self.a)
        # Объекты компании B
        self.client_b = Client.objects.create(company=self.b, name='ClientB')
        self.product_b = FinishedProduct.objects.create(company=self.b, name='ProdB', quantity=Decimal('1'))
        self.material_b = RawMaterial.objects.create(company=self.b, name='MatB', quantity=Decimal('5'))
        self.worker_b = User.objects.create_user(username='b_wb', password='p',
                                                  role=User.Role.WORKER, company=self.b)
        self.order_b = Order.objects.create(
            company=self.b, client=self.client_b, product=self.product_b,
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('1000'),
            deadline=datetime.date(2026, 1, 1))
        # Объекты компании A
        self.client_a = Client.objects.create(company=self.a, name='ClientA')
        self.product_a = FinishedProduct.objects.create(company=self.a, name='ProdA', quantity=Decimal('1'))

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c


class PaymentCrossTenantTests(_TwoCompanies):
    def test_payment_on_foreign_order_rejected_and_untouched(self):
        # payment_date передаём валидным, чтобы отказ шёл именно от проверки
        # компании (403), а не от валидации обязательного поля (400).
        resp = self.api(self.owner_a).post('/api/v1/clients/payments/', {
            'client': self.client_a.id, 'order': self.order_b.id,
            'amount': '500', 'payment_method': 'cash',
            'payment_date': '2026-01-15T10:00:00Z',
        }, format='json')
        self.assertEqual(resp.status_code, 403)
        self.order_b.refresh_from_db()
        self.assertEqual(self.order_b.paid_amount, Decimal('0'))  # чужой заказ не тронут

    def test_payment_on_own_client_and_order_works(self):
        order_a = Order.objects.create(
            company=self.a, client=self.client_a, product=self.product_a,
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('1000'),
            deadline=datetime.date(2026, 1, 1))
        resp = self.api(self.owner_a).post('/api/v1/clients/payments/', {
            'client': self.client_a.id, 'order': order_a.id,
            'amount': '500', 'payment_method': 'cash',
            'payment_date': '2026-01-15T10:00:00Z',
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        order_a.refresh_from_db()
        self.assertEqual(order_a.paid_amount, Decimal('500'))


class OrderCrossTenantTests(_TwoCompanies):
    def test_create_order_with_foreign_worker_rejected(self):
        resp = self.api(self.owner_a).post('/api/v1/orders/orders/', {
            'client': self.client_a.id, 'product': self.product_a.id,
            'quantity': '1', 'unit': 'sht', 'worker': self.worker_b.id,
            'deadline': FUTURE_DEADLINE,
        }, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_create_order_with_foreign_client_rejected(self):
        resp = self.api(self.owner_a).post('/api/v1/orders/orders/', {
            'client': self.client_b.id, 'product': self.product_a.id,
            'quantity': '1', 'unit': 'sht', 'deadline': FUTURE_DEADLINE,
        }, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_update_order_to_foreign_worker_rejected(self):
        order_a = Order.objects.create(
            company=self.a, client=self.client_a, product=self.product_a,
            quantity=Decimal('1'), unit='sht', deadline=datetime.date(2026, 1, 1))
        resp = self.api(self.owner_a).patch(
            f'/api/v1/orders/orders/{order_a.id}/', {'worker': self.worker_b.id}, format='json')
        self.assertEqual(resp.status_code, 403)
        order_a.refresh_from_db()
        self.assertIsNone(order_a.worker_id)

    def test_create_own_order_works(self):
        resp = self.api(self.owner_a).post('/api/v1/orders/orders/', {
            'client': self.client_a.id, 'product': self.product_a.id,
            'quantity': '1', 'unit': 'sht', 'worker': self.worker_a.id,
            'deadline': FUTURE_DEADLINE,
        }, format='json')
        self.assertEqual(resp.status_code, 201)


class RecipeItemCrossTenantTests(_TwoCompanies):
    def test_update_recipe_item_to_foreign_material_rejected(self):
        # Своя строка рецепта в компании A
        prod_a = self.product_a
        recipe_a = Recipe.objects.create(company=self.a, product=prod_a, name='RA', is_active=True)
        mat_a = RawMaterial.objects.create(company=self.a, name='MatA', quantity=Decimal('5'))
        item = RecipeItem.objects.create(recipe=recipe_a, material=mat_a,
                                         quantity_required=Decimal('1'), unit='sht')
        resp = self.api(self.owner_a).patch(
            f'/api/v1/warehouse/recipe-items/{item.id}/',
            {'material': self.material_b.id}, format='json')
        self.assertEqual(resp.status_code, 403)
        item.refresh_from_db()
        self.assertEqual(item.material_id, mat_a.id)  # не перепривязано


class WorkRecordCrossTenantTests(_TwoCompanies):
    def test_owner_cannot_record_work_for_foreign_worker(self):
        resp = self.api(self.owner_a).post('/api/v1/production/works/', {
            'product': self.product_a.id, 'quantity': '1', 'unit': 'sht',
            'worker': self.worker_b.id,
        }, format='json')
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(WorkRecord.objects.filter(worker=self.worker_b).exists())
