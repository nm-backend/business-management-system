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
from apps.warehouse.models import FinishedProduct, RawMaterial, Recipe, RecipeItem, StockMovement

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


class LaborRateOperationTests(TestCase):
    """
    Полный аудит: работа не знала свою операцию, и начисление брало ставку
    по алфавиту (order_by('operation') -> 'cutting'). У товара с несколькими
    ставками работник получал деньги за чужую операцию. Теперь операцию
    указывает работник, а ставка выбирается по ней.
    """

    def setUp(self):
        self.company = Company.objects.create(name='OpCo', is_active=True)
        self.owner = User.objects.create_user(username='op_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='op_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('0'), unit='dona')
        self.material = RawMaterial.objects.create(
            company=self.company, name='Гранит', quantity=Decimal('100'), unit='m2')
        self.recipe = Recipe.objects.create(company=self.company, product=self.product, name='R')
        RecipeItem.objects.create(recipe=self.recipe, material=self.material,
                                  quantity_required=Decimal('1'))
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

    def test_work_uses_rate_of_its_operation(self):
        """Полировка должна начислить по ставке полировки, а не по «алфавитной» резке."""
        self._rates()
        work = self._work(operation=LaborRate.OperationType.POLISHING)
        resp = self.api.post(f'{WORKS}{work.id}/confirm/')
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        work.refresh_from_db()
        self.assertEqual(work.labor_cost, Decimal('350.00'), '5 * 70 (полировка)')

    def test_cutting_uses_cutting_rate(self):
        self._rates()
        work = self._work(operation=LaborRate.OperationType.CUTTING)
        self.assertEqual(self.api.post(f'{WORKS}{work.id}/confirm/').status_code, 200)
        work.refresh_from_db()
        self.assertEqual(work.labor_cost, Decimal('250.00'), '5 * 50 (резка)')

    def test_work_without_operation_uses_single_rate(self):
        """Одна ставка на товар и работа без операции — как раньше."""
        LaborRate.objects.create(company=self.company, product=self.product,
                                 operation=LaborRate.OperationType.OTHER,
                                 rate_per_unit=Decimal('1500'), unit='dona')
        work = self._work()
        resp = self.api.post(f'{WORKS}{work.id}/confirm/')
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        work.refresh_from_db()
        self.assertEqual(work.labor_cost, Decimal('7500.00'))

    def test_multiple_rates_without_operation_are_not_guessed(self):
        """Несколько ставок и операция не указана — начислять нельзя наугад."""
        self._rates()
        work = self._work()
        resp = self.api.post(f'{WORKS}{work.id}/confirm/')
        self.assertEqual(resp.status_code, 400, resp.content[:200])
        self.assertEqual(resp.json().get('code'), 'labor_rate_missing')
        work.refresh_from_db()
        self.assertEqual(work.status, WorkRecord.WorkStatus.AWAITING_CONFIRMATION)

    def test_operation_saved_on_work_create(self):
        resp = self.api.post(WORKS, {
            'worker': self.worker.id, 'product': self.product.id,
            'operation': 'polishing', 'quantity': '2', 'unit': 'dona',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content[:200])
        work = WorkRecord.objects.get(pk=resp.json()['id'])
        self.assertEqual(work.operation, LaborRate.OperationType.POLISHING)

    def test_rates_can_be_filtered_by_product(self):
        self._rates()
        rows = self.api.get('/api/v1/finance/labor-rates/', {'product': self.product.id}).json()
        rows = rows['results'] if isinstance(rows, dict) else rows
        self.assertEqual(len(rows), 2)


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
