"""
Поле labor_rate в карточке работы: ставка за единицу по операции видна и
владельцу, и работнику ДО подтверждения — рабочему при сдаче работы, а
владельцу в модалке подтверждения (расчёт «ставка × количество»).

Логика выбора ставки та же, что в calculate_labor_cost: по операции работы;
если операция не указана — только когда ставка одна; иначе None.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.finance.models import LaborRate
from apps.production.models import WorkRecord
from apps.warehouse.models import FinishedProduct

WORKS = '/api/v1/production/works/'


class WorkLaborRateFieldTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='PayCo', is_active=True)
        self.owner = User.objects.create_user(username='pay_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='pay_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('0'), unit='dona')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _work(self, **kwargs):
        defaults = dict(
            company=self.company, worker=self.worker, product=self.product,
            quantity=Decimal('5'), unit='dona',
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION)
        defaults.update(kwargs)
        return WorkRecord.objects.create(**defaults)

    def _rates(self):
        LaborRate.objects.create(company=self.company, product=self.product,
                                 operation=LaborRate.OperationType.CUTTING,
                                 rate_per_unit=Decimal('50'), unit='dona')
        LaborRate.objects.create(company=self.company, product=self.product,
                                 operation=LaborRate.OperationType.POLISHING,
                                 rate_per_unit=Decimal('70'), unit='dona')

    def test_rate_by_operation(self):
        self._rates()
        work = self._work(operation=LaborRate.OperationType.POLISHING)
        resp = self.api.get(f'{WORKS}{work.id}/')
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        self.assertEqual(resp.json()['labor_rate'], '70.00')

    def test_single_rate_without_operation(self):
        LaborRate.objects.create(company=self.company, product=self.product,
                                 operation=LaborRate.OperationType.OTHER,
                                 rate_per_unit=Decimal('1500'), unit='dona')
        work = self._work()
        self.assertEqual(self.api.get(f'{WORKS}{work.id}/').json()['labor_rate'], '1500.00')

    def test_multiple_rates_without_operation(self):
        """Несколько ставок и операция не указана — ставку не угадываем."""
        self._rates()
        work = self._work()
        self.assertIsNone(self.api.get(f'{WORKS}{work.id}/').json()['labor_rate'])

    def test_no_rate(self):
        work = self._work()
        self.assertIsNone(self.api.get(f'{WORKS}{work.id}/').json()['labor_rate'])

    def test_worker_sees_rate_in_own_work(self):
        """Работник видит ставку ДО подтверждения — знает, сколько получит."""
        self._rates()
        work = self._work(operation=LaborRate.OperationType.CUTTING)
        api = APIClient()
        api.force_authenticate(self.worker)
        resp = api.get(f'{WORKS}{work.id}/')
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        self.assertEqual(resp.json()['labor_rate'], '50.00')

    def test_rate_in_awaiting_list(self):
        """В списке ожидающих подтверждения работ ставка тоже видна."""
        self._rates()
        work = self._work(operation=LaborRate.OperationType.CUTTING)
        resp = self.api.get(WORKS, {'status': 'awaiting_confirmation'})
        rows = resp.json()['results'] if isinstance(resp.json(), dict) else resp.json()
        row = next(r for r in rows if r['id'] == work.id)
        self.assertEqual(row['labor_rate'], '50.00')


class LaborRateReadAccessTests(TestCase):
    """
    Форма «Ишни якунлаш» подтягивает ставки выбранного товара, чтобы работник
    выбрал операцию (иначе при нескольких ставках подтверждение падает с
    labor_rate_missing). Раньше LaborRateViewSet был закрыт FinancialDataPermission,
    и рабочий получал 403 — операцию выбрать не мог.
    """

    def setUp(self):
        self.company = Company.objects.create(name='AccessCo', is_active=True)
        self.owner = User.objects.create_user(username='acc_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='acc_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.admin = User.objects.create_user(username='acc_admin', password='p',
                                              role=User.Role.ADMIN, company=self.company)
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('0'), unit='dona')
        self.rate = LaborRate.objects.create(
            company=self.company, product=self.product,
            operation=LaborRate.OperationType.CUTTING,
            rate_per_unit=Decimal('50'), unit='dona')
        self.RATES = '/api/v1/finance/labor-rates/'

    def _client(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def test_worker_reads_rates(self):
        resp = self._client(self.worker).get(self.RATES, {'product': self.product.id})
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        rows = resp.json()['results'] if isinstance(resp.json(), dict) else resp.json()
        self.assertEqual(rows[0]['rate_per_unit'], '50.00')
        self.assertEqual(rows[0]['operation'], LaborRate.OperationType.CUTTING)

    def test_admin_reads_rates(self):
        resp = self._client(self.admin).get(self.RATES)
        self.assertEqual(resp.status_code, 200, resp.content[:200])

    def test_worker_cannot_change_rates(self):
        api = self._client(self.worker)
        self.assertEqual(api.post(self.RATES, {
            'product': self.product.id, 'operation': 'polishing',
            'rate_per_unit': '999', 'unit': 'dona'}, format='json').status_code, 403)
        self.assertEqual(api.patch(f"{self.RATES}{self.rate.id}/",
                                   {'rate_per_unit': '999'}, format='json').status_code, 403)
        self.assertEqual(api.delete(f'{self.RATES}{self.rate.id}/').status_code, 403)

    def test_owner_manages_rates(self):
        api = self._client(self.owner)
        self.assertEqual(api.patch(f'{self.RATES}{self.rate.id}/',
                                   {'rate_per_unit': '75'}, format='json').status_code, 200)
        self.rate.refresh_from_db()
        self.assertEqual(self.rate.rate_per_unit, Decimal('75.00'))
