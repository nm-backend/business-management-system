"""
Заработок работника: этот/прошлый месяц и свои выплаты.

Макет «Менинг иш ҳақим» показывает разрез по месяцам и историю выплат.
Список /finance/worker-payments/ работнику закрыт, поэтому выплаты отдаём
в my_earnings — строго свои, без чужих сумм.
"""
from datetime import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.finance.models import WorkerPayment
from apps.production.models import WorkRecord
from apps.warehouse.models import FinishedProduct, UnitChoices

URL = '/api/v1/production/works/my_earnings/'


class WorkerEarningsPeriodTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='EarnCo')
        cls.owner = User.objects.create_user(
            username='earn_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='earn_worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )
        cls.other = User.objects.create_user(
            username='earn_other', password='pw', role=User.Role.WORKER, company=cls.company,
        )
        cls.product = FinishedProduct.objects.create(
            company=cls.company, name='Столешница', unit=UnitChoices.IZDELIE,
            quantity=Decimal('1'),
        )

        today = timezone.localdate()
        month_start = today.replace(day=1)
        if month_start.month == 1:
            last_day = month_start.replace(year=month_start.year - 1, month=12, day=15)
        else:
            last_day = month_start.replace(month=month_start.month - 1, day=15)
        this_at = timezone.now()
        last_at = timezone.make_aware(datetime.combine(last_day, datetime.min.time()))

        WorkRecord.objects.create(
            company=cls.company, worker=cls.worker, product=cls.product,
            quantity=Decimal('2'), unit='izdelie',
            status=WorkRecord.WorkStatus.CONFIRMED,
            labor_cost=Decimal('300.00'), confirmed_at=this_at,
        )
        WorkRecord.objects.create(
            company=cls.company, worker=cls.worker, product=cls.product,
            quantity=Decimal('1'), unit='izdelie',
            status=WorkRecord.WorkStatus.CONFIRMED,
            labor_cost=Decimal('150.00'), confirmed_at=last_at,
        )
        WorkRecord.objects.create(
            company=cls.company, worker=cls.other, product=cls.product,
            quantity=Decimal('9'), unit='izdelie',
            status=WorkRecord.WorkStatus.CONFIRMED,
            labor_cost=Decimal('999.00'), confirmed_at=this_at,
        )
        WorkerPayment.objects.create(
            company=cls.company, worker=cls.worker, amount=Decimal('80.00'),
            payment_date=today, payment_type='salary',
        )
        WorkerPayment.objects.create(
            company=cls.company, worker=cls.other, amount=Decimal('500.00'),
            payment_date=today, payment_type='bonus',
        )

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def test_this_and_last_month_and_own_payments(self):
        data = self.api_as(self.worker).get(URL).data
        self.assertEqual(Decimal(str(data['this_month'])), Decimal('300.00'))
        self.assertEqual(Decimal(str(data['last_month'])), Decimal('150.00'))
        self.assertEqual(Decimal(str(data['total_earned'])), Decimal('450.00'))
        self.assertEqual(Decimal(str(data['paid_out'])), Decimal('80.00'))
        self.assertEqual(len(data['payments']), 1)
        self.assertEqual(Decimal(str(data['payments'][0]['amount'])), Decimal('80.00'))
        self.assertEqual(data['payments'][0]['payment_type'], 'salary')
        body = str(data)
        self.assertNotIn('999', body)
        self.assertNotIn('500', body)

    def test_admin_still_denied(self):
        admin = User.objects.create_user(
            username='earn_admin', password='pw', role=User.Role.ADMIN, company=self.company,
        )
        self.assertEqual(self.api_as(admin).get(URL).status_code, 403)
