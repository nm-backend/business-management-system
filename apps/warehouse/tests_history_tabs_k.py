"""
История движений: вкладки, фильтры и итоги (макет «Материал ҳаракатлари»).

Вкладки макета — «Ҳаммаси / Келган / Ишлатилган / Қайтарилган», под таблицей
итоги «Жами келган / Жами ишлатилган / Жами қолган».

Два принципиальных требования проверяются здесь:
  * фильтрация идёт НА СЕРВЕРЕ по реальным StockMovement, а не отбором уже
    загруженной страницы (иначе вкладка врёт на второй странице);
  * неизвестный параметр не должен молча возвращать всё подряд, создавая
    иллюзию фильтрации — каждый тест сравнивает результат с нефильтрованным.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.orders.models import Order
from apps.warehouse.models import RawMaterial, StockMovement

HISTORY = '/api/v1/warehouse/stock-movements/'
TOTALS = '/api/v1/warehouse/stock-movements/totals/'


class HistoryTabsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='HistoryCo')
        cls.owner = User.objects.create_user(
            username='hs_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='hs_worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )
        cls.marble = RawMaterial.objects.create(
            company=cls.company, name='Мрамор', unit='m2', quantity=Decimal('100'),
        )
        cls.granite = RawMaterial.objects.create(
            company=cls.company, name='Гранит', unit='m2', quantity=Decimal('100'),
        )
        client_obj = Client.objects.create(company=cls.company, name='Акбаров')
        cls.order = Order.objects.create(
            company=cls.company, client=client_obj, custom_product_name='Столешница',
            quantity=Decimal('1'), unit='sht', total_amount=Decimal('100'),
            deadline=timezone.now() + timezone.timedelta(days=1),
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        types = StockMovement.MovementType
        # Реальные строки истории — по одной каждого интересующего типа.
        self.incoming = StockMovement.objects.create(
            company=self.company, material=self.marble, movement_type=types.INCOMING,
            quantity=Decimal('25'), document_number='K-1258',
        )
        self.outgoing = StockMovement.objects.create(
            company=self.company, material=self.marble, movement_type=types.OUTGOING,
            quantity=Decimal('8.5'), related_order_id=self.order.id, purpose='production',
        )
        self.production_out = StockMovement.objects.create(
            company=self.company, material=self.granite, movement_type=types.PRODUCTION_OUT,
            quantity=Decimal('5.3'),
        )
        self.returned = StockMovement.objects.create(
            company=self.company, material=self.marble, movement_type=types.RETURN,
            quantity=Decimal('2'),
        )
        self.loss = StockMovement.objects.create(
            company=self.company, material=self.granite, movement_type=types.LOSS,
            quantity=Decimal('1.2'),
        )

    def _rows(self, params=None):
        response = self.api.get(HISTORY, params or {})
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data
        return data['results'] if 'results' in data else data

    # ── Вкладки ─────────────────────────────────────────────────────────────

    def test_all_tab_returns_every_movement(self):
        self.assertEqual(len(self._rows()), 5)

    def test_incoming_tab(self):
        rows = self._rows({'category': 'incoming'})
        self.assertEqual([r['movement_type'] for r in rows], ['incoming'])
        self.assertLess(len(rows), 5, 'вкладка обязана сузить выборку')

    def test_outgoing_tab_includes_production_and_loss(self):
        """«Ишлатилган» — это всё, что уменьшает склад: расход, производство, брак."""
        rows = self._rows({'category': 'outgoing'})
        self.assertEqual(
            sorted(r['movement_type'] for r in rows),
            ['loss', 'outgoing', 'production_out'],
        )

    def test_returned_tab_is_separate_from_incoming(self):
        returned = self._rows({'category': 'returned'})
        incoming = self._rows({'category': 'incoming'})
        self.assertEqual([r['movement_type'] for r in returned], ['return'])
        self.assertNotIn('return', [r['movement_type'] for r in incoming])

    def test_unknown_category_returns_nothing(self):
        """
        Неизвестная вкладка не должна показывать всю историю.

        Молчаливое игнорирование параметра выглядело бы как рабочий фильтр.
        """
        self.assertEqual(len(self._rows({'category': 'нечто'})), 0)

    # ── Фильтры ─────────────────────────────────────────────────────────────

    def test_filter_by_material_actually_filters(self):
        rows = self._rows({'material': self.granite.id})
        self.assertTrue(rows)
        self.assertLess(len(rows), 5)
        self.assertTrue(all(r['material'] == self.granite.id for r in rows))

    def test_filter_by_order(self):
        rows = self._rows({'order': self.order.id})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], self.outgoing.id)

    def test_filter_by_purpose(self):
        rows = self._rows({'purpose': 'production'})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['purpose'], 'production')

    def test_filter_by_period(self):
        old = StockMovement.objects.create(
            company=self.company, material=self.marble,
            movement_type=StockMovement.MovementType.INCOMING, quantity=Decimal('7'),
        )
        StockMovement.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=40),
        )
        today = timezone.localdate()
        rows = self._rows({'date_from': today.isoformat()})
        self.assertEqual(len(rows), 5, 'старое движение не должно попасть в период')

        rows_old = self._rows({
            'date_to': (today - timezone.timedelta(days=30)).isoformat(),
        })
        self.assertEqual(len(rows_old), 1)

    def test_invalid_date_is_validation_error_not_500(self):
        response = self.api.get(HISTORY, {'date_from': 'вчера'})
        self.assertEqual(response.status_code, 400)

    def test_search_by_document_number(self):
        rows = self._rows({'search': 'K-1258'})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['document_number'], 'K-1258')

    # ── Итоги ───────────────────────────────────────────────────────────────

    def test_totals_match_movements(self):
        data = self.api.get(TOTALS).data
        self.assertEqual(Decimal(str(data['incoming'])), Decimal('25.000'))
        self.assertEqual(Decimal(str(data['returned'])), Decimal('2.000'))
        # 8.5 расход + 5.3 производство + 1.2 брак
        self.assertEqual(Decimal(str(data['outgoing'])), Decimal('15.000'))
        self.assertEqual(Decimal(str(data['net'])), Decimal('12.000'))
        self.assertEqual(data['movements_count'], 5)

    def test_totals_respect_filters(self):
        """Итог считается по выборке с фильтрами, а не по всей истории."""
        data = self.api.get(TOTALS, {'material': self.granite.id}).data
        self.assertEqual(Decimal(str(data['incoming'])), Decimal('0'))
        self.assertEqual(Decimal(str(data['outgoing'])), Decimal('6.500'))

    def test_totals_are_not_page_limited(self):
        """
        Итог считает всю выборку, а не видимую страницу.

        Создаём движений больше размера страницы и сверяем сумму.
        """
        for _ in range(60):
            StockMovement.objects.create(
                company=self.company, material=self.marble,
                movement_type=StockMovement.MovementType.INCOMING, quantity=Decimal('1'),
            )
        data = self.api.get(TOTALS, {'category': 'incoming'}).data
        self.assertEqual(Decimal(str(data['incoming'])), Decimal('85.000'))
        self.assertEqual(data['movements_count'], 61)

    # ── Изоляция и права ────────────────────────────────────────────────────

    def test_other_company_history_invisible(self):
        other = Company.objects.create(name='OtherHistoryCo')
        other_material = RawMaterial.objects.create(
            company=other, name='Чужой', unit='m2', quantity=Decimal('1'),
        )
        StockMovement.objects.create(
            company=other, material=other_material,
            movement_type=StockMovement.MovementType.INCOMING, quantity=Decimal('999'),
        )
        self.assertEqual(len(self._rows()), 5)
        data = self.api.get(TOTALS).data
        self.assertEqual(Decimal(str(data['incoming'])), Decimal('25.000'))

    def test_foreign_material_filter_returns_empty(self):
        other = Company.objects.create(name='OtherHistoryCo2')
        foreign = RawMaterial.objects.create(
            company=other, name='Чужой', unit='m2', quantity=Decimal('1'),
        )
        self.assertEqual(len(self._rows({'material': foreign.id})), 0)

    def test_worker_has_no_history_access(self):
        api = APIClient()
        api.force_authenticate(self.worker)
        self.assertEqual(api.get(HISTORY).status_code, 403)
        self.assertEqual(api.get(TOTALS).status_code, 403)
