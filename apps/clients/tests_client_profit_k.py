"""
Прибыль по клиенту — полная карточка владельца (ТЗ).

Правило: прибыль клиента = сумма ВЫДАННЫХ заказов (total_amount по
status=DELIVERED, не архивных) минус их себестоимость (quantity × снимок
cost_price на момент выдачи), за всё время. Невыданные (в работе/готовые) и
отменённые заказы прибыли не дают — прибыль реализованная, как COGS в отчётах.

Поле отдаётся только владельцу (ClientOwnerSerializer): админ получает ту же
модель, но БЕЗ ключа profit — server-side ограничение, а не скрытие в UI.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct


def _money(value):
    """Значение из JSON (строка или число) -> Decimal для сравнения."""
    return Decimal(str(value))


_UNSET = object()


class ClientProfitTests(TestCase):
    """Расчёт прибыли по выданным заказам и её отсутствие у не-owner ролей."""

    def setUp(self):
        self.company = Company.objects.create(name='ProfitCo', is_active=True)
        self.owner = User.objects.create_user(
            username='profit_owner', password='p',
            role=User.Role.OWNER, company=self.company)
        self.admin = User.objects.create_user(
            username='profit_admin', password='p',
            role=User.Role.ADMIN, company=self.company)
        self.client = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('100'),
            unit='sht', cost_price=Decimal('40'))
        self.owner_api = self._api(self.owner)
        self.admin_api = self._api(self.admin)

    def _api(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def _order(self, status=Order.Status.DELIVERED, quantity='2', total_amount='200',
               product=_UNSET):
        """Заказ со снимком себестоимости на момент выдачи (как в бою).

        По умолчанию товарный заказ на self.product (snapshot cost_price из
        товара); product=None — заказ «вручную» без товара и без снимка.
        """
        if product is _UNSET:
            product = self.product
        return Order.objects.create(
            company=self.company, client=self.client,
            product=product,
            custom_product_name='' if product else 'Изделие на заказ',
            quantity=Decimal(quantity), unit='sht',
            total_amount=Decimal(total_amount), status=status,
        )

    def _owner_profit(self, client=None):
        client = client or self.client
        resp = self.owner_api.get(f'/api/v1/clients/clients/{client.id}/')
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_owner_profit_is_revenue_minus_cogs_over_delivered(self):
        # Выданы: 2 × 40 = 80 COGS и 5 × 40 = 200 COGS. Выручка 200 + 350.
        self._order(total_amount='200')
        self._order(total_amount='350', quantity='5')
        data = self._owner_profit()
        self.assertIn('profit', data)
        self.assertEqual(_money(data['profit']), Decimal('270.00'))

    def test_profit_excludes_not_delivered_and_cancelled(self):
        # Готовый (не выдан) на 1000 и отменённый на 500 прибыли не дают.
        self._order(total_amount='200')
        self._order(status=Order.Status.READY, total_amount='1000')
        self._order(status=Order.Status.CANCELLED, total_amount='500')
        data = self._owner_profit()
        self.assertEqual(_money(data['profit']), Decimal('120.00'))

    def test_custom_product_without_snapshot_profit_equals_revenue(self):
        # Заказ без товара (вручную): снимка нет, COGS = 0 — как в отчётах.
        self._order(product=None, total_amount='450')
        data = self._owner_profit()
        self.assertEqual(_money(data['profit']), Decimal('450.00'))

    def test_profit_uses_snapshot_not_live_product_price(self):
        order = self._order(total_amount='200')  # снимок 40 × 2 = 80
        self.assertGreater(order.cost_price, 0)
        # Переоценка товара после выдачи не меняет прибыль выданного заказа.
        self.product.cost_price = Decimal('999')
        self.product.save(update_fields=['cost_price'])
        data = self._owner_profit()
        self.assertEqual(_money(data['profit']), Decimal('120.00'))

    def test_profit_is_zero_when_no_delivered_orders(self):
        data = self._owner_profit()
        self.assertIn('profit', data)
        self.assertEqual(_money(data['profit']), Decimal('0'))

    def test_profit_present_in_owner_list_too(self):
        self._order(total_amount='200')
        resp = self.owner_api.get('/api/v1/clients/clients/?is_archived=false')
        self.assertEqual(resp.status_code, 200)
        results = resp.json().get('results', resp.json())
        client = next(c for c in results if c['id'] == self.client.id)
        self.assertIn('profit', client)
        self.assertEqual(_money(client['profit']), Decimal('120.00'))

    def test_admin_never_receives_profit_field(self):
        self._order(total_amount='200')
        resp = self.admin_api.get(f'/api/v1/clients/clients/{self.client.id}/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertNotIn('profit', data)
        # Финансовая карточка целиком недоступна админу (server-side).
        for key in ('total_orders_amount', 'total_paid', 'debt'):
            self.assertNotIn(key, data)
        self.assertIn('has_debt', data)
