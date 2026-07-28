"""
Приход на склад и архивация.

Приход раньше считался в браузере: страница читала остаток, прибавляла и слала
PATCH с АБСОЛЮТНЫМ значением. Два прихода со страницы, открытой до первого из
них, затирали друг друга — поставка исчезала. Здесь приход считает сервер, и
тест воспроизводит именно тот сценарий: два запроса из одного исходного
состояния должны сложиться.

Заодно проверяется то, чего не было вовсе: движение StockMovement.INCOMING
(тип был объявлен и не создавался нигде), средневзвешенная себестоимость
(поле показывалось владельцу и всегда оставалось нулём) и приход у готовой
продукции (её остаток рос только через подтверждённое производство).
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.warehouse.models import FinishedProduct, RawMaterial, StockMovement

MATERIALS = '/api/v1/warehouse/raw-materials/'
PRODUCTS = '/api/v1/warehouse/finished-products/'


class _Base(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='StockCo', is_active=True)
        self.owner = User.objects.create_user(username='stock_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.admin = User.objects.create_user(username='stock_admin', password='p',
                                              role=User.Role.ADMIN, company=self.company)
        self.worker = User.objects.create_user(username='stock_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.material = RawMaterial.objects.create(
            company=self.company, name='Гранит', quantity=Decimal('10'), unit='m2',
            avg_cost_price=Decimal('100'))
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('2'), unit='dona')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def as_(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api


class IncomingTests(_Base):
    def test_incoming_adds_to_the_stock(self):
        r = self.api.post(f'{MATERIALS}{self.material.id}/incoming/',
                          {'quantity': '5'}, format='json')
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('15.000'))

    def test_two_arrivals_from_the_same_stale_state_both_land(self):
        """
        Ровно та потеря, что была раньше: страница знает остаток 10, оператор
        дважды оприходовал по 5. При счёте в браузере обе отправки слали 15 и
        одна поставка пропадала. Сервер прибавляет — должно стать 20.
        """
        for _ in range(2):
            r = self.api.post(f'{MATERIALS}{self.material.id}/incoming/',
                              {'quantity': '5'}, format='json')
            self.assertEqual(r.status_code, 200)
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('20.000'))

    def test_incoming_writes_a_stock_movement(self):
        self.api.post(f'{MATERIALS}{self.material.id}/incoming/',
                      {'quantity': '7', 'price_per_unit': '250'}, format='json')
        movement = StockMovement.objects.get(material=self.material)
        self.assertEqual(movement.movement_type, StockMovement.MovementType.INCOMING)
        self.assertEqual(movement.quantity, Decimal('7.000'))
        self.assertEqual(movement.price_per_unit, Decimal('250.00'))
        self.assertEqual(movement.company_id, self.company.id)
        self.assertEqual(movement.created_by, self.owner)

    def test_weighted_average_cost(self):
        """10 по 100 + 10 по 200 -> 150."""
        self.api.post(f'{MATERIALS}{self.material.id}/incoming/',
                      {'quantity': '10', 'price_per_unit': '200'}, format='json')
        self.material.refresh_from_db()
        self.assertEqual(self.material.avg_cost_price, Decimal('150.00'))

    def test_incoming_without_price_keeps_the_average(self):
        self.api.post(f'{MATERIALS}{self.material.id}/incoming/',
                      {'quantity': '10'}, format='json')
        self.material.refresh_from_db()
        self.assertEqual(self.material.avg_cost_price, Decimal('100.00'))

    def test_arrival_date_is_stored(self):
        today = timezone.localdate()
        self.api.post(f'{MATERIALS}{self.material.id}/incoming/',
                      {'quantity': '1', 'arrival_date': today.isoformat()}, format='json')
        self.material.refresh_from_db()
        self.assertEqual(self.material.arrival_date, today)

    def test_finished_product_can_be_received(self):
        r = self.api.post(f'{PRODUCTS}{self.product.id}/incoming/',
                          {'quantity': '3'}, format='json')
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('5.000'))
        self.assertTrue(StockMovement.objects.filter(
            product=self.product, movement_type=StockMovement.MovementType.INCOMING).exists())

    def test_admin_may_receive_but_does_not_touch_prices(self):
        """Цена — финансовое поле владельца; приход админа её не меняет."""
        r = self.as_(self.admin).post(f'{MATERIALS}{self.material.id}/incoming/',
                                      {'quantity': '10', 'price_per_unit': '999'}, format='json')
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('20.000'))
        self.assertEqual(self.material.avg_cost_price, Decimal('100.00'))

    def test_worker_cannot_receive(self):
        r = self.as_(self.worker).post(f'{MATERIALS}{self.material.id}/incoming/',
                                       {'quantity': '5'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('10.000'))

    def test_zero_and_negative_quantity_rejected(self):
        for bad in ('0', '-5'):
            r = self.api.post(f'{MATERIALS}{self.material.id}/incoming/',
                              {'quantity': bad}, format='json')
            self.assertEqual(r.status_code, 400, bad)
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('10.000'))

    def test_future_arrival_date_rejected(self):
        future = (timezone.localdate() + datetime.timedelta(days=5)).isoformat()
        r = self.api.post(f'{MATERIALS}{self.material.id}/incoming/',
                          {'quantity': '1', 'arrival_date': future}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_negative_price_rejected(self):
        r = self.api.post(f'{MATERIALS}{self.material.id}/incoming/',
                          {'quantity': '1', 'price_per_unit': '-10'}, format='json')
        self.assertEqual(r.status_code, 400)


class ArchiveTests(_Base):
    def test_archive_and_restore_material(self):
        r = self.api.post(f'{MATERIALS}{self.material.id}/archive/')
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.material.refresh_from_db()
        self.assertTrue(self.material.is_archived)
        self.assertIsNotNone(self.material.archived_at)

        r = self.api.post(f'{MATERIALS}{self.material.id}/restore/')
        self.assertEqual(r.status_code, 200)
        self.material.refresh_from_db()
        self.assertFalse(self.material.is_archived)

    def test_archived_material_leaves_the_active_list(self):
        self.api.post(f'{MATERIALS}{self.material.id}/archive/')
        self.assertNotIn(self.material.id, self._ids(f'{MATERIALS}?is_archived=false'))
        self.assertIn(self.material.id, self._ids(f'{MATERIALS}?is_archived=true'))

    def _ids(self, url):
        body = self.api.get(url).json()
        rows = body['results'] if isinstance(body, dict) else body
        return [row['id'] for row in rows]

    def test_archive_and_restore_product(self):
        self.assertEqual(self.api.post(f'{PRODUCTS}{self.product.id}/archive/').status_code, 200)
        self.product.refresh_from_db()
        self.assertTrue(self.product.is_archived)
        self.assertEqual(self.api.post(f'{PRODUCTS}{self.product.id}/restore/').status_code, 200)
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_archived)

    def test_worker_cannot_archive(self):
        r = self.as_(self.worker).post(f'{MATERIALS}{self.material.id}/archive/')
        self.assertEqual(r.status_code, 403)


class ClientArchiveTests(TestCase):
    def setUp(self):
        from apps.clients.models import Client
        self.company = Company.objects.create(name='ArcCo', is_active=True)
        self.owner = User.objects.create_user(username='arc_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.url = f'/api/v1/clients/clients/{self.client_obj.id}/'

    def test_archive_and_restore(self):
        r = self.api.post(f'{self.url}archive/')
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.client_obj.refresh_from_db()
        self.assertTrue(self.client_obj.is_archived)
        self.assertIsNotNone(self.client_obj.archived_at)

        r = self.api.post(f'{self.url}restore/')
        self.assertEqual(r.status_code, 200)
        self.client_obj.refresh_from_db()
        self.assertFalse(self.client_obj.is_archived)

    def test_patch_cannot_bypass_the_action(self):
        """
        Прямой PATCH is_archived обходил archive() и не проставлял archived_at —
        клиент «в архиве» без даты архивации. Поле только на чтение.
        """
        r = self.api.patch(self.url, {'is_archived': True}, format='json')
        self.assertEqual(r.status_code, 200)
        self.client_obj.refresh_from_db()
        self.assertFalse(self.client_obj.is_archived)


class CrossCompanyTests(_Base):
    """Чужие записи не видны, значит и оприходовать/заархивировать их нельзя."""
    def setUp(self):
        super().setUp()
        other = Company.objects.create(name='Чужая', is_active=True)
        self.stranger = User.objects.create_user(username='stranger_owner', password='p',
                                                 role=User.Role.OWNER, company=other)

    def test_cannot_receive_into_another_company(self):
        r = self.as_(self.stranger).post(f'{MATERIALS}{self.material.id}/incoming/',
                                         {'quantity': '5'}, format='json')
        self.assertEqual(r.status_code, 404)
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('10.000'))

    def test_cannot_archive_another_company(self):
        r = self.as_(self.stranger).post(f'{MATERIALS}{self.material.id}/archive/')
        self.assertEqual(r.status_code, 404)
        self.material.refresh_from_db()
        self.assertFalse(self.material.is_archived)


class StockMovementHistoryTests(_Base):
    def test_history_shows_names_and_hides_price_from_admin(self):
        self.api.post(f'{MATERIALS}{self.material.id}/incoming/',
                      {'quantity': '4', 'price_per_unit': '300'}, format='json')

        owner_row = self.api.get('/api/v1/warehouse/stock-movements/').json()
        owner_row = (owner_row.get('results') or owner_row)[0]
        self.assertEqual(owner_row['material_name'], 'Гранит')
        self.assertEqual(owner_row['unit'], 'm2')
        self.assertIn('price_per_unit', owner_row)

        admin_row = self.as_(self.admin).get('/api/v1/warehouse/stock-movements/').json()
        admin_row = (admin_row.get('results') or admin_row)[0]
        self.assertEqual(admin_row['material_name'], 'Гранит')
        self.assertNotIn('price_per_unit', admin_row)

    def test_worker_cannot_read_history(self):
        r = self.as_(self.worker).get('/api/v1/warehouse/stock-movements/')
        self.assertEqual(r.status_code, 403)
