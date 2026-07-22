"""
Регрессия межтенантных записей на UPDATE в финансах (аудит K, находки #3/#4).

perform_create проверял принадлежность FK компании, но perform_update
отсутствовал — PATCH позволял перепривязать worker/product к объекту ЧУЖОЙ
компании (IDOR-запись + утечка чужого имени через *_name в ответе).
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.finance.models import LaborRate, WorkerPayment
from apps.warehouse.models import FinishedProduct


class _FinanceTwoCompanies(TestCase):
    def setUp(self):
        self.a = Company.objects.create(name='FA')
        self.b = Company.objects.create(name='FB')
        self.owner_a = User.objects.create_user(username='k_foa', password='p',
                                                role=User.Role.OWNER, company=self.a)
        self.worker_a = User.objects.create_user(username='k_fwa', password='p',
                                                 role=User.Role.WORKER, company=self.a)
        self.worker_b = User.objects.create_user(username='k_fwb', password='p',
                                                 role=User.Role.WORKER, company=self.b)
        self.product_a = FinishedProduct.objects.create(company=self.a, name='FPA', quantity=Decimal('1'))
        self.product_b = FinishedProduct.objects.create(company=self.b, name='FPB', quantity=Decimal('1'))

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c


class WorkerPaymentUpdateIDORTests(_FinanceTwoCompanies):
    def test_patch_worker_to_foreign_company_rejected(self):
        wp = WorkerPayment.objects.create(
            company=self.a, worker=self.worker_a, amount=Decimal('100'),
            payment_date=datetime.date(2026, 1, 1),
            payment_type=WorkerPayment.PaymentType.SALARY, created_by=self.owner_a)
        resp = self.api(self.owner_a).patch(
            f'/api/v1/finance/worker-payments/{wp.id}/',
            {'worker': self.worker_b.id}, format='json')
        self.assertEqual(resp.status_code, 403)
        wp.refresh_from_db()
        self.assertEqual(wp.worker_id, self.worker_a.id)  # не перепривязано к чужому

    def test_patch_worker_to_own_company_ok(self):
        w2 = User.objects.create_user(username='k_fwa2', password='p',
                                      role=User.Role.WORKER, company=self.a)
        wp = WorkerPayment.objects.create(
            company=self.a, worker=self.worker_a, amount=Decimal('100'),
            payment_date=datetime.date(2026, 1, 1),
            payment_type=WorkerPayment.PaymentType.SALARY, created_by=self.owner_a)
        resp = self.api(self.owner_a).patch(
            f'/api/v1/finance/worker-payments/{wp.id}/',
            {'worker': w2.id}, format='json')
        self.assertEqual(resp.status_code, 200)
        wp.refresh_from_db()
        self.assertEqual(wp.worker_id, w2.id)


class LaborRateUpdateIDORTests(_FinanceTwoCompanies):
    def test_patch_product_to_foreign_company_rejected(self):
        lr = LaborRate.objects.create(
            company=self.a, product=self.product_a,
            operation=LaborRate.OperationType.CUTTING,
            rate_per_unit=Decimal('5'), unit='dona')
        resp = self.api(self.owner_a).patch(
            f'/api/v1/finance/labor-rates/{lr.id}/',
            {'product': self.product_b.id}, format='json')
        self.assertEqual(resp.status_code, 403)
        lr.refresh_from_db()
        self.assertEqual(lr.product_id, self.product_a.id)  # не перепривязано к чужому
