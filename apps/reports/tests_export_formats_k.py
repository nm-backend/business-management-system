"""
Экспорт отчётов в PDF и Excel.

БАГ (воспроизведён на живом API): кнопка «PDF» в финансах всегда отдавала 404.
Причина не в коде вьюхи — DRF сам обрабатывает query-параметр ?format= для
выбора рендерера и возвращает 404, если формат ему неизвестен. Запрос не
доходил до OwnerFinanceExportView вообще. Лечится URL_FORMAT_OVERRIDE=None:
параметр читают сами вьюхи экспорта.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client, Payment
from apps.companies.models import Company
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct, RawMaterial

EXPORTS = ['/api/v1/reports/export/finance/',
           '/api/v1/reports/export/orders/',
           '/api/v1/reports/export/stock/',
           '/api/v1/reports/export/work/']


class ExportFormatsTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='ExpCo', is_active=True)
        self.owner = User.objects.create_user(username='exp_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        cli = Client.objects.create(company=self.company, name='Клиент Кириллица')
        product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('3'),
            unit='dona', cost_price=Decimal('1000'))
        RawMaterial.objects.create(company=self.company, name='Гранит', quantity=Decimal('10'),
                                   unit='m2')
        Order.objects.create(company=self.company, client=cli, product=product,
                             quantity=Decimal('1'), unit='dona', total_amount=Decimal('5000'),
                             deadline=timezone.now() + datetime.timedelta(days=5))
        Payment.objects.create(company=self.company, client=cli, amount=Decimal('1000'),
                               payment_method='cash', payment_date=timezone.now())
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_pdf_export_returns_a_pdf(self):
        for url in EXPORTS:
            resp = self.api.get(url + '?format=pdf')
            self.assertEqual(resp.status_code, 200, f'{url}: {resp.status_code}')
            body = b''.join(resp.streaming_content) if resp.streaming else resp.content
            self.assertTrue(body.startswith(b'%PDF'), f'{url}: это не PDF')
            self.assertGreater(len(body), 1000, f'{url}: PDF подозрительно мал')

    def test_excel_export_returns_a_workbook(self):
        for url in EXPORTS:
            resp = self.api.get(url)
            self.assertEqual(resp.status_code, 200, url)
            body = b''.join(resp.streaming_content) if resp.streaming else resp.content
            self.assertTrue(body.startswith(b'PK'), f'{url}: это не xlsx')

    def test_format_param_is_not_swallowed_by_drf(self):
        """Именно этот параметр раньше приводил к 404 до входа во вьюху."""
        resp = self.api.get('/api/v1/reports/export/finance/?format=pdf')
        self.assertNotEqual(resp.status_code, 404)

    def test_worker_cannot_export_finance(self):
        worker = User.objects.create_user(username='exp_worker', password='p',
                                          role=User.Role.WORKER, company=self.company)
        api = APIClient()
        api.force_authenticate(worker)
        self.assertEqual(api.get('/api/v1/reports/export/finance/?format=pdf').status_code, 403)
