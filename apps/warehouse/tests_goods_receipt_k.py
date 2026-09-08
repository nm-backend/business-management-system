"""
Документ прихода: одна поставка — несколько материалов (макет «Материални
қабул қилиш»: поставщик, номер и дата один раз, ниже «Яна материал қўшиш»).

Проверяется не только «сохранилось», а инварианты, которые ломают склад:
атомарность, отсутствие частично проведённого документа, связь истории с
операцией, изоляция компаний, права на цены и идемпотентность.
"""
import threading
from decimal import Decimal

from django.db import connection, connections
from django.test import TestCase, TransactionTestCase, tag
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.companies.models import Company
from apps.warehouse.models import (
    GoodsReceipt, GoodsReceiptLine, RawMaterial, StockMovement,
)

RECEIPTS = '/api/v1/warehouse/goods-receipts/'
IS_POSTGRES = connection.vendor == 'postgresql'


class GoodsReceiptSetupMixin:
    @classmethod
    def _setup_company(cls):
        cls.company = Company.objects.create(name='ReceiptCo')
        cls.owner = User.objects.create_user(
            username='gr_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='gr_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )
        cls.worker = User.objects.create_user(
            username='gr_worker', password='pw', role=User.Role.WORKER, company=cls.company,
        )
        cls.marble = RawMaterial.objects.create(
            company=cls.company, name='Мрамор оқ', unit='m2',
            quantity=Decimal('10'), avg_cost_price=Decimal('100.00'),
        )
        cls.granite = RawMaterial.objects.create(
            company=cls.company, name='Гранит', unit='m2', quantity=Decimal('5'),
        )
        cls.glue = RawMaterial.objects.create(
            company=cls.company, name='Елим', unit='kg', quantity=Decimal('0'),
        )

    def api_as(self, user):
        api = APIClient()
        api.force_authenticate(user)
        return api

    def payload(self, **overrides):
        data = {
            'supplier': 'Marble Stone LLC',
            'document_number': 'K-1258',
            'receipt_date': timezone.localdate().isoformat(),
            'lines': [
                {'material': self.marble.id, 'quantity': '25', 'price_per_unit': '850000'},
                {'material': self.granite.id, 'quantity': '18.75', 'price_per_unit': '500000'},
                {'material': self.glue.id, 'quantity': '3', 'price_per_unit': '15000'},
            ],
        }
        data.update(overrides)
        return data


class GoodsReceiptTests(GoodsReceiptSetupMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_company()

    # ── Проведение ──────────────────────────────────────────────────────────

    def test_receipt_applies_all_lines(self):
        response = self.api_as(self.owner).post(RECEIPTS, self.payload(), format='json')
        self.assertEqual(response.status_code, 201, response.data)

        self.marble.refresh_from_db()
        self.granite.refresh_from_db()
        self.glue.refresh_from_db()
        self.assertEqual(self.marble.quantity, Decimal('35.000'))
        self.assertEqual(self.granite.quantity, Decimal('23.750'))
        self.assertEqual(self.glue.quantity, Decimal('3.000'))

        receipt = GoodsReceipt.objects.get(pk=response.data['id'])
        self.assertEqual(receipt.lines.count(), 3)

    def test_history_links_to_the_operation(self):
        """История склада ссылается на документ, а не только на его номер строкой."""
        response = self.api_as(self.owner).post(RECEIPTS, self.payload(), format='json')
        receipt = GoodsReceipt.objects.get(pk=response.data['id'])

        movements = StockMovement.objects.filter(receipt=receipt)
        self.assertEqual(movements.count(), 3)
        self.assertEqual(
            {m.movement_type for m in movements},
            {StockMovement.MovementType.INCOMING},
        )
        self.assertEqual(
            sorted(m.material_id for m in movements),
            sorted([self.marble.id, self.granite.id, self.glue.id]),
        )

    def test_average_cost_recalculated_like_single_incoming(self):
        """
        Средневзвешенная себестоимость считается тем же правилом, что и раньше.

        Было 10 м² по 100, пришло 25 по 850000 → (10×100 + 25×850000) / 35.
        """
        self.api_as(self.owner).post(RECEIPTS, self.payload(), format='json')
        self.marble.refresh_from_db()
        expected = ((Decimal('10') * Decimal('100') + Decimal('25') * Decimal('850000'))
                    / Decimal('35')).quantize(Decimal('0.01'))
        self.assertEqual(self.marble.avg_cost_price, expected)

    # ── Атомарность ─────────────────────────────────────────────────────────

    def test_bad_line_rolls_back_whole_document(self):
        """Частично проведённого прихода быть не может."""
        before_marble = self.marble.quantity
        response = self.api_as(self.owner).post(RECEIPTS, self.payload(lines=[
            {'material': self.marble.id, 'quantity': '25'},
            {'material': self.granite.id, 'quantity': '-5'},   # ошибка во второй строке
        ]), format='json')
        self.assertEqual(response.status_code, 400, response.data)

        self.marble.refresh_from_db()
        self.assertEqual(self.marble.quantity, before_marble)
        self.assertEqual(GoodsReceipt.objects.count(), 0)
        self.assertEqual(GoodsReceiptLine.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_foreign_material_rolls_back_whole_document(self):
        other = Company.objects.create(name='ForeignReceiptCo')
        foreign_material = RawMaterial.objects.create(
            company=other, name='Чужой', unit='m2', quantity=Decimal('1'),
        )
        before = self.marble.quantity
        response = self.api_as(self.owner).post(RECEIPTS, self.payload(lines=[
            {'material': self.marble.id, 'quantity': '5'},
            {'material': foreign_material.id, 'quantity': '5'},
        ]), format='json')
        self.assertIn(response.status_code, (400, 403), response.data)

        self.marble.refresh_from_db()
        foreign_material.refresh_from_db()
        self.assertEqual(self.marble.quantity, before)
        self.assertEqual(foreign_material.quantity, Decimal('1.000'))
        self.assertEqual(GoodsReceipt.objects.count(), 0)

    def test_empty_document_rejected(self):
        response = self.api_as(self.owner).post(RECEIPTS, self.payload(lines=[]), format='json')
        self.assertEqual(response.status_code, 400)

    # ── Идемпотентность ─────────────────────────────────────────────────────

    def test_same_document_number_not_duplicated(self):
        """
        Повтор той же формы (двойной клик, ретрай сети) не создаёт вторую поставку.

        Иначе остаток вырастает дважды, а в истории две одинаковые операции.
        """
        api = self.api_as(self.owner)
        first = api.post(RECEIPTS, self.payload(), format='json')
        self.assertEqual(first.status_code, 201)

        second = api.post(RECEIPTS, self.payload(), format='json')
        self.assertEqual(second.status_code, 400, 'документ с тем же номером принят повторно')

        self.marble.refresh_from_db()
        self.assertEqual(self.marble.quantity, Decimal('35.000'), 'приход применился дважды')
        self.assertEqual(GoodsReceipt.objects.count(), 1)

    def test_documents_without_number_are_allowed_repeatedly(self):
        """Поставка без бумаг бывает не одна — пустой номер не ограничиваем."""
        api = self.api_as(self.owner)
        for _ in range(2):
            response = api.post(RECEIPTS, self.payload(document_number='', lines=[
                {'material': self.marble.id, 'quantity': '1'},
            ]), format='json')
            self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(GoodsReceipt.objects.count(), 2)

    def test_same_number_from_other_supplier_allowed(self):
        api = self.api_as(self.owner)
        api.post(RECEIPTS, self.payload(lines=[{'material': self.marble.id, 'quantity': '1'}]),
                 format='json')
        response = api.post(RECEIPTS, self.payload(
            supplier='Stone Premium',
            lines=[{'material': self.marble.id, 'quantity': '1'}],
        ), format='json')
        self.assertEqual(response.status_code, 201, response.data)

    # ── Права и изоляция ────────────────────────────────────────────────────

    def test_admin_can_receive_but_sees_no_prices(self):
        """Приход по количеству администратору разрешён, закупочные цены — нет."""
        api = self.api_as(self.admin)
        response = api.post(RECEIPTS, self.payload(), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotIn('total_amount', response.data)
        for line in response.data['lines']:
            self.assertNotIn('price_per_unit', line)

        # Цена, присланная админом, игнорируется — себестоимость не меняется.
        self.marble.refresh_from_db()
        self.assertEqual(self.marble.avg_cost_price, Decimal('100.00'))

    def test_owner_sees_prices_and_total(self):
        api = self.api_as(self.owner)
        created = api.post(RECEIPTS, self.payload(), format='json')
        detail = api.get(f"{RECEIPTS}{created.data['id']}/").data
        self.assertIn('total_amount', detail)
        self.assertEqual(Decimal(str(detail['lines'][0]['price_per_unit'])), Decimal('850000.00'))

    def test_worker_cannot_receive_or_read(self):
        api = self.api_as(self.worker)
        self.assertEqual(api.post(RECEIPTS, self.payload(), format='json').status_code, 403)
        self.assertEqual(api.get(RECEIPTS).status_code, 403)

    def test_other_company_documents_invisible(self):
        other = Company.objects.create(name='OtherReceiptCo')
        other_owner = User.objects.create_user(
            username='gr_other', password='pw', role=User.Role.OWNER, company=other,
        )
        self.api_as(self.owner).post(RECEIPTS, self.payload(), format='json')

        rows = self.api_as(other_owner).get(RECEIPTS).data
        rows = rows['results'] if 'results' in rows else rows
        self.assertEqual(len(rows), 0)

    def test_direct_id_access_denied_across_tenants(self):
        created = self.api_as(self.owner).post(RECEIPTS, self.payload(), format='json')
        other = Company.objects.create(name='OtherReceiptCo2')
        other_owner = User.objects.create_user(
            username='gr_other2', password='pw', role=User.Role.OWNER, company=other,
        )
        response = self.api_as(other_owner).get(f"{RECEIPTS}{created.data['id']}/")
        self.assertEqual(response.status_code, 404)

    # ── История и журнал ────────────────────────────────────────────────────

    def test_receipt_is_not_editable_or_deletable(self):
        """
        Проведённый документ не правится и не удаляется.

        Остатки уже изменены; правка задним числом разошлась бы с историей
        склада (ТЗ: удаления нет, все изменения историзированы).
        """
        created = self.api_as(self.owner).post(RECEIPTS, self.payload(), format='json')
        url = f"{RECEIPTS}{created.data['id']}/"
        self.assertEqual(self.api_as(self.owner).patch(url, {'supplier': 'X'}, format='json').status_code, 405)
        self.assertEqual(self.api_as(self.owner).delete(url).status_code, 405)

    def test_audit_log_written(self):
        self.api_as(self.owner).post(RECEIPTS, self.payload(), format='json')
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.CREATE, object_type__icontains='goodsreceipt',
            ).exists()
            or AuditLog.objects.filter(action=AuditLog.Action.CREATE).exists()
        )

    def test_decimal_precision_preserved(self):
        """Дробные количества не теряют тысячные и не превращаются в float."""
        self.api_as(self.owner).post(RECEIPTS, self.payload(lines=[
            {'material': self.granite.id, 'quantity': '18.755'},
        ]), format='json')
        self.granite.refresh_from_db()
        self.assertEqual(self.granite.quantity, Decimal('23.755'))
        self.assertIsInstance(self.granite.quantity, Decimal)


@tag('postgres')
class GoodsReceiptConcurrencyTests(GoodsReceiptSetupMixin, TransactionTestCase):
    """Параллельное проведение документов на PostgreSQL."""

    def setUp(self):
        if not IS_POSTGRES:
            self.skipTest('Гонки проверяются только на PostgreSQL')
        super().setUp()
        self._setup_company()

    def _run(self, func, threads=2):
        barrier = threading.Barrier(threads)
        results = []
        lock = threading.Lock()

        def runner(index):
            try:
                barrier.wait(timeout=30)
                outcome = func(index)
            except Exception as exc:  # noqa: BLE001
                outcome = exc
            finally:
                connections.close_all()
            with lock:
                results.append(outcome)

        workers = [threading.Thread(target=runner, args=(i,)) for i in range(threads)]
        for w in workers:
            w.start()
        for w in workers:
            w.join(timeout=60)
        return results

    def test_parallel_identical_documents_apply_once(self):
        """
        Два одновременных запроса с одним номером документа = один приход.

        Именно так выглядит двойной клик по кнопке «Қабул қилиш».
        """
        def post(_):
            return self.api_as(self.owner).post(RECEIPTS, self.payload(lines=[
                {'material': self.marble.id, 'quantity': '25'},
            ]), format='json').status_code

        results = self._run(post, threads=2)
        codes = [r for r in results if isinstance(r, int)]
        self.assertEqual(codes.count(201), 1, f'приход прошёл дважды: {results}')

        self.marble.refresh_from_db()
        self.assertEqual(self.marble.quantity, Decimal('35.000'))
        self.assertEqual(GoodsReceipt.objects.count(), 1)

    def test_parallel_different_documents_sum_up(self):
        """Разные поставки одного материала складываются без потерь."""
        def post(index):
            return self.api_as(self.owner).post(RECEIPTS, self.payload(
                document_number=f'K-{index}',
                lines=[{'material': self.marble.id, 'quantity': '10'}],
            ), format='json').status_code

        results = self._run(post, threads=4)
        self.assertEqual([r for r in results if r == 201].__len__(), 4, results)

        self.marble.refresh_from_db()
        self.assertEqual(self.marble.quantity, Decimal('50.000'))
        self.assertEqual(StockMovement.objects.filter(material=self.marble).count(), 4)
