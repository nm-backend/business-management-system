"""
Потолок зарплатной выплаты и минимальная ставка.

1. WorkerPayment с типом SALARY не может превысить начисленное (labor_cost
   подтверждённых работ) минус уже выданное — иначе баланс работника на
   странице расчётов уходил в минус, а опечатка в сумме проходила молча.
   ADVANCE/BONUS/OTHER — свободные выплаты (аванс выдаётся ДО работы).
2. LaborRate с нулевой ставкой запрещена: работа «за ноль» начисляла
   нули, владелец потом не мог выплатить зарплату по такому тарифу.
"""
from decimal import Decimal

from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APIClient

from django.db.models import Sum

from apps.accounts.models import User
from apps.companies.models import Company
from apps.finance.models import WorkerPayment
from apps.production.models import WorkRecord
from apps.warehouse.models import FinishedProduct

from apps.core.tests_race import run_parallel

PAYMENTS_URL = '/api/v1/finance/worker-payments/'
RATES_URL = '/api/v1/finance/labor-rates/'


class WorkerPaymentSalaryCapTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='CapCo', is_active=True)
        self.owner = User.objects.create_user(username='cap_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='cap_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Плита', quantity=Decimal('0'), unit='dona')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _accrue(self, cost):
        WorkRecord.objects.create(
            company=self.company, worker=self.worker, product=self.product,
            quantity=Decimal('1'), unit='dona', labor_cost=Decimal(cost),
            status=WorkRecord.WorkStatus.CONFIRMED)

    def _pay(self, amount, payment_type='salary'):
        return self.api.post(PAYMENTS_URL, {
            'worker': self.worker.id, 'amount': str(amount),
            'payment_date': timezone.localdate().isoformat(), 'payment_type': payment_type,
        }, format='json')

    def test_salary_above_accrued_is_rejected(self):
        self._accrue('100000')
        resp = self._pay('100000.01')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('amount', resp.data)

    def test_salary_without_any_accrual_is_rejected(self):
        resp = self._pay('50000')
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_salary_within_accrual_is_ok(self):
        self._accrue('100000')
        self.assertEqual(self._pay('100000').status_code, 201)

    def test_advance_is_free_even_without_accrual(self):
        """Аванс по определению выдаётся ДО работы — потолка нет."""
        resp = self._pay('50000', 'advance')
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_bonus_is_free(self):
        self.assertEqual(self._pay('50000', 'bonus').status_code, 201)

    def test_salary_twice_rejected_when_accrual_exhausted(self):
        self._accrue('100000')
        self.assertEqual(self._pay('60000').status_code, 201)
        resp = self._pay('50000')
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_salary_cap_also_on_update(self):
        self._accrue('100000')
        first = self._pay('40000')
        self.assertEqual(first.status_code, 201)
        payment_id = WorkerPayment.objects.get(worker=self.worker).id
        # Увеличение до 90 000 при начисленных 100 000 — допустимо.
        ok = self.api.patch(f'{PAYMENTS_URL}{payment_id}/', {'amount': '90000'}, format='json')
        self.assertEqual(ok.status_code, 200, ok.data)
        # Увеличение сверх начисленного — 400.
        bad = self.api.patch(f'{PAYMENTS_URL}{payment_id}/', {'amount': '150000'}, format='json')
        self.assertEqual(bad.status_code, 400, bad.data)


@skipUnlessDBFeature('has_select_for_update')
class WorkerPaymentSalaryConcurrencyTests(TransactionTestCase):
    """Проверка, что параллельные salary-платежи не позволяют переплатить."""
    reset_sequences = False

    def setUp(self):
        if not self._fixture_setup:
            pass
        self.company = Company.objects.create(name='ConcurrentCapCo', is_active=True)
        self.owner = User.objects.create_user(username='concurrent_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='concurrent_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Плита', quantity=Decimal('0'), unit='dona')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        WorkRecord.objects.create(
            company=self.company, worker=self.worker, product=self.product,
            quantity=Decimal('1'), unit='dona', labor_cost=Decimal('100'),
            status=WorkRecord.WorkStatus.CONFIRMED)

    def _pay(self, amount):
        api = APIClient()
        api.force_authenticate(self.owner)
        return api.post(PAYMENTS_URL, {
            'worker': self.worker.id, 'amount': str(amount),
            'payment_date': timezone.localdate().isoformat(), 'payment_type': 'salary',
        }, format='json')

    def test_concurrent_salary_payments_do_not_exceed_accrued(self):
        results = run_parallel(lambda index: self._pay('25').status_code, n=8)
        accepted = sum(1 for status in results if status == 201)
        self.assertEqual(accepted, 4, f'Ожидалось ровно 4 принятые выплаты, получено: {accepted}')
        self.worker.refresh_from_db()
        total_paid = WorkerPayment.objects.filter(worker=self.worker, payment_type='salary').aggregate(
            total=Sum('amount'))['total'] or Decimal('0')
        self.assertEqual(total_paid, Decimal('100'), f'Сумма выплат должна быть ровно 100, получено {total_paid}')


class LaborRateMinValueTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RateCo', is_active=True)
        self.owner = User.objects.create_user(username='rate_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Плита', quantity=Decimal('0'), unit='dona')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_zero_rate_rejected(self):
        resp = self.api.post(RATES_URL, {
            'product': self.product.id, 'operation': 'cutting',
            'rate_per_unit': '0', 'unit': 'dona',
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('rate_per_unit', resp.data)

    def test_positive_rate_ok(self):
        resp = self.api.post(RATES_URL, {
            'product': self.product.id, 'operation': 'cutting',
            'rate_per_unit': '0.01', 'unit': 'dona',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
