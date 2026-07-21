"""
Этап F — регрессия: прямая запись Order.status / payment_status через PATCH.

OrderSerializer держал status и payment_status записываемыми. Owner/admin мог
PATCH-ем поставить заказу status='delivered' в обход action deliver() (который
пересчитывает финансы клиента, архивирует его и шлёт уведомление о неоплате) —
конечный автомат заказа рассинхронизировался.

Переходы должны идти только через действия (deliver/cancel) и производственный
поток. Фронтенд status/payment_status прямым PATCH не отправляет (форма шлёт
client/product/quantity/unit/deadline/total_amount/comment), поэтому read-only
их не ломает.

До фикса тесты падают (status меняется), после — status read-only.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.clients.models import Client
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct


class OrderStatusMassAssignTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='FCo')
        self.owner = User.objects.create_user(username='f_o', password='p',
                                               role=User.Role.OWNER, company=self.company)
        self.admin = User.objects.create_user(username='f_a', password='p',
                                               role=User.Role.ADMIN, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='C')
        self.product = FinishedProduct.objects.create(company=self.company, name='P',
                                                      quantity=Decimal('1'))
        self.order = Order.objects.create(
            company=self.company, client=self.client_obj, product=self.product,
            quantity=Decimal('1'), unit='sht', status=Order.Status.NEW,
            deadline=datetime.date(2026, 1, 1))

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_admin_cannot_patch_status_directly(self):
        resp = self.api(self.admin).patch(
            f'/api/v1/orders/orders/{self.order.id}/',
            {'status': 'delivered'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.NEW)  # read-only: не изменился

    def test_owner_cannot_patch_payment_status_directly(self):
        resp = self.api(self.owner).patch(
            f'/api/v1/orders/orders/{self.order.id}/',
            {'payment_status': 'paid'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.payment_status, Order.PaymentStatus.PAID)

    def test_edit_form_fields_still_work(self):
        """Позитивный контроль: обычное редактирование (comment) проходит."""
        resp = self.api(self.owner).patch(
            f'/api/v1/orders/orders/{self.order.id}/',
            {'comment': 'обновлено'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.comment, 'обновлено')

    def test_deliver_action_still_changes_status(self):
        """Переход через action работает (status меняется легитимно)."""
        self.order.status = Order.Status.READY
        self.order.save(update_fields=['status'])
        resp = self.api(self.owner).post(f'/api/v1/orders/orders/{self.order.id}/deliver/')
        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.DELIVERED)
