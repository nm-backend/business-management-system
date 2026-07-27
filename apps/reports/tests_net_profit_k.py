"""
Чистая прибыль обязана учитывать выплаты работникам.

Было: net_profit = выручка - себестоимость - расходы. Выплаты работникам
(WorkerPayment) не вычитались вообще, хотя это реальные деньги из кассы —
прибыль была завышена ровно на сумму всех выплат за период. При этом «Касса»
в том же отчёте выплаты вычитала, то есть две цифры на одном экране
противоречили друг другу.

WorkerPayment и Expense — разные журналы: расход заводят вручную, выплата
создаётся при выдаче денег работнику. Двойного учёта нет.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client, Payment
from apps.companies.models import Company
from apps.finance.models import Expense, ExpenseCategory, WorkerPayment

UTC = datetime.timezone.utc
PERIOD = '?date_from=2026-06-01&date_to=2026-06-30'
URL = '/api/v1/reports/analytics/owner/'


class NetProfitTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='NPCo', is_active=True)
        self.owner = User.objects.create_user(username='np_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='np_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.cli = Client.objects.create(company=self.company, name='К')
        # Выручка 10 000
        Payment.objects.create(company=self.company, client=self.cli, amount=Decimal('10000'),
                               payment_date=datetime.datetime(2026, 6, 10, tzinfo=UTC),
                               payment_method='cash')
        # Расходы 2 000
        Expense.objects.create(company=self.company, category=ExpenseCategory.RENT,
                               amount=Decimal('2000'), date=datetime.date(2026, 6, 11))

    def _report(self):
        c = APIClient()
        c.force_authenticate(self.owner)
        resp = c.get(URL + PERIOD)
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_without_worker_payments(self):
        data = self._report()
        self.assertEqual(Decimal(str(data['net_profit'])), Decimal('8000'))
        self.assertEqual(Decimal(str(data['worker_payments'])), Decimal('0'))

    def test_worker_payments_reduce_net_profit(self):
        WorkerPayment.objects.create(company=self.company, worker=self.worker,
                                     amount=Decimal('3000'),
                                     payment_date=datetime.date(2026, 6, 15),
                                     created_by=self.owner)
        data = self._report()
        self.assertEqual(Decimal(str(data['worker_payments'])), Decimal('3000'))
        # 10000 выручки - 0 себестоимости - 2000 расходов - 3000 выплат
        self.assertEqual(Decimal(str(data['net_profit'])), Decimal('5000'))

    def test_net_profit_and_cash_agree_on_worker_payments(self):
        """Обе цифры на экране должны учитывать выплаты одинаково."""
        WorkerPayment.objects.create(company=self.company, worker=self.worker,
                                     amount=Decimal('3000'),
                                     payment_date=datetime.date(2026, 6, 15),
                                     created_by=self.owner)
        data = self._report()
        # Касса за всё время: 10000 - 2000 - 3000
        self.assertEqual(Decimal(str(data['cash'])), Decimal('5000'))
        self.assertEqual(Decimal(str(data['net_profit'])), Decimal('5000'))

    def test_payment_of_other_company_does_not_leak(self):
        other = Company.objects.create(name='Чужая', is_active=True)
        other_worker = User.objects.create_user(username='np_other_w', password='p',
                                                role=User.Role.WORKER, company=other)
        WorkerPayment.objects.create(company=other, worker=other_worker,
                                     amount=Decimal('9999'),
                                     payment_date=datetime.date(2026, 6, 15))
        data = self._report()
        self.assertEqual(Decimal(str(data['worker_payments'])), Decimal('0'))
        self.assertEqual(Decimal(str(data['net_profit'])), Decimal('8000'))
