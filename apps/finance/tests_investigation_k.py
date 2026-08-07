"""
Расследование: смена работника в выплате и отсутствие id в ответе создания.

Воспроизведено до правки:
1. PATCH выплаты менял worker: потолок зарплаты обходился — выплата создавалась
   под начисление одного работника, а перевешивалась на другого с пустым балансом.
2. Ответ создания выплаты не содержал id: клиент не мог сразу PATCH/удалить её.
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

PAYMENTS_URL = '/api/v1/finance/worker-payments/'


class WorkerPaymentUpdateTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='WpCo', is_active=True)
        self.owner = User.objects.create_user(username='wp_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='wp_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.worker2 = User.objects.create_user(username='wp_worker2', password='p',
                                                role=User.Role.WORKER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _accrue(self, worker, cost):
        product = FinishedProduct.objects.create(
            company=self.company, name='Плита', quantity=Decimal('0'), unit='dona')
        WorkRecord.objects.create(
            company=self.company, worker=worker, product=product,
            quantity=Decimal('1'), unit='dona', labor_cost=Decimal(cost),
            status=WorkRecord.WorkStatus.CONFIRMED)

    def test_change_worker_after_payment_rejected(self):
        self._accrue(self.worker, '100000')
        resp = self.api.post(PAYMENTS_URL, {
            'worker': self.worker.id, 'amount': '100000',
            'payment_date': timezone.localdate().isoformat(), 'payment_type': 'salary',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        payment_id = resp.json()['id']

        resp = self.api.patch(f'{PAYMENTS_URL}{payment_id}/', {'worker': self.worker2.id},
                              format='json')
        self.assertEqual(resp.status_code, 403, resp.data)
        self.assertEqual(WorkerPayment.objects.get(pk=payment_id).worker_id, self.worker.id)

    def test_create_response_contains_id(self):
        resp = self.api.post(PAYMENTS_URL, {
            'worker': self.worker.id, 'amount': '50000',
            'payment_date': timezone.localdate().isoformat(), 'payment_type': 'advance',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertIn('id', resp.data)
        self.assertTrue(WorkerPayment.objects.filter(pk=resp.data['id']).exists())
