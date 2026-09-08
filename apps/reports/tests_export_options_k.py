"""
Параметры экспорта (макет «Ҳисобот экспорти»: три тумблера).

Главное требование: каждый параметр ДОЛЖЕН менять файл. Поэтому все тесты
сравнивают выгрузку с параметром и без него — «переключатель, который ничего
не делает» такую проверку не пройдёт.

Второе требование: параметры не расширяют права. Администратор с любыми
тумблерами не получает ни одной суммы.
"""
import io
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from openpyxl import load_workbook
from pypdf import PdfReader
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client, Payment
from apps.companies.models import Company
from apps.finance.models import Expense, ExpenseCategory
from apps.orders.models import Order
from apps.warehouse.models import RawMaterial, Warehouse, WarehouseCell

FINANCE = '/api/v1/reports/export/finance/'
STOCK = '/api/v1/reports/export/stock/'


def pdf_bytes_pages(content):
    return PdfReader(io.BytesIO(content)).pages


def pdf_text(content):
    return '\n'.join(page.extract_text() or '' for page in pdf_bytes_pages(content))


def xlsx_cells(content):
    workbook = load_workbook(io.BytesIO(content))
    values = []
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows(values_only=True):
            values += [str(cell) for cell in row if cell is not None]
    return values


class ExportOptionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='OptCo')
        cls.owner = User.objects.create_user(
            username='eo_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='eo_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )
        warehouse = Warehouse.objects.create(company=cls.company, name='Асосий омбор')
        cell = WarehouseCell.objects.create(
            company=cls.company, warehouse=warehouse, code='A-01', zone='a',
        )
        RawMaterial.objects.create(
            company=cls.company, name='Гранит', stone_type='granite', unit='m2',
            quantity=Decimal('50'), min_stock=Decimal('5'),
            purchase_price=Decimal('777777.77'), avg_cost_price=Decimal('777777.77'),
            warehouse=warehouse, cell=cell, condition='good',
            supplier='ООО Тошкент Мармар', storage_zone='a',
        )
        client_obj = Client.objects.create(company=cls.company, name='Акбаров')
        order = Order.objects.create(
            company=cls.company, client=client_obj, custom_product_name='Столешница',
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('500000.00'),
            deadline=timezone.now() + timezone.timedelta(days=1),
        )
        Payment.objects.create(
            company=cls.company, client=client_obj, order=order,
            amount=Decimal('123456.78'), payment_date=timezone.now(),
        )
        Expense.objects.create(
            company=cls.company, category=ExpenseCategory.RENT, amount=Decimal('98765.43'),
            created_by=cls.owner, date=timezone.localdate(), comment='Аренда цеха',
        )

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    # ── Детализация ─────────────────────────────────────────────────────────

    def test_detailed_finance_adds_operation_rows(self):
        api = self.api_as(self.owner)
        plain = xlsx_cells(api.get(FINANCE).content)
        detailed = xlsx_cells(api.get(FINANCE, {'detailed': '1'}).content)

        self.assertGreater(len(detailed), len(plain), 'детализация не изменила файл')
        # Сумма расхода совпадает с итогом «Харажатлар», поэтому по ней
        # отличить режимы нельзя. Признак детализации — раздел операций и
        # имя клиента в строке платежа: в сводном отчёте их нет.
        self.assertNotIn('Тафсилот', plain)
        self.assertIn('Тафсилот', detailed)
        self.assertNotIn('Акбаров', plain)
        self.assertIn('Акбаров', detailed)
        # Категория конкретного расхода тоже появляется только в детализации.
        self.assertIn('Ижара', detailed)

    def test_detailed_stock_adds_operational_columns(self):
        api = self.api_as(self.owner)
        plain = xlsx_cells(api.get(STOCK).content)
        detailed = xlsx_cells(api.get(STOCK, {'detailed': '1'}).content)

        self.assertGreater(len(detailed), len(plain))
        self.assertIn('A-01', detailed)
        self.assertIn('ООО Тошкент Мармар', detailed)
        self.assertNotIn('A-01', plain)

    def test_detailed_stock_for_admin_has_no_money(self):
        """Детализация не расширяет права: у администратора цен нет и с ней."""
        cells = xlsx_cells(self.api_as(self.admin).get(STOCK, {'detailed': '1'}).content)
        self.assertIn('A-01', cells, 'операционная детализация админу положена')
        self.assertNotIn('777777.77', cells, 'закупочная цена утекла администратору')

    def test_admin_cannot_use_finance_export_with_any_option(self):
        api = self.api_as(self.admin)
        for params in ({}, {'detailed': '1'}, {'notes': '1'}, {'charts': '1'}):
            self.assertEqual(api.get(FINANCE, params).status_code, 403, params)

    # ── Пояснения ───────────────────────────────────────────────────────────

    def test_notes_add_formulas_to_xlsx(self):
        api = self.api_as(self.owner)
        plain = xlsx_cells(api.get(FINANCE).content)
        with_notes = xlsx_cells(api.get(FINANCE, {'notes': '1'}).content)

        self.assertGreater(len(with_notes), len(plain), 'пояснения не изменили файл')
        joined = ' '.join(with_notes)
        self.assertIn('=', joined, 'в пояснениях должна быть формула показателя')

    def test_notes_add_block_to_pdf(self):
        api = self.api_as(self.owner)
        plain = pdf_text(api.get(FINANCE, {'format': 'pdf'}).content)
        with_notes = pdf_text(api.get(FINANCE, {'format': 'pdf', 'notes': '1'}).content)
        self.assertGreater(len(with_notes), len(plain), 'пояснения не попали в PDF')

    def test_notes_in_csv(self):
        api = self.api_as(self.owner)
        plain = api.get(FINANCE, {'format': 'csv'}).content.decode('utf-8')
        with_notes = api.get(FINANCE, {'format': 'csv', 'notes': '1'}).content.decode('utf-8')
        self.assertGreater(len(with_notes), len(plain))

    def test_stock_notes_available_to_admin(self):
        api = self.api_as(self.admin)
        plain = xlsx_cells(api.get(STOCK).content)
        with_notes = xlsx_cells(api.get(STOCK, {'notes': '1'}).content)
        self.assertGreater(len(with_notes), len(plain))
        self.assertNotIn('777777.77', ' '.join(with_notes))

    # ── Графики ─────────────────────────────────────────────────────────────

    def test_charts_make_pdf_bigger_and_valid(self):
        """
        График — настоящая диаграмма reportlab, а не подпись.

        Сравниваем размер потока страницы: рисунок добавляет векторные
        команды, поэтому содержимое страницы заметно растёт.
        """
        api = self.api_as(self.owner)
        plain = api.get(FINANCE, {'format': 'pdf'}).content
        charted = api.get(FINANCE, {'format': 'pdf', 'charts': '1'}).content

        self.assertTrue(charted.startswith(b'%PDF'))
        self.assertGreater(len(charted), len(plain), 'график не изменил PDF')

        plain_stream = pdf_bytes_pages(plain)[0].get_contents().get_data()
        chart_stream = pdf_bytes_pages(charted)[0].get_contents().get_data()
        self.assertGreater(
            len(chart_stream), len(plain_stream) * 1.2,
            'содержимое страницы почти не изменилось — диаграмма не отрисована',
        )

    def test_charts_available_to_admin_without_money(self):
        api = self.api_as(self.admin)
        charted = api.get(STOCK, {'format': 'pdf', 'charts': '1'}).content
        self.assertTrue(charted.startswith(b'%PDF'))
        self.assertNotIn('777777.77', pdf_text(charted))

    def test_charts_do_not_break_xlsx(self):
        """Для Excel параметр графика безвреден: файл остаётся читаемым."""
        response = self.api_as(self.owner).get(FINANCE, {'charts': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(xlsx_cells(response.content))

    # ── Комбинации и устойчивость ───────────────────────────────────────────

    def test_all_options_together(self):
        response = self.api_as(self.owner).get(FINANCE, {
            'format': 'pdf', 'charts': '1', 'notes': '1', 'detailed': '1',
        })
        self.assertEqual(response.status_code, 200)
        text = pdf_text(response.content)
        self.assertIn('98765.43', text.replace(' ', ''))

    def test_unknown_option_value_is_treated_as_off(self):
        api = self.api_as(self.owner)
        plain = xlsx_cells(api.get(FINANCE).content)
        weird = xlsx_cells(api.get(FINANCE, {'detailed': 'может быть'}).content)
        self.assertEqual(len(weird), len(plain))

    def test_options_do_not_leak_other_tenant(self):
        other = Company.objects.create(name='OtherOptCo')
        other_client = Client.objects.create(company=other, name='ЧУЖОЙ')
        other_order = Order.objects.create(
            company=other, client=other_client, custom_product_name='Чужой',
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('1'),
            deadline=timezone.now() + timezone.timedelta(days=1),
        )
        Payment.objects.create(
            company=other, client=other_client, order=other_order,
            amount=Decimal('555555.55'), payment_date=timezone.now(),
        )
        cells = ' '.join(xlsx_cells(
            self.api_as(self.owner).get(FINANCE, {'detailed': '1'}).content,
        ))
        self.assertNotIn('555555.55', cells)
        self.assertNotIn('ЧУЖОЙ', cells)
