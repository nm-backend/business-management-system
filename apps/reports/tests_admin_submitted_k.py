"""
Счётчик «Сдано сегодня» на операционной панели администратора.

Это количество работ, созданных сегодня (сдача работником), а не денег
и не подтверждений — подтверждения считает awaiting_confirmation.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.core.tests_tz_compliance_k import collect_money_keys
from apps.production.models import WorkRecord
from apps.warehouse.models import FinishedProduct

ADMIN = '/api/v1/reports/analytics/admin/'


class AdminSubmittedTodayTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='SubmitCo')
        cls.owner = User.objects.create_user(
            username='st_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='st_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='st_worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )
        cls.product = FinishedProduct.objects.create(
            company=cls.company, name='Столешница', unit='sht', quantity=Decimal('1'),
        )

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def _work(self, *, days_ago=0, company=None, worker=None):
        record = WorkRecord.objects.create(
            company=company or self.company,
            worker=worker or self.worker,
            product=self.product,
            quantity=Decimal('1'),
            unit='sht',
            status=WorkRecord.WorkStatus.AWAITING_CONFIRMATION,
        )
        if days_ago:
            WorkRecord.objects.filter(pk=record.pk).update(
                created_at=timezone.now() - timedelta(days=days_ago),
            )
        return record

    def test_counts_only_todays_submissions(self):
        self._work(days_ago=0)
        self._work(days_ago=0)
        self._work(days_ago=1)
        data = self.api_as(self.admin).get(ADMIN).data
        self.assertEqual(data['submitted_today'], 2)
        self.assertEqual(data['awaiting_confirmation'], 3)

    def test_other_company_not_counted(self):
        other = Company.objects.create(name='OtherSubmitCo')
        stranger = User.objects.create_user(
            username='st_stranger', password='pw', role=User.Role.WORKER, company=other,
        )
        self._work(days_ago=0)
        self._work(days_ago=0, company=other, worker=stranger)
        data = self.api_as(self.admin).get(ADMIN).data
        self.assertEqual(data['submitted_today'], 1)

    def test_admin_payload_has_no_money(self):
        self._work()
        response = self.api_as(self.admin).get(ADMIN)
        self.assertEqual(response.status_code, 200)
        leaks = collect_money_keys(response.data)
        self.assertFalse(leaks, f'операционная аналитика отдала деньги: {leaks}')

    def test_worker_denied(self):
        self.assertEqual(self.api_as(self.worker).get(ADMIN).status_code, 403)
