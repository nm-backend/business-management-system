"""
Валидация ввода: 10 дыр, найденных обстрелом боевых эндпоинтов враждебными данными.

Каждый случай ниже РАНЬШЕ возвращал HTTP 201 (запись создавалась), теперь — 400.
Последствия, из-за которых это важно:
  • отрицательный остаток и отрицательная цена ломают склад и завышают прибыль
    (себестоимость со знаком минус увеличивает валовую прибыль);
  • резерв больше остатка даёт ОТРИЦАТЕЛЬНОЕ доступное количество и ломает
    признак нехватки товара;
  • будущая дата оплаты/расхода прячет сумму из отчёта за текущий период;
  • единица измерения вне списка отображается в интерфейсе пустым местом
    (шаблон подставляет data-i18n="units.<мусор>", перевода нет);
  • заказ со сроком в прошлом сразу попадает в «просроченные» и портит показатель;
  • телефон из букв делает контакт бесполезным.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.warehouse.models import FinishedProduct

FUTURE_DATE = (timezone.localdate() + datetime.timedelta(days=30)).isoformat()
FUTURE_DT = (timezone.now() + datetime.timedelta(days=30)).isoformat()
PAST_DT = (timezone.now() - datetime.timedelta(days=30)).isoformat()


class _Base(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='ValCo', is_active=True)
        self.owner = User.objects.create_user(username='val_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.cli = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Товар', quantity=Decimal('10'), unit='dona')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def post(self, path, body):
        return self.api.post(path, body, format='json')


class WarehouseValidationTests(_Base):
    def test_negative_material_quantity_rejected(self):
        r = self.post('/api/v1/warehouse/raw-materials/',
                      {'name': 'Мат', 'quantity': '-10', 'unit': 'm2'})
        self.assertEqual(r.status_code, 400)

    def test_negative_purchase_price_rejected(self):
        r = self.post('/api/v1/warehouse/raw-materials/',
                      {'name': 'Мат', 'quantity': '5', 'unit': 'm2', 'purchase_price': '-99'})
        self.assertEqual(r.status_code, 400)

    def test_future_arrival_date_rejected(self):
        r = self.post('/api/v1/warehouse/raw-materials/',
                      {'name': 'Мат', 'quantity': '5', 'unit': 'm2', 'arrival_date': FUTURE_DATE})
        self.assertEqual(r.status_code, 400)

    def test_today_arrival_date_accepted(self):
        r = self.post('/api/v1/warehouse/raw-materials/',
                      {'name': 'Мат сегодня', 'quantity': '5', 'unit': 'm2',
                       'arrival_date': timezone.localdate().isoformat()})
        self.assertEqual(r.status_code, 201)

    def test_negative_cost_price_rejected(self):
        r = self.post('/api/v1/warehouse/finished-products/',
                      {'name': 'Т', 'quantity': '1', 'unit': 'dona', 'cost_price': '-50'})
        self.assertEqual(r.status_code, 400)

    def test_reserved_above_quantity_rejected(self):
        r = self.post('/api/v1/warehouse/finished-products/',
                      {'name': 'Т', 'quantity': '1', 'unit': 'dona', 'reserved_for_orders': '100'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('reserved_for_orders', r.json())

    def test_reserved_equal_quantity_accepted(self):
        r = self.post('/api/v1/warehouse/finished-products/',
                      {'name': 'Т2', 'quantity': '5', 'unit': 'dona', 'reserved_for_orders': '5'})
        self.assertEqual(r.status_code, 201)


class OrderValidationTests(_Base):
    def _order(self, **over):
        body = {'client': self.cli.id, 'product': self.product.id,
                'quantity': '1', 'unit': 'dona',
                'deadline': (timezone.now() + datetime.timedelta(days=5)).isoformat()}
        body.update(over)
        return self.post('/api/v1/orders/orders/', body)

    def test_unit_outside_the_list_rejected(self):
        self.assertEqual(self._order(unit='выдумка').status_code, 400)

    def test_known_units_accepted(self):
        for unit in ('sht', 'm', 'm2', 'izdelie', 'dona'):
            self.assertEqual(self._order(unit=unit).status_code, 201, unit)

    def test_deadline_in_the_past_rejected_on_create(self):
        self.assertEqual(self._order(deadline=PAST_DT).status_code, 400)

    def test_existing_order_deadline_can_be_moved_back(self):
        """Перенос срока у существующего заказа — законная операция."""
        created = self._order()
        self.assertEqual(created.status_code, 201)
        order_id = created.json()['id']
        r = self.api.patch(f'/api/v1/orders/orders/{order_id}/',
                           {'deadline': PAST_DT}, format='json')
        self.assertEqual(r.status_code, 200)


class DateAndContactValidationTests(_Base):
    def test_future_payment_date_rejected(self):
        r = self.post('/api/v1/clients/payments/',
                      {'client': self.cli.id, 'amount': '10',
                       'payment_method': 'cash', 'payment_date': FUTURE_DT})
        self.assertEqual(r.status_code, 400)

    def test_future_expense_date_rejected(self):
        r = self.post('/api/v1/finance/expenses/',
                      {'category': 'rent', 'amount': '100', 'date': FUTURE_DATE})
        self.assertEqual(r.status_code, 400)

    def test_garbage_phone_rejected(self):
        r = self.post('/api/v1/clients/clients/',
                      {'name': 'Тел', 'phone': 'не телефон вообще'})
        self.assertEqual(r.status_code, 400)

    def test_real_phone_formats_accepted(self):
        for phone in ('+996 700 11-22-33', '(312) 900700', '0555123456'):
            r = self.post('/api/v1/clients/clients/', {'name': f'К {phone}', 'phone': phone})
            self.assertEqual(r.status_code, 201, phone)


class HostileTextIsStoredSafelyTests(_Base):
    """
    HTML/SQL/emoji в названиях принимать МОЖНО — это допустимый текст.
    Важно, что он не выполняется: ORM параметризует запросы, а интерфейс
    экранирует вывод через ui.escape.
    """
    def test_hostile_strings_are_saved_verbatim(self):
        for name in ('<script>alert(1)</script>', "'; DROP TABLE orders_order; --", '🔥 тест'):
            r = self.post('/api/v1/clients/clients/', {'name': name})
            self.assertEqual(r.status_code, 201, name)
            self.assertEqual(r.json()['name'], name)
        # таблица на месте — SQL-инъекции не произошло
        self.assertTrue(Client.objects.filter(company=self.company).exists())

    def test_empty_and_whitespace_names_rejected(self):
        for name in ('', '   '):
            self.assertEqual(self.post('/api/v1/clients/clients/', {'name': name}).status_code, 400)
