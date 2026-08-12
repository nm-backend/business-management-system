"""
Арифметика финансовых показателей владельца.

Числа подобраны так, чтобы каждая ошибка меняла результат однозначно.
Проверяется и то, что «Чистая прибыль» на карточке и на графике —
одно и то же число: раньше график не вычитал выплаты работникам.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client, Payment
from apps.companies.models import Company
from apps.finance.models import Expense, ExpenseCategory, WorkerPayment
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct

ANALYTICS = '/api/v1/reports/analytics/owner/'
TIMELINE = '/api/v1/reports/analytics/revenue-timeline/'


class OwnerFinanceMathTests(TestCase):
    """
    Сценарий одного месяца:
        поступления от клиента     120 000
        себестоимость выданного     3 * 10 000 = 30 000
        расходы (аренда)            20 000
        выплата работнику           15 000
    Ожидания:
        валовая прибыль = 120 000 - 30 000            =  90 000
        чистая прибыль  = 90 000 - 20 000 - 15 000    =  55 000
        касса           = 120 000 - 20 000 - 15 000   =  85 000
    """
    def setUp(self):
        self.today = timezone.localdate()
        self.company = Company.objects.create(name='MathCo', is_active=True)
        self.owner = User.objects.create_user(username='math_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='math_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        client = Client.objects.create(company=self.company, name='Клиент')
        product = FinishedProduct.objects.create(
            company=self.company, name='Плита', quantity=Decimal('10'),
            unit='dona', cost_price=Decimal('10000'))

        Payment.objects.create(company=self.company, client=client, amount=Decimal('120000'),
                               payment_method='cash', payment_date=timezone.now())
        order = Order.objects.create(
            company=self.company, client=client, product=product,
            quantity=Decimal('3'), unit='dona', total_amount=Decimal('150000'),
            deadline=timezone.now() + datetime.timedelta(days=3))
        order.status = Order.Status.DELIVERED
        # save-хук сам проставляет delivered_at и снимок себестоимости:
        # ручная установка delivered_at в обход хука оставила бы cost_price=0.
        order.save(update_fields=['status'])

        Expense.objects.create(company=self.company, category=ExpenseCategory.RENT,
                               amount=Decimal('20000'), date=self.today)
        WorkerPayment.objects.create(company=self.company, worker=self.worker,
                                     amount=Decimal('15000'), payment_date=self.today)

        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def analytics(self, period='month'):
        resp = self.api.get(ANALYTICS, {'period': period})
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        return resp.json()

    def test_every_figure_matches_the_scenario(self):
        d = self.analytics()
        self.assertEqual(Decimal(str(d['revenue'])), Decimal('120000'))
        self.assertEqual(Decimal(str(d['cost_of_goods'])), Decimal('30000'))
        self.assertEqual(Decimal(str(d['gross_profit'])), Decimal('90000'))
        self.assertEqual(Decimal(str(d['expenses_total'])), Decimal('20000'))
        self.assertEqual(Decimal(str(d['worker_payments'])), Decimal('15000'))
        self.assertEqual(Decimal(str(d['net_profit'])), Decimal('55000'))
        self.assertEqual(Decimal(str(d['cash'])), Decimal('85000'))

    def test_net_profit_is_gross_minus_expenses_minus_payouts(self):
        """Инвариант: показатели не могут противоречить друг другу."""
        d = self.analytics()
        expected = (Decimal(str(d['gross_profit']))
                    - Decimal(str(d['expenses_total']))
                    - Decimal(str(d['worker_payments'])))
        self.assertEqual(Decimal(str(d['net_profit'])), expected)

    def test_timeline_profit_equals_card_profit(self):
        """
        График «Выручка и прибыль» и карточка «Чистая прибыль» показывают
        одну и ту же величину. Раньше график не вычитал выплаты работникам:
        карточка 55 000, график 70 000 — расхождение в 15 000.
        """
        resp = self.api.get(TIMELINE)
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        timeline = resp.json()
        card = self.analytics()

        self.assertIn(Decimal(str(card['revenue'])),
                      [Decimal(str(v)) for v in timeline['revenues']])
        self.assertIn(Decimal(str(card['net_profit'])),
                      [Decimal(str(v)) for v in timeline['net_profits']],
                      f"график: {timeline['net_profits']}, карточка: {card['net_profit']}")

    def test_timeline_does_not_split_one_month_in_two(self):
        """
        Выручка берётся из DateTimeField, расходы — из DateField. Если
        группировать их по месяцу без приведения к одному типу, июль из
        платежей и июль из расходов оказываются РАЗНЫМИ ключами — месяц
        задваивается, а прибыль считается против нулевых расходов.
        """
        resp = self.api.get(TIMELINE)
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        labels = resp.json()['labels']
        self.assertEqual(len(labels), len(set(labels)), f'месяцы задвоились: {labels}')
        self.assertEqual(len(labels), 1, f'ожидался один месяц, получено: {labels}')


class PeriodBoundariesTests(TestCase):
    """Границы периода включаются, соседние дни — нет."""
    def setUp(self):
        self.company = Company.objects.create(name='BoundCo', is_active=True)
        self.owner = User.objects.create_user(username='bound_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='К')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def pay(self, when, amount):
        Payment.objects.create(company=self.company, client=self.client_obj,
                               amount=Decimal(amount), payment_method='cash',
                               payment_date=when)

    def test_first_and_last_day_of_month_are_counted(self):
        today = timezone.localdate()
        first = today.replace(day=1)
        start = timezone.make_aware(datetime.datetime.combine(first, datetime.time(0, 5)))
        self.pay(start, '1000')                      # первый день месяца
        self.pay(timezone.now(), '2000')             # сегодня
        # день до начала месяца в период попасть не должен
        before = timezone.make_aware(
            datetime.datetime.combine(first - datetime.timedelta(days=1), datetime.time(23, 55)))
        self.pay(before, '999999')

        resp = self.api.get(ANALYTICS, {'period': 'month'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Decimal(str(resp.json()['revenue'])), Decimal('3000'))
