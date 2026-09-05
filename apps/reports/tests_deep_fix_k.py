"""
Глубокая ревизия reports: formula injection в CSV, Камомад по доступному
остатку, топ по id, сходимость финансового экспорта, долги без архива.
"""
import csv
import io
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client, Payment
from apps.companies.models import Company
from apps.finance.models import Expense, WorkerPayment
from apps.orders.models import Order
from apps.production.models import WorkRecord
from apps.warehouse.models import FinishedProduct, RawMaterial

FINANCE = '/api/v1/reports/export/finance/?format=csv'
SHORTAGE = '/api/v1/reports/export/?report_type=material_shortage&format_type=csv'
OWNER = '/api/v1/reports/analytics/owner/?period=month'


class CsvFormulaInjectionTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='CsvCo', is_active=True)
        self.owner = User.objects.create_user(username='csv_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _parsed(self, url):
        resp = self.api.get(url)
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        return list(csv.reader(io.StringIO(resp.content.decode('utf-8')), delimiter=';'))

    def test_csv_escapes_formula_in_client_name(self):
        evil = '=HYPERLINK("http://evil","x")'
        evil_client = Client.objects.create(company=self.company, name=evil)
        Order.objects.create(company=self.company, client=evil_client,
                             custom_product_name='Изделие', quantity=1,
                             unit='dona', total_amount=Decimal('100'))
        rows = self._parsed('/api/v1/reports/export/orders/?format=csv')
        flattened = [cell for row in rows for cell in row]
        self.assertIn("'=HYPERLINK(\"http://evil\",\"x\")", flattened,
                      'имя-формула экранируется апострофом')


class ShortageExportTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='ShortCo', is_active=True)
        self.owner = User.objects.create_user(username='short_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_shortage_uses_available_not_physical_quantity(self):
        material = RawMaterial.objects.create(
            company=self.company, name='Мрамор', quantity=Decimal('10'),
            min_stock=Decimal('10'), unit='dona')
        material.required_for_orders = Decimal('9')
        material.save(update_fields=['required_for_orders'])
        resp = self.api.get(SHORTAGE)
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        rows = list(csv.reader(io.StringIO(resp.content.decode('utf-8')), delimiter=';'))
        data_rows = [r for r in rows if r and r[0] == 'Мрамор']
        self.assertEqual(len(data_rows), 1)
        self.assertEqual(Decimal(data_rows[0][5]), Decimal('9'),
                         'камомад = мин. остаток - доступно')

    def test_shortage_empty_when_available_above_min(self):
        material = RawMaterial.objects.create(
            company=self.company, name='Гранит', quantity=Decimal('12'),
            min_stock=Decimal('10'), unit='dona')
        material.required_for_orders = Decimal('2')
        material.save(update_fields=['required_for_orders'])
        resp = self.api.get(SHORTAGE)
        rows = list(csv.reader(io.StringIO(resp.content.decode('utf-8')), delimiter=';'))
        data_rows = [r for r in rows if r and r[0] == 'Гранит']
        self.assertEqual(len(data_rows), 0)


class TopProductsGroupingTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='TopCo', is_active=True)
        self.owner = User.objects.create_user(username='top_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.client = Client.objects.create(company=self.company, name='ТопКлиент')
        self.p1 = FinishedProduct.objects.create(company=self.company, name='Дубликат',
                                                 quantity=Decimal('10'), unit='dona')
        self.p2 = FinishedProduct.objects.create(company=self.company, name='Дубликат',
                                                 quantity=Decimal('10'), unit='dona')

    def _deliver_order(self, product, quantity):
        order = Order.objects.create(
            company=self.company, client=self.client, product=product,
            quantity=quantity, unit='dona', total_amount=Decimal(quantity * 100),
            status=Order.Status.DELIVERED)
        return order

    def test_top_products_groups_by_id_not_name(self):
        self._deliver_order(self.p1, 3)
        self._deliver_order(self.p2, 5)
        data = self.api.get(OWNER).json()
        top = data['top_products']
        self.assertEqual(len(top), 2, 'товары с одинаковым именем не сливаются')
        quantities = {row['total_quantity'] for row in top}
        self.assertEqual(quantities, {3, 5})


class FinanceExportConsistencyTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='FinCo', is_active=True)
        self.owner = User.objects.create_user(username='fin_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_export_shows_worker_payments(self):
        worker = User.objects.create_user(username='fin_worker', password='p',
                                          role=User.Role.WORKER, company=self.company)
        # Дата относительно «сегодня»: финансовый экспорт по умолчанию берёт
        # текущий месяц (period=month), поэтому жёстко зашитая дата делала тест
        # зависимым от дня запуска (например 2026-08-01 проваливал его в сентябре).
        today = timezone.localdate()
        WorkerPayment.objects.create(
            company=self.company, worker=worker, amount=Decimal('150'),
            payment_date=today, created_by=self.owner)
        resp = self.api.get(FINANCE)
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        content = resp.content.decode('utf-8')
        self.assertIn('Ишчиларга тўловлар', content)
        self.assertIn('тўловлар;150', content, 'выплата работника видна строкой экспорта')
        self.assertNotIn("';-1", content, 'отрицательные суммы не экранируются апострофом')

    def test_client_debts_exclude_archived(self):
        active = Client.objects.create(company=self.company, name='Активный', debt=Decimal('100'))
        archived = Client.objects.create(company=self.company, name='Архивный', debt=Decimal('50'))
        archived.archive()
        active.refresh_from_db()
        data = self.api.get(OWNER).json()
        self.assertEqual(Decimal(str(data['client_debts'])), Decimal('100'))
