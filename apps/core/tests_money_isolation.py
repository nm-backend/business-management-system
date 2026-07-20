"""
Регрессионные тесты защиты финансовых данных и валидации дат.

По ТЗ сервер НЕ должен отдавать администратору и работнику прибыль,
себестоимость, закупочные цены, расходы и зарплаты. Работник видит только
СВОЙ заработок.

Также: невалидные ?date_from/?date_to раньше давали HTTP 500 (ValidationError
в finance, ValueError «Invalid isoformat string» в reports). Теперь — 400.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company

MONEY_FIELDS = {
    'purchase_price', 'avg_cost_price', 'cost_price', 'sale_price',
    'total_amount', 'paid_amount', 'total_orders_amount', 'total_paid', 'debt',
    'labor_cost', 'rate_per_unit', 'price_per_unit',
}


def deep_find(obj, keys, path=''):
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys:
                found.append(f'{path}.{k}')
            found += deep_find(v, keys, f'{path}.{k}')
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += deep_find(v, keys, f'{path}[{i}]')
    return found


class MoneyLeakTests(TestCase):
    """Админ и работник не получают денежные поля с сервера."""

    def setUp(self):
        from apps.clients.models import Client as Cl
        from apps.orders.models import Order
        from apps.warehouse.models import FinishedProduct, RawMaterial

        self.company = Company.objects.create(name='MoneyCo')
        self.owner = User.objects.create_user(username='m_o', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.admin = User.objects.create_user(username='m_a', password='p',
                                              role=User.Role.ADMIN, company=self.company)
        self.worker = User.objects.create_user(username='m_w', password='p',
                                               role=User.Role.WORKER, company=self.company)
        RawMaterial.objects.create(company=self.company, name='M', quantity=Decimal('5'),
                                   purchase_price=Decimal('777'), avg_cost_price=Decimal('555'))
        prod = FinishedProduct.objects.create(company=self.company, name='P', quantity=Decimal('5'),
                                              cost_price=Decimal('333'), sale_price=Decimal('999'))
        client = Cl.objects.create(company=self.company, name='Cl', debt=Decimal('1234'))
        Order.objects.create(company=self.company, client=client, product=prod,
                             quantity=Decimal('1'), unit='izdelie', status='in_progress',
                             total_amount=Decimal('9999'), paid_amount=Decimal('1111'),
                             deadline=datetime.date(2026, 1, 1))

    def _api(self, user):
        api = APIClient()
        api.force_authenticate(user=user)
        return api

    def test_admin_gets_no_money_fields(self):
        api = self._api(self.admin)
        for url in ['/api/v1/warehouse/raw-materials/', '/api/v1/warehouse/finished-products/',
                    '/api/v1/clients/clients/', '/api/v1/orders/orders/',
                    '/api/v1/reports/analytics/admin/']:
            with self.subTest(url=url):
                resp = api.get(url)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(deep_find(resp.json(), MONEY_FIELDS), [], f'утечка в {url}')

    def test_worker_gets_no_money_fields_in_stock_and_orders(self):
        api = self._api(self.worker)
        for url in ['/api/v1/warehouse/raw-materials/', '/api/v1/warehouse/finished-products/',
                    '/api/v1/orders/orders/']:
            with self.subTest(url=url):
                resp = api.get(url)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(deep_find(resp.json(), MONEY_FIELDS), [], f'утечка в {url}')

    def test_finance_endpoints_forbidden_for_admin_and_worker(self):
        for user in (self.admin, self.worker):
            api = self._api(user)
            for url in ['/api/v1/finance/expenses/', '/api/v1/finance/worker-payments/',
                        '/api/v1/finance/labor-rates/', '/api/v1/reports/analytics/owner/',
                        '/api/v1/reports/export/finance/']:
                with self.subTest(role=user.role, url=url):
                    self.assertEqual(api.get(url).status_code, 403)

    def test_worker_cannot_see_other_workers_earnings(self):
        """Работник видит СВОЙ заработок, но не чужой."""
        from apps.production.models import WorkRecord
        from apps.warehouse.models import FinishedProduct

        prod = FinishedProduct.objects.get(name='P')
        other = User.objects.create_user(username='m_w2', password='p',
                                         role=User.Role.WORKER, company=self.company)
        WorkRecord.objects.create(company=self.company, worker=self.worker, product=prod,
                                  quantity=Decimal('1'), labor_cost=Decimal('100'))
        WorkRecord.objects.create(company=self.company, worker=other, product=prod,
                                  quantity=Decimal('1'), labor_cost=Decimal('999'))

        resp = self._api(self.worker).get('/api/v1/production/works/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('100', body)          # свой заработок виден
        self.assertNotIn('999', body)       # чужой — нет

    def test_admin_sees_work_without_money(self):
        from apps.production.models import WorkRecord
        from apps.warehouse.models import FinishedProduct

        prod = FinishedProduct.objects.get(name='P')
        WorkRecord.objects.create(company=self.company, worker=self.worker, product=prod,
                                  quantity=Decimal('1'), labor_cost=Decimal('4242'))
        resp = self._api(self.admin).get('/api/v1/production/works/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(deep_find(resp.json(), MONEY_FIELDS), [])


class InvalidDateParamTests(TestCase):
    """Регрессия: кривые даты давали 500, теперь 400."""

    def setUp(self):
        self.company = Company.objects.create(name='DateCo')
        self.owner = User.objects.create_user(username='d_o', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(user=self.owner)

    def test_invalid_dates_return_400_not_500(self):
        cases = [
            ('/api/v1/finance/expenses/', {'date_from': 'abc'}),
            ('/api/v1/finance/expenses/', {'date_to': "' OR 1=1"}),
            ('/api/v1/finance/worker-payments/', {'date_from': '31-31-2026'}),
            ('/api/v1/finance/worker-payments/', {'date_to': '2026-13-45'}),
            ('/api/v1/reports/analytics/owner/', {'date_from': 'zzz'}),
            ('/api/v1/reports/analytics/owner/', {'date_to': '01/02/2026'}),
        ]
        for url, params in cases:
            with self.subTest(url=url, params=params):
                resp = self.api.get(url, params)
                self.assertLess(resp.status_code, 500, f'HTTP 500 на {url} {params}')
                self.assertEqual(resp.status_code, 400)

    def test_valid_dates_still_work(self):
        for url in ['/api/v1/finance/expenses/', '/api/v1/finance/worker-payments/',
                    '/api/v1/reports/analytics/owner/']:
            with self.subTest(url=url):
                resp = self.api.get(url, {'date_from': '2026-01-01', 'date_to': '2026-12-31'})
                self.assertEqual(resp.status_code, 200)
