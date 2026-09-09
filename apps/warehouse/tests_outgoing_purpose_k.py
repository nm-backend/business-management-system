"""
Назначение расхода и привязка к заказу (макет «Материални ишлатиш»).

В макете расход обязательно объясняется: «Қайси мақсадда — Ишлаб чиқариш» и
«Буюртма №1256 - Ошхона столешницаси», а в истории движения видно, на какой
заказ ушло сырьё. Поле related_order в модели существовало, но ручной
расход его не заполнял: списание было анонимным.
"""
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.orders.models import Order
from apps.warehouse.models import RawMaterial, StockMovement


class OutgoingPurposeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='PurposeCo')
        cls.owner = User.objects.create_user(
            username='pp_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='pp_worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )
        cls.material = RawMaterial.objects.create(
            company=cls.company, name='Гранит', unit='m2', quantity=Decimal('100'),
        )
        cls.client_obj = Client.objects.create(company=cls.company, name='Акбаров')
        cls.order = Order.objects.create(
            company=cls.company, client=cls.client_obj, custom_product_name='Столешница',
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('1000.00'),
            deadline=timezone.now() + timezone.timedelta(days=2),
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.url = f'/api/v1/warehouse/raw-materials/{self.material.id}/outgoing/'

    def _last_movement(self):
        return StockMovement.objects.filter(material=self.material).latest('created_at')

    def test_purpose_and_order_saved(self):
        response = self.api.post(self.url, {
            'quantity': '8.50', 'purpose': 'production', 'order': self.order.id,
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)

        movement = self._last_movement()
        self.assertEqual(movement.purpose, 'production')
        self.assertEqual(movement.related_order_id, self.order.id)
        self.assertEqual(movement.quantity, Decimal('8.500'))

    def test_history_exposes_purpose_and_order(self):
        self.api.post(self.url, {
            'quantity': '2', 'purpose': 'sample', 'order': self.order.id,
        }, format='json')
        rows = self.api.get('/api/v1/warehouse/stock-movements/').data
        rows = rows['results'] if 'results' in rows else rows
        row = rows[0]
        self.assertEqual(row['purpose'], 'sample')
        self.assertEqual(row['related_order'], self.order.id)

    def test_foreign_order_rejected(self):
        """Заказ чужой компании нельзя привязать к своему расходу."""
        other = Company.objects.create(name='OtherPurposeCo')
        other_client = Client.objects.create(company=other, name='Чужой')
        foreign_order = Order.objects.create(
            company=other, client=other_client, custom_product_name='Чужой заказ',
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('10.00'),
            deadline=timezone.now() + timezone.timedelta(days=1),
        )
        response = self.api.post(self.url, {
            'quantity': '1', 'purpose': 'production', 'order': foreign_order.id,
        }, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('100.000'), 'склад не должен измениться')

    def test_outgoing_without_purpose_still_works(self):
        """Обратная совместимость: старые формы шлют расход без назначения."""
        response = self.api.post(self.url, {'quantity': '5'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        movement = self._last_movement()
        self.assertEqual(movement.purpose, '')
        self.assertIsNone(movement.related_order_id)

    def test_unknown_purpose_rejected(self):
        response = self.api.post(self.url, {'quantity': '1', 'purpose': 'нечто'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_worker_cannot_write_off(self):
        api = APIClient()
        api.force_authenticate(self.worker)
        response = api.post(self.url, {'quantity': '1', 'purpose': 'production'}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_manual_write_off_does_not_change_order_cost(self):
        """
        Ручной расход по заказу не должен влиять на себестоимость заказа.

        Себестоимость считается по подтверждённому производству; если бы
        ручное списание попадало в неё, владелец увидел бы двойной расход.
        """
        cost_before = self.order.cost_price
        self.api.post(self.url, {
            'quantity': '10', 'purpose': 'production', 'order': self.order.id,
        }, format='json')
        self.order.refresh_from_db()
        self.assertEqual(self.order.cost_price, cost_before)


class RelatedOrderFKTests(TestCase):
    """related_order — честный FK: целостность, SET_NULL, обратный доступ."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='FKCo')
        cls.owner = User.objects.create_user(
            username='fk_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.material = RawMaterial.objects.create(
            company=cls.company, name='Мрамор', unit='m2', quantity=Decimal('50'),
        )
        cls.client_obj = Client.objects.create(company=cls.company, name='Хакимов')
        cls.order = Order.objects.create(
            company=cls.company, client=cls.client_obj, custom_product_name='Подоконник',
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('500.00'),
            deadline=timezone.now() + timezone.timedelta(days=2),
        )

    def _move(self, **kw):
        args = dict(
            company=self.company, material=self.material,
            movement_type=StockMovement.MovementType.OUTGOING,
            quantity=Decimal('3'), purpose='production',
        )
        args.update(kw)
        return StockMovement.objects.create(**args)

    def test_bogus_order_id_rejected_by_database(self):
        # PG бросает сразу на INSERT, SQLite откладывает проверку FK до
        # коммита — дёргаем check_constraints явно; внутренняя atomic-блок
        # откатывает битую строку сейвпоинтом, teardown остаётся чистым.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._move(related_order_id=999999)
                connection.check_constraints()

    def test_order_delete_keeps_movement_with_null_link(self):
        movement = self._move(related_order=self.order)
        self.order.delete()
        movement.refresh_from_db()
        self.assertIsNone(movement.related_order_id)

    def test_filter_and_reverse_accessor(self):
        movement = self._move(related_order=self.order)
        self.assertIn(movement, StockMovement.objects.filter(related_order_id=self.order.id))
        self.assertIn(movement, self.order.stock_movements.all())
