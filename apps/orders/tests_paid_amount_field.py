"""
Спец-задание #1 — вычисляемое поле Order.paid_amount не должно писаться напрямую.

paid_amount управляется Order.apply_payment_amount (из зарегистрированных
платежей). В OrderOwnerSerializer оно было записываемым → owner PATCH-ем мог
выставить заказу «оплачено» без единого платежа, рассинхронизировав ledger
платежей и кассу.

total_amount при этом ОСТАЁТСЯ записываемым (владелец задаёт цену заказа — это
не вычисляемое поле, а вход).

До фикса тест падает (paid_amount меняется), после — paid_amount read-only.
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


class PaidAmountFieldTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='PaCo')
        self.owner = User.objects.create_user(username='pa2_o', password='p',
                                               role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='C')
        self.product = FinishedProduct.objects.create(company=self.company, name='P',
                                                      quantity=Decimal('1'))
        self.order = Order.objects.create(
            company=self.company, client=self.client_obj, product=self.product,
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('1000'),
            paid_amount=Decimal('0'), deadline=datetime.date(2026, 1, 1))
        self.api = APIClient()
        self.api.force_authenticate(user=self.owner)

    def test_paid_amount_is_read_only(self):
        resp = self.api.patch(f'/api/v1/orders/orders/{self.order.id}/',
                              {'paid_amount': '999999'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal('0'))  # не подменён

    def test_total_amount_still_editable(self):
        """total_amount — вход владельца, остаётся редактируемым."""
        resp = self.api.patch(f'/api/v1/orders/orders/{self.order.id}/',
                              {'total_amount': '1500'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.total_amount, Decimal('1500'))
