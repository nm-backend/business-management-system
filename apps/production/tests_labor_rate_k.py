"""
Начисление работнику: ноль больше не начисляется молча.

Воспроизведено полной цепочкой заказ -> задача -> принятие -> сдача работы ->
подтверждение: склад пополнялся (0 -> 5, движение production_in), а работнику
начислялось 0.00, потому что для товара не было ставки. Ни ошибки, ни
предупреждения: администратор видел «подтверждено» и был уверен, что всё в
порядке, а работник не получал ничего.

Решение владельца: подтверждение без ставки запрещено, ставка задаётся в
карточке товара рядом с себестоимостью и ценой продажи.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.finance.models import LaborRate
from apps.production.models import WorkRecord
from apps.warehouse.models import FinishedProduct, StockMovement

WORKS = '/api/v1/production/works/'
PRODUCTS = '/api/v1/warehouse/finished-products/'


class ConfirmRequiresLaborRateTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RateCo', is_active=True)
        self.owner = User.objects.create_user(username='rate_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='rate_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('0'), unit='dona')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _work(self):
        return WorkRecord.objects.create(
            company=self.company, worker=self.worker, product=self.product,
            quantity=Decimal('5'), unit='dona',
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION)

    def test_confirm_without_rate_is_refused(self):
        work = self._work()
        resp = self.api.post(f'{WORKS}{work.id}/confirm/')
        self.assertEqual(resp.status_code, 400, resp.content[:200])
        self.assertEqual(resp.json().get('code'), 'labor_rate_missing')
        self.assertIn('Столешница', resp.json()['detail'])

    def test_refused_confirmation_changes_nothing(self):
        """Отказ обязан быть чистым: ни склада, ни статуса, ни начисления."""
        work = self._work()
        self.api.post(f'{WORKS}{work.id}/confirm/')
        work.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(work.status, WorkRecord.WorkStatus.AWAITING_CONFIRMATION)
        self.assertEqual(work.labor_cost, Decimal('0.00'))
        self.assertEqual(self.product.quantity, Decimal('0.000'))
        self.assertFalse(StockMovement.objects.filter(product=self.product).exists())

    def test_confirm_with_rate_accrues_and_stocks(self):
        LaborRate.objects.create(company=self.company, product=self.product,
                                 operation=LaborRate.OperationType.OTHER,
                                 rate_per_unit=Decimal('1500'), unit='dona')
        work = self._work()
        resp = self.api.post(f'{WORKS}{work.id}/confirm/')
        self.assertEqual(resp.status_code, 200, resp.content[:200])

        work.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(work.labor_cost, Decimal('7500.00'), '5 шт * 1500')
        self.assertEqual(self.product.quantity, Decimal('5.000'))
        self.assertTrue(StockMovement.objects.filter(
            product=self.product, movement_type=StockMovement.MovementType.PRODUCTION_IN).exists())

    def test_owner_can_still_set_amount_by_hand(self):
        """Явно указанная владельцем сумма ставку не требует."""
        work = self._work()
        resp = self.api.post(f'{WORKS}{work.id}/confirm/', {'labor_cost': '2000'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        work.refresh_from_db()
        self.assertEqual(work.labor_cost, Decimal('2000.00'))

    def test_accrual_reaches_worker_settlements(self):
        """Начисленное обязано дойти до расчётов с работниками и до дашборда."""
        LaborRate.objects.create(company=self.company, product=self.product,
                                 operation=LaborRate.OperationType.OTHER,
                                 rate_per_unit=Decimal('1000'), unit='dona')
        work = self._work()
        self.api.post(f'{WORKS}{work.id}/confirm/')

        rows = self.api.get('/api/v1/finance/worker-payments/settlements/').json()
        mine = [r for r in rows['results'] if r['worker'] == self.worker.id]
        self.assertEqual(len(mine), 1, 'работник обязан появиться в расчётах')
        self.assertEqual(Decimal(str(mine[0]['accrued'])), Decimal('5000'))
        self.assertEqual(Decimal(str(mine[0]['balance'])), Decimal('5000'))

        dash = self.api.get('/api/v1/reports/analytics/owner/', {'period': 'year'}).json()
        self.assertEqual(Decimal(str(dash['worker_debts'])), Decimal('5000'),
                         'дашборд обязан показывать тот же долг')


class LaborRateOnProductCardTests(TestCase):
    """Ставка задаётся в карточке товара — там же, где себестоимость и цена."""

    def setUp(self):
        self.company = Company.objects.create(name='CardCo', is_active=True)
        self.owner = User.objects.create_user(username='card_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_rate_can_be_set_on_create(self):
        resp = self.api.post(PRODUCTS, {
            'name': 'Подоконник', 'quantity': '0', 'unit': 'dona', 'labor_rate': '900',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:200])
        product = FinishedProduct.objects.get(pk=resp.json()['id'])
        self.assertEqual(product.labor_rates.count(), 1)
        self.assertEqual(product.labor_rates.first().rate_per_unit, Decimal('900.00'))
        self.assertEqual(resp.json()['labor_rate'], '900.00')

    def test_rate_is_updated_not_duplicated(self):
        pid = self.api.post(PRODUCTS, {'name': 'Ступень', 'quantity': '0',
                                       'unit': 'dona', 'labor_rate': '500'},
                            format='json').json()['id']
        self.api.patch(f'{PRODUCTS}{pid}/', {'labor_rate': '750'}, format='json')
        product = FinishedProduct.objects.get(pk=pid)
        self.assertEqual(product.labor_rates.count(), 1, 'ставка одна, а не копится')
        self.assertEqual(product.labor_rates.first().rate_per_unit, Decimal('750.00'))

    def test_saving_card_without_rate_keeps_it(self):
        pid = self.api.post(PRODUCTS, {'name': 'Плита', 'quantity': '0',
                                       'unit': 'dona', 'labor_rate': '400'},
                            format='json').json()['id']
        self.api.patch(f'{PRODUCTS}{pid}/', {'name': 'Плита 2'}, format='json')
        product = FinishedProduct.objects.get(pk=pid)
        self.assertEqual(product.labor_rates.first().rate_per_unit, Decimal('400.00'))

    def test_worker_does_not_see_the_rate(self):
        pid = self.api.post(PRODUCTS, {'name': 'Плита', 'quantity': '0',
                                       'unit': 'dona', 'labor_rate': '400'},
                            format='json').json()['id']
        worker = User.objects.create_user(username='card_worker', password='p',
                                          role=User.Role.WORKER, company=self.company)
        api = APIClient()
        api.force_authenticate(worker)
        self.assertNotIn('labor_rate', api.get(f'{PRODUCTS}{pid}/').json())
