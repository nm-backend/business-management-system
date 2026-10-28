"""
Сумма ставки оплаты труда — только для владельца.

Аудит: работник получал `GET /api/v1/finance/labor-rates/` с `rate_per_unit`
по всем операциям компании, хотя по ТЗ зарплаты в деньгах ему недоступны.
Админ был замаскирован, работник — нет.

Проверяем оба невладельческих роли на list и retrieve, а также что owner
по-прежнему видит сумму и может фильтровать по товару.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.finance.models import LaborRate
from apps.warehouse.models import FinishedProduct

RATES = '/api/v1/finance/labor-rates/'


class LaborRateMoneyMaskingTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RateMaskCo', is_active=True)
        self.owner = User.objects.create_user(
            username='mask_owner', password='p',
            role=User.Role.OWNER, company=self.company,
        )
        self.admin = User.objects.create_user(
            username='mask_admin', password='p',
            role=User.Role.ADMIN, company=self.company,
        )
        self.worker = User.objects.create_user(
            username='mask_worker', password='p',
            role=User.Role.WORKER, company=self.company,
        )
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('0'), unit='sht',
        )
        self.rate = LaborRate.objects.create(
            company=self.company, product=self.product,
            operation=LaborRate.OperationType.CUTTING,
            rate_per_unit=Decimal('7777'), unit='sht',
        )

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def rows(self, user, url=RATES, params=None):
        resp = self.api(user).get(url, params or {})
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        return resp.json().get('results', resp.json())

    def test_worker_list_has_no_rate_per_unit(self):
        row = self.rows(self.worker)[0]
        self.assertNotIn('rate_per_unit', row)
        self.assertEqual(row['operation'], LaborRate.OperationType.CUTTING)
        self.assertEqual(row['unit'], 'sht')
        self.assertEqual(row['product_name'], 'Столешница')

    def test_worker_retrieve_has_no_rate_per_unit(self):
        row = self.rows(self.worker, f'{RATES}{self.rate.id}/')
        self.assertNotIn('rate_per_unit', row)
        self.assertEqual(row['id'], self.rate.id)

    def test_admin_list_and_retrieve_have_no_rate_per_unit(self):
        self.assertNotIn('rate_per_unit', self.rows(self.admin)[0])
        self.assertNotIn('rate_per_unit', self.rows(self.admin, f'{RATES}{self.rate.id}/'))

    def test_owner_sees_rate_per_unit_everywhere(self):
        self.assertEqual(self.rows(self.owner)[0]['rate_per_unit'], '7777.00')
        self.assertEqual(
            self.rows(self.owner, f'{RATES}{self.rate.id}/')['rate_per_unit'],
            '7777.00',
        )

    def test_owner_filter_by_product_still_sees_money(self):
        other = FinishedProduct.objects.create(
            company=self.company, name='Другой', quantity=Decimal('0'), unit='sht',
        )
        LaborRate.objects.create(
            company=self.company, product=other, operation='polishing',
            rate_per_unit=Decimal('10'), unit='sht',
        )
        rows = self.rows(self.owner, params={'product': self.product.id})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['rate_per_unit'], '7777.00')
        worker_rows = self.rows(self.worker, params={'product': self.product.id})
        self.assertEqual(len(worker_rows), 1)
        self.assertNotIn('rate_per_unit', worker_rows[0])

    def test_operation_is_available_to_worker_for_the_form(self):
        """Маскировка не должна ломать выбор операции при сдаче работы."""
        row = self.rows(self.worker, params={'product': self.product.id})[0]
        self.assertTrue(row['operation'])
        self.assertTrue(row['product'])
