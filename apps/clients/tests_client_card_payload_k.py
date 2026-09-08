"""
Карточка клиента: безопасный payload на уровне API (макет «Мижоз картаси»).

Вкладки макета — Умумий / Заказлар / Тўловлар / Қарзлар. Требование ТЗ: вкладки
не должны просто прятать запрещённые поля — сервер обязан их не отдавать.
Здесь проверяется именно это: у администратора в ответе НЕТ ключей с деньгами,
а не «есть, но не показываются».
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client, Payment
from apps.companies.models import Company
from apps.orders.models import Order

CLIENTS = '/api/v1/clients/clients/'
PAYMENTS = '/api/v1/clients/payments/'
ORDERS = '/api/v1/orders/orders/'

MONEY_KEYS = {
    'debt', 'total_paid', 'total_orders_amount', 'profit', 'payments',
    'total_amount', 'paid_amount', 'cost_price',
}


class ClientCardPayloadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='CardCo')
        cls.owner = User.objects.create_user(
            username='cc_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='cc_admin', password='pw', role=User.Role.ADMIN,
            company=cls.company, full_name='Администратор Б.',
        )
        cls.worker = User.objects.create_user(
            username='cc_worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )
        cls.client_obj = Client.objects.create(
            company=cls.company, name='Акбаров Азизбек', phone='+998901234567',
            address='Тошкент', client_type='individual', responsible_employee=cls.admin,
        )
        cls.order = Order.objects.create(
            company=cls.company, client=cls.client_obj, custom_product_name='Столешница',
            quantity=Decimal('2'), unit='sht', total_amount=Decimal('12750000.00'),
            deadline=timezone.now() + timezone.timedelta(days=3),
        )
        Payment.objects.create(
            company=cls.company, client=cls.client_obj, order=cls.order,
            amount=Decimal('2000000.00'), payment_date=timezone.now(),
        )
        cls.client_obj.recalculate_financials()

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    # ── Вкладка «Умумий» ────────────────────────────────────────────────────

    def test_owner_card_has_profile_and_money(self):
        data = self.api_as(self.owner).get(f'{CLIENTS}{self.client_obj.id}/').data
        self.assertEqual(data['client_type'], 'individual')
        self.assertEqual(data['responsible_employee_name'], 'Администратор Б.')
        self.assertIn('created_at', data)
        for key in ('debt', 'total_paid', 'total_orders_amount', 'profit', 'payments'):
            self.assertIn(key, data, f'владельцу не хватает поля {key}')

    def test_admin_card_has_profile_without_any_money_key(self):
        """Ключей с деньгами в ответе администратора быть не должно вовсе."""
        data = self.api_as(self.admin).get(f'{CLIENTS}{self.client_obj.id}/').data
        self.assertEqual(data['client_type'], 'individual')
        self.assertEqual(data['responsible_employee_name'], 'Администратор Б.')
        leaked = MONEY_KEYS & set(data.keys())
        self.assertFalse(leaked, f'администратор получил денежные ключи: {leaked}')
        # Признак долга без суммы — по нему рисуется красная карточка.
        self.assertIn('has_debt', data)
        self.assertTrue(data['has_debt'])

    def test_admin_list_has_no_money_keys(self):
        rows = self.api_as(self.admin).get(CLIENTS).data
        rows = rows['results'] if 'results' in rows else rows
        leaked = MONEY_KEYS & set(rows[0].keys())
        self.assertFalse(leaked, f'список клиентов отдал админу: {leaked}')

    # ── Вкладка «Заказлар» ──────────────────────────────────────────────────

    def test_orders_tab_data_is_real_and_scoped(self):
        """Вкладка берёт настоящие заказы клиента, а не выдуманный список."""
        other_client = Client.objects.create(company=self.company, name='Другой')
        Order.objects.create(
            company=self.company, client=other_client, custom_product_name='Чужой заказ',
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('100'),
            deadline=timezone.now() + timezone.timedelta(days=1),
        )
        rows = self.api_as(self.owner).get(ORDERS, {'client': self.client_obj.id}).data
        rows = rows['results'] if 'results' in rows else rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], self.order.id)

    def test_orders_tab_for_admin_has_no_amounts(self):
        rows = self.api_as(self.admin).get(ORDERS, {'client': self.client_obj.id}).data
        rows = rows['results'] if 'results' in rows else rows
        leaked = MONEY_KEYS & set(rows[0].keys())
        self.assertFalse(leaked, f'заказы клиента отдали админу: {leaked}')
        # Статус оплаты без суммы администратору нужен по ТЗ.
        self.assertIn('payment_status', rows[0])

    # ── Вкладки «Тўловлар» и «Қарзлар» ──────────────────────────────────────

    def test_payments_endpoint_is_owner_only(self):
        self.assertEqual(
            self.api_as(self.owner).get(PAYMENTS, {'client': self.client_obj.id}).status_code, 200,
        )
        self.assertEqual(
            self.api_as(self.admin).get(PAYMENTS, {'client': self.client_obj.id}).status_code, 403,
        )
        self.assertEqual(
            self.api_as(self.worker).get(PAYMENTS, {'client': self.client_obj.id}).status_code, 403,
        )

    def test_owner_payment_history_is_real(self):
        rows = self.api_as(self.owner).get(PAYMENTS, {'client': self.client_obj.id}).data
        rows = rows['results'] if 'results' in rows else rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(Decimal(str(rows[0]['amount'])), Decimal('2000000.00'))

    def test_debt_numbers_match_orders_and_payments(self):
        """Вкладка «Қарзлар» показывает пересчитанные, а не сохранённые «на глаз» цифры."""
        data = self.api_as(self.owner).get(f'{CLIENTS}{self.client_obj.id}/').data
        self.assertEqual(Decimal(str(data['total_orders_amount'])), Decimal('12750000.00'))
        self.assertEqual(Decimal(str(data['total_paid'])), Decimal('2000000.00'))
        self.assertEqual(Decimal(str(data['debt'])), Decimal('10750000.00'))

    # ── Изоляция ────────────────────────────────────────────────────────────

    def test_worker_has_no_client_card(self):
        response = self.api_as(self.worker).get(f'{CLIENTS}{self.client_obj.id}/')
        self.assertEqual(response.status_code, 403)

    def test_foreign_client_card_denied(self):
        other = Company.objects.create(name='OtherCardCo')
        foreign_owner = User.objects.create_user(
            username='cc_foreign', password='pw', role=User.Role.OWNER, company=other,
        )
        response = self.api_as(foreign_owner).get(f'{CLIENTS}{self.client_obj.id}/')
        self.assertEqual(response.status_code, 404)


class ClientListTabsTests(TestCase):
    """
    Вкладки списка клиентов (макет «Мижозлар»: Барчаси / Фаол / Қарзи бор / Архив).

    Фильтры серверные и булевы: факт долга администратору виден (по нему
    рисуется красная карточка), сумма — нет.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='TabsCo')
        cls.owner = User.objects.create_user(
            username='ct_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='ct_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )
        # Клиент с долгом
        cls.debtor = Client.objects.create(
            company=cls.company, name='Должник', debt=Decimal('5000.00'),
        )
        # Клиент с активным заказом, но без долга
        cls.with_order = Client.objects.create(company=cls.company, name='С заказом')
        Order.objects.create(
            company=cls.company, client=cls.with_order, custom_product_name='Столешница',
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('100'),
            paid_amount=Decimal('100'), status=Order.Status.IN_PROGRESS,
            deadline=timezone.now() + timezone.timedelta(days=2),
        )
        # Спокойный клиент: ни долга, ни активных заказов
        cls.quiet = Client.objects.create(company=cls.company, name='Спокойный')
        # Архивный
        cls.archived = Client.objects.create(
            company=cls.company, name='Архивный', is_archived=True,
        )

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def names(self, user, params):
        rows = self.api_as(user).get(CLIENTS, params).data
        rows = rows['results'] if 'results' in rows else rows
        return {row['name'] for row in rows}

    def test_all_tab_shows_non_archived(self):
        names = self.names(self.owner, {'is_archived': 'false'})
        self.assertEqual(names, {'Должник', 'С заказом', 'Спокойный'})

    def test_active_tab_is_debt_or_open_order(self):
        names = self.names(self.owner, {'is_archived': 'false', 'is_active_client': 'true'})
        self.assertEqual(names, {'Должник', 'С заказом'})
        self.assertNotIn('Спокойный', names)

    def test_debt_tab(self):
        names = self.names(self.owner, {'is_archived': 'false', 'has_debt': 'true'})
        self.assertEqual(names, {'Должник'})

    def test_archive_tab(self):
        names = self.names(self.owner, {'is_archived': 'true'})
        self.assertEqual(names, {'Архивный'})

    def test_admin_can_filter_by_debt_without_seeing_amounts(self):
        rows = self.api_as(self.admin).get(
            CLIENTS, {'is_archived': 'false', 'has_debt': 'true'},
        ).data
        rows = rows['results'] if 'results' in rows else rows
        self.assertEqual([r['name'] for r in rows], ['Должник'])
        self.assertNotIn('debt', rows[0])
        self.assertTrue(rows[0]['has_debt'])

    def test_filters_are_tenant_scoped(self):
        other = Company.objects.create(name='OtherTabsCo')
        Client.objects.create(company=other, name='Чужой должник', debt=Decimal('999'))
        names = self.names(self.owner, {'is_archived': 'false', 'has_debt': 'true'})
        self.assertNotIn('Чужой должник', names)
