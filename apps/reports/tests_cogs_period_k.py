"""
COGS не уезжает между периодами из-за поздней оплаты (аудит K, находка #5).

Регрессия: себестоимость проданного (cost_of_goods) считается по delivered_at
(момент фактической выдачи), а не по updated_at. Реальная поздняя оплата бампит
updated_at, но НЕ должна выкидывать заказ из отчёта месяца выдачи.
"""
import datetime
from decimal import Decimal

from django.db import models as django_models
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

    def test_cogs_snapshot_frozen_at_delivery(self):
        """Переоценка товара после выдачи не переписывает COGS выданного заказа."""
        self.order.refresh_from_db()
        self.assertEqual(self.order.cost_price, Decimal('1000'))
        # Товар переоценили после выдачи (новый приход, пересчёт по рецепту).
        self.product.cost_price = Decimal('9000')
        self.product.save(update_fields=['cost_price'])
        # COGS за июнь всё ещё по снимку на момент выдачи.
        self.assertEqual(self._june_cogs(), Decimal('1000'))

    def test_historical_cogs_survives_weighted_average_change(self):
        """
        Исторический COGS не пересчитывается после смены WAC.

        Старый заказ выдан при себестоимости 50 за шт. Затем приход меняет
        средневзвешенную себестоимость товара (WAC) до 80 за шт. COGS уже
        выданного заказа обязан остаться 50 × quantity, а не пересчитаться
        в 80 — иначе поздний приход задним числом меняет прибыль прошлых
        периодов.
        """
        product = FinishedProduct.objects.create(
            company=self.company, name='WAC', quantity=Decimal('0'), cost_price=Decimal('50'))
        # Приход 10 шт по 50 → WAC = 50.
        from apps.warehouse.services import record_incoming
        record_incoming(target=product, quantity=Decimal('10'), price_per_unit=Decimal('50'))
        order = Order.objects.create(
            company=self.company, client=self.cli, product=product,
            quantity=Decimal('4'), unit='dona', total_amount=Decimal('400'),
            status=Order.Status.DELIVERED)
        Order.objects.filter(pk=order.pk).update(delivered_at=JUNE, updated_at=JUNE)
        self.assertEqual(order.cost_price, Decimal('50'))
        self.assertEqual(self._june_cogs_for(product), Decimal('200'))  # 4 × 50

        # Поздний приход дороже → WAC растёт до 80.
        record_incoming(target=product, quantity=Decimal('10'), price_per_unit=Decimal('110'))
        product.refresh_from_db()
        self.assertEqual(product.cost_price, Decimal('80'))  # (10*50 + 10*110)/20 = 80

        # Исторический COGS не изменился: 4 × 50 = 200, а не 4 × 80 = 320.
        self.assertEqual(self._june_cogs_for(product), Decimal('200'))

    def _june_cogs_for(self, product):
        from django.db.models import Sum
        from apps.orders.models import Order as OrderModel
        return (
            OrderModel.objects.filter(
                company=self.company, product=product,
                status=OrderModel.Status.DELIVERED,
                delivered_at__date__range=('2026-06-01', '2026-06-30'),
            ).aggregate(
                s=Sum(django_models.ExpressionWrapper(
                    django_models.F('quantity') * django_models.F('cost_price'),
                    output_field=django_models.DecimalField(max_digits=15, decimal_places=2),
                ))
            )['s'] or Decimal('0')
        )

    def test_custom_product_contributes_zero_cogs(self):
        """Ручная позиция без товара не завышает прибыль: COGS по ней 0."""
        Order.objects.create(
            company=self.company, client=self.cli,
            custom_product_name='Кованые ворота', quantity=Decimal('2'),
            unit='dona', total_amount=Decimal('4000'),
            status=Order.Status.DELIVERED)
        # В июне: 1 товарный заказ (снимок 1000) + 1 ручной (0).
        self.assertEqual(self._june_cogs(), Decimal('1000'))
