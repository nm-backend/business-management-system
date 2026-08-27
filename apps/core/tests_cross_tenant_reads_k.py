"""
Межтенантные READ-векторы и mass assignment (этап K, доп. покрытие).

Проверяем, что токен компании A не видит данные компании B по всем доменам
(GET), и что серверные/производные поля нельзя подменить через API.
Векторы записи (Payment.order, Order.worker/client/product, RecipeItem,
WorkRecord.worker) уже покрыты tests_cross_tenant_b.py.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.audit.services import write_audit_log
from apps.clients.models import Client, Payment
from apps.companies.models import Company
from apps.finance.models import Expense, ExpenseCategory
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct, RawMaterial


class _TwoCompanies(TestCase):
    def setUp(self):
        self.a = Company.objects.create(name='ReadA')
        self.b = Company.objects.create(name='ReadB')
        self.owner_a = User.objects.create_user(username='ra_owner', password='p',
                                                role=User.Role.OWNER, company=self.a)
        self.owner_b = User.objects.create_user(username='rb_owner', password='p',
                                                role=User.Role.OWNER, company=self.b)

        # Данные компании A.
        self.client_a = Client.objects.create(company=self.a, name='Клиент A')
        self.product_a = FinishedProduct.objects.create(
            company=self.a, name='Товар A', quantity=Decimal('1'), unit='dona')
        self.material_a = RawMaterial.objects.create(
            company=self.a, name='Сырьё A', quantity=Decimal('1'), unit='m2')
        self.order_a = Order.objects.create(
            company=self.a, client=self.client_a, product=self.product_a,
            quantity=Decimal('1'), unit='dona', total_amount=Decimal('100'),
            deadline=timezone.now() + datetime.timedelta(days=3))
        Payment.objects.create(company=self.a, client=self.client_a, order=self.order_a,
                               amount=Decimal('40'), payment_method='cash',
                               payment_date=timezone.now())
        Expense.objects.create(company=self.a, category=ExpenseCategory.RENT,
                               amount=Decimal('10'), date=timezone.localdate())
        write_audit_log(action=AuditLog.Action.CREATE, actor=self.owner_a,
                        target=self.client_a)

        # Данные компании B.
        self.client_b = Client.objects.create(company=self.b, name='Клиент B')
        self.product_b = FinishedProduct.objects.create(
            company=self.b, name='Товар B', quantity=Decimal('1'), unit='dona')
        self.material_b = RawMaterial.objects.create(
            company=self.b, name='Сырьё B', quantity=Decimal('1'), unit='m2')
        self.order_b = Order.objects.create(
            company=self.b, client=self.client_b, product=self.product_b,
            quantity=Decimal('1'), unit='dona', total_amount=Decimal('999'),
            deadline=timezone.now() + datetime.timedelta(days=3))
        Payment.objects.create(company=self.b, client=self.client_b, order=self.order_b,
                               amount=Decimal('999'), payment_method='cash',
                               payment_date=timezone.now())
        write_audit_log(action=AuditLog.Action.CREATE, actor=self.owner_b,
                        target=self.client_b)

        self.api = APIClient()
        self.api.force_authenticate(self.owner_a)


class CrossTenantReadIsolationTests(_TwoCompanies):
    def _ids(self, url):
        resp = self.api.get(url)
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        data = resp.json()
        rows = data['results'] if isinstance(data, dict) and 'results' in data else data
        return {row['id'] for row in rows}

    def test_clients_list_isolated(self):
        ids = self._ids('/api/v1/clients/clients/')
        self.assertIn(self.client_a.id, ids)
        self.assertNotIn(self.client_b.id, ids)

    def test_orders_list_isolated(self):
        ids = self._ids('/api/v1/orders/orders/')
        self.assertIn(self.order_a.id, ids)
        self.assertNotIn(self.order_b.id, ids)

    def test_payments_list_isolated(self):
        ids = self._ids('/api/v1/clients/payments/')
        self.assertIn(self.client_a.payments.first().id, ids)
        self.assertNotIn(self.client_b.payments.first().id, ids)

    def test_warehouse_isolated(self):
        products = self._ids('/api/v1/warehouse/finished-products/')
        materials = self._ids('/api/v1/warehouse/raw-materials/')
        self.assertIn(self.product_a.id, products)
        self.assertNotIn(self.product_b.id, products)
        self.assertIn(self.material_a.id, materials)
        self.assertNotIn(self.material_b.id, materials)

    def test_audit_isolated(self):
        ids = self._ids('/api/v1/audit/logs/')
        own_logs = AuditLog.objects.filter(company=self.a).values_list('id', flat=True)
        foreign_logs = AuditLog.objects.filter(company=self.b).values_list('id', flat=True)
        self.assertTrue(set(own_logs) <= ids)
        self.assertFalse(set(foreign_logs) & ids)

    def test_reports_analytics_isolated(self):
        resp = self.api.get('/api/v1/reports/analytics/owner/', {'period': 'year'})
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        data = resp.json()
        # Выручка A = 40, расходы A = 10; данные B (999) не протекают.
        self.assertEqual(Decimal(str(data['revenue'])), Decimal('40'))
        self.assertEqual(Decimal(str(data['expenses_total'])), Decimal('10'))

    def test_cannot_fetch_foreign_object_by_id(self):
        for url in (
            f'/api/v1/clients/clients/{self.client_b.id}/',
            f'/api/v1/orders/orders/{self.order_b.id}/',
            f'/api/v1/warehouse/finished-products/{self.product_b.id}/',
            f'/api/v1/warehouse/raw-materials/{self.material_b.id}/',
        ):
            resp = self.api.get(url)
            self.assertEqual(resp.status_code, 404, f'{url} должен быть 404')


class MassAssignmentServerFieldTests(_TwoCompanies):
    def test_order_paid_amount_not_writable(self):
        # paid_amount — производное поле (apply_payment_amount); PATCH игнорируется.
        before = self.order_a.paid_amount
        resp = self.api.patch(
            f'/api/v1/orders/orders/{self.order_a.id}/',
            {'paid_amount': '999999', 'total_amount': '100'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self.order_a.refresh_from_db()
        self.assertEqual(self.order_a.paid_amount, before,
                         'paid_amount не должен меняться прямым PATCH')

    def test_client_debt_not_writable(self):
        resp = self.api.patch(
            f'/api/v1/clients/clients/{self.client_a.id}/',
            {'debt': '999999'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self.client_a.refresh_from_db()
        self.assertNotEqual(self.client_a.debt, Decimal('999999'))

    def test_payment_received_by_not_writable(self):
        # received_by проставляет сервер (текущий пользователь), не клиент.
        resp = self.api.post('/api/v1/clients/payments/', {
            'client': self.client_a.id, 'order': self.order_a.id, 'amount': '10',
            'payment_method': 'cash', 'received_by': self.owner_b.id,
            'payment_date': timezone.localdate().isoformat(),
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        payment = Payment.objects.get(pk=resp.json()['id'])
        self.assertEqual(payment.received_by, self.owner_a)
