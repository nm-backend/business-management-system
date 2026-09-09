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
                             unit='sht', total_amount=Decimal('100'))
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
            min_stock=Decimal('10'), unit='sht')
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
            min_stock=Decimal('10'), unit='sht')
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
                                                 quantity=Decimal('10'), unit='sht')
        self.p2 = FinishedProduct.objects.create(company=self.company, name='Дубликат',
                                                 quantity=Decimal('10'), unit='sht')

    def _deliver_order(self, product, quantity):
        order = Order.objects.create(
            company=self.company, client=self.client, product=product,
            quantity=quantity, unit='sht', total_amount=Decimal(quantity * 100),
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


class WorkerAggregatesUnitTests(TestCase):
    """
    Агрегаты по работникам не суммируют количество в разных единицах
    (тот же баг, что был в summary склада): total_quantity отдаётся только
    при единой единице, иначе unit_totals + ранжирование по числу работ.
    """
    ADMIN = '/api/v1/reports/analytics/admin/'

    def setUp(self):
        self.company = Company.objects.create(name='WorkCo', is_active=True)
        self.owner = User.objects.create_user(username='work_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.worker_a = User.objects.create_user(username='worker_a', password='p',
                                                 role=User.Role.WORKER, company=self.company,
                                                 full_name='Работник А')
        self.worker_b = User.objects.create_user(username='worker_b', password='p',
                                                 role=User.Role.WORKER, company=self.company,
                                                 full_name='Работник Б')

    def _work(self, worker, quantity, unit, confirmed=True):
        return WorkRecord.objects.create(
            company=self.company, worker=worker, quantity=Decimal(str(quantity)),
            unit=unit,
            status=(WorkRecord.WorkStatus.CONFIRMED if confirmed
                    else WorkRecord.WorkStatus.AWAITING_CONFIRMATION),
            confirmed_at=timezone.now() if confirmed else None,
        )

    def test_single_unit_worker_has_plain_total(self):
        for q in (2, 3, 5):
            self._work(self.worker_a, q, 'sht')
        # Неподтверждённая работа не влияет на агрегаты.
        self._work(self.worker_a, 999, 'sht', confirmed=False)
        data = self.api.get(OWNER).json()
        w = data['most_active_worker']
        self.assertIsNotNone(w)
        self.assertEqual(w['name'], 'Работник А')
        self.assertEqual(Decimal(str(w['total_quantity'])), Decimal('10'))
        self.assertEqual(w['unit_totals'], [{'unit': 'sht', 'total_quantity': 10}])
        self.assertEqual(w['works'], 3)

    def test_mixed_units_never_summed(self):
        self._work(self.worker_a, 2, 'sht')
        self._work(self.worker_a, 3, 'm')
        data = self.api.get(OWNER).json()
        w = data['most_active_worker']
        self.assertIsNone(w['total_quantity'], 'разные единицы — общего количества нет')
        self.assertEqual(w['unit_totals'], [
            {'unit': 'm', 'total_quantity': 3},
            {'unit': 'sht', 'total_quantity': 2},
        ])
        self.assertEqual(w['works'], 2)

    def test_ranking_by_works_when_units_mixed(self):
        # А: 10 шт в 2 работах; Б: 20 м в 1 работе. Сумма по количеству дала бы
        # победителем Б (20 > 10), но 10 шт и 20 м несравнимы — побеждает тот,
        # у кого больше подтверждённых работ.
        self._work(self.worker_a, 10, 'sht')
        self._work(self.worker_a, 4, 'sht')
        self._work(self.worker_b, 20, 'm')
        data = self.api.get(OWNER).json()
        self.assertEqual(data['most_active_worker']['worker_id'], self.worker_a.id)

    def test_ranking_by_quantity_when_single_unit(self):
        self._work(self.worker_a, 5, 'sht')
        self._work(self.worker_b, 10, 'sht')
        data = self.api.get(OWNER).json()
        w = data['most_active_worker']
        self.assertEqual(w['worker_id'], self.worker_b.id)
        self.assertEqual(Decimal(str(w['total_quantity'])), Decimal('10'))

    def test_admin_worker_performance_per_unit(self):
        self._work(self.worker_a, 2, 'sht')
        self._work(self.worker_a, 3, 'm')
        self._work(self.worker_b, 7, 'sht')
        data = self.api.get(self.ADMIN).json()
        rows = {r['worker_id']: r for r in data['worker_performance']}
        self.assertIn(self.worker_a.id, rows)
        self.assertIn(self.worker_b.id, rows)
        a = rows[self.worker_a.id]
        self.assertIsNone(a['total_quantity'])
        self.assertEqual(a['unit_totals'], [
            {'unit': 'm', 'total_quantity': 3},
            {'unit': 'sht', 'total_quantity': 2},
        ])
        b = rows[self.worker_b.id]
        self.assertEqual(Decimal(str(b['total_quantity'])), Decimal('7'))
        self.assertEqual(b['unit_totals'], [{'unit': 'sht', 'total_quantity': 7}])
