"""
COGS не уезжает между периодами из-за поздней оплаты (аудит K, находка #5).

Регрессия: себестоимость проданного (cost_of_goods) считается по delivered_at
(момент фактической выдачи), а не по updated_at. Реальная поздняя оплата бампит
updated_at, но НЕ должна выкидывать заказ из отчёта месяца выдачи.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct

UTC = datetime.timezone.utc
JUNE = datetime.datetime(2026, 6, 10, tzinfo=UTC)


class CogsPeriodAttributionTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RCOGS')
        self.owner = User.objects.create_user(username='rc_owner', password='p',
                                               role=User.Role.OWNER, company=self.company)
        self.cli = Client.objects.create(company=self.company, name='Cli')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='P', quantity=Decimal('100'), cost_price=Decimal('1000'))
        self.order = Order.objects.create(
            company=self.company, client=self.cli, product=self.product,
            quantity=Decimal('1'), unit='dona', total_amount=Decimal('1500'),
            status=Order.Status.DELIVERED)
        # Фиксируем факт выдачи в ИЮНЕ (и delivered_at, и updated_at).
        Order.objects.filter(pk=self.order.pk).update(delivered_at=JUNE, updated_at=JUNE)

    def _june_cogs(self):
        c = APIClient()
        c.force_authenticate(user=self.owner)
        resp = c.get('/api/v1/reports/analytics/owner/?date_from=2026-06-01&date_to=2026-06-30')
        assert resp.status_code == 200, resp.status_code
        return Decimal(str(resp.json()['cost_of_goods']))

    def test_delivered_at_set_on_delivery(self):
        # save-хук проставил delivered_at при создании в статусе DELIVERED.
        fresh = Order.objects.create(
            company=self.company, client=self.cli, product=self.product,
            quantity=Decimal('1'), unit='dona', total_amount=Decimal('10'),
            status=Order.Status.DELIVERED)
        self.assertIsNotNone(fresh.delivered_at)

    def test_cogs_stable_after_real_later_payment(self):
        self.assertEqual(self._june_cogs(), Decimal('1000'))

        # Реальная поздняя оплата через API (бампит updated_at на «сейчас»).
        c = APIClient()
        c.force_authenticate(user=self.owner)
        resp = c.post('/api/v1/clients/payments/', {
            'client': self.cli.id, 'order': self.order.id,
            'amount': '500', 'payment_method': 'cash',
            'payment_date': '2026-07-05T10:00:00Z',
        }, format='json')
        self.assertEqual(resp.status_code, 201)

        self.order.refresh_from_db()
        # updated_at сдвинулся на «сейчас», а delivered_at остался в июне.
        self.assertNotEqual(self.order.updated_at.date(), JUNE.date())
        self.assertEqual(self.order.delivered_at.date(), JUNE.date())

        # Июньский COGS не изменился.
        self.assertEqual(self._june_cogs(), Decimal('1000'))
