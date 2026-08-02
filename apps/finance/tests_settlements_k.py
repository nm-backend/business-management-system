"""
Расчёты с работниками: начислено, выплачено, остаток.

Вкладка «Оплата работников» показывала только сами выплаты. Работник, который
выполнил подтверждённые работы и денег ещё не получил, в ней не появлялся —
владелец не видел, кому и сколько должен. Отсюда замечание тестировщика
«работы произведены, а тут пусто».

Ключевое требование — согласованность: сумма остатков по работникам должна
совпадать с показателем «Долги работникам» на дашборде, иначе два экрана
показывали бы разные долги.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.finance.models import WorkerPayment
from apps.production.models import WorkRecord
from apps.warehouse.models import FinishedProduct

SETTLEMENTS = '/api/v1/finance/worker-payments/settlements/'
ANALYTICS = '/api/v1/reports/analytics/owner/'


class WorkerSettlementsTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='SettleCo', is_active=True)
        self.owner = User.objects.create_user(username='set_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.ivan = User.objects.create_user(username='set_ivan', password='p', full_name='Иван',
                                             role=User.Role.WORKER, company=self.company)
        self.pyotr = User.objects.create_user(username='set_pyotr', password='p', full_name='Пётр',
                                              role=User.Role.WORKER, company=self.company)
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Плита', quantity=Decimal('0'), unit='dona')

        # Иван: начислено 50 000, выплачено 20 000 -> должны 30 000
        self._work(self.ivan, '30000')
        self._work(self.ivan, '20000')
        WorkerPayment.objects.create(company=self.company, worker=self.ivan,
                                     amount=Decimal('20000'), payment_date=timezone.localdate())
        # Пётр: начислено 15 000, не выплачено ничего
        self._work(self.pyotr, '15000')
        # Неподтверждённая работа в расчёт не идёт
        self._work(self.pyotr, '99999', status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION)

        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _work(self, worker, cost, status=WorkRecord.WorkStatus.CONFIRMED):
        return WorkRecord.objects.create(
            company=self.company, worker=worker, product=self.product,
            quantity=Decimal('1'), unit='dona', labor_cost=Decimal(cost), status=status)

    def rows(self):
        resp = self.api.get(SETTLEMENTS)
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        return resp.json()

    def test_accrued_paid_and_balance_per_worker(self):
        data = self.rows()
        by_name = {row['worker_name']: row for row in data['results']}
        self.assertEqual(Decimal(str(by_name['Иван']['accrued'])), Decimal('50000'))
        self.assertEqual(Decimal(str(by_name['Иван']['paid'])), Decimal('20000'))
        self.assertEqual(Decimal(str(by_name['Иван']['balance'])), Decimal('30000'))
        self.assertEqual(Decimal(str(by_name['Пётр']['accrued'])), Decimal('15000'))
        self.assertEqual(Decimal(str(by_name['Пётр']['paid'])), Decimal('0'))
        self.assertEqual(Decimal(str(by_name['Пётр']['balance'])), Decimal('15000'))

    def test_worker_without_payments_is_present(self):
        """Ровно то, чего не хватало: работник без выплат тоже в списке."""
        names = [row['worker_name'] for row in self.rows()['results']]
        self.assertIn('Пётр', names)

    def test_totals_match_dashboard_worker_debts(self):
        """Два экрана не должны показывать разный долг."""
        total_balance = Decimal(str(self.rows()['total_balance']))
        analytics = self.api.get(ANALYTICS, {'period': 'year'})
        self.assertEqual(analytics.status_code, 200)
        self.assertEqual(total_balance, Decimal(str(analytics.json()['worker_debts'])))

    def test_unconfirmed_work_is_not_accrued(self):
        by_name = {row['worker_name']: row for row in self.rows()['results']}
        self.assertEqual(Decimal(str(by_name['Пётр']['accrued'])), Decimal('15000'))

    def test_only_own_company(self):
        other = Company.objects.create(name='Чужая', is_active=True)
        stranger = User.objects.create_user(username='set_stranger', password='p',
                                            role=User.Role.WORKER, company=other)
        WorkRecord.objects.create(company=other, worker=stranger, product=self.product,
                                  quantity=Decimal('1'), unit='dona',
                                  labor_cost=Decimal('777777'),
                                  status=WorkRecord.WorkStatus.CONFIRMED)
        names = [row['worker_name'] for row in self.rows()['results']]
        self.assertNotIn(stranger.username, names)
        self.assertEqual(Decimal(str(self.rows()['total_accrued'])), Decimal('65000'))

    def test_worker_cannot_read_settlements(self):
        api = APIClient()
        api.force_authenticate(self.ivan)
        self.assertEqual(api.get(SETTLEMENTS).status_code, 403)
