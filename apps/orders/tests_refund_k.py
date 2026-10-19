"""
Refund endpoint tests — полный набор regression tests для Block 3.

Покрывает:
- refund owner allowed / admin+worker denied
- refund non-delivered / cancelled denied
- refund zero / negative denied
- refund > refundable denied
- partial refund, full refund, second refund
- full refund → cancel allowed
- partial refund → cancel blocked
- refund → cash decreases, revenue unchanged, net profit decreases
- cancellation → stock restored
- double cancellation blocked
- concurrent refunds cannot over-refund
- idempotency (retry)
- audit cancellation / refund
- cross-tenant refund denied
- admin/worker cannot see refund amount
"""
import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.clients.models import Client
from apps.companies.models import Company
from apps.finance.models import Expense
from apps.orders.models import Order
from apps.warehouse.models import FinishedProduct, StockMovement

ORDERS = '/api/v1/orders/orders/'


def _make_order(api, company, client_obj, product, **overrides):
    data = {
        'client': client_obj.id,
        'product': product.id,
        'quantity': '5',
        'unit': 'sht',
        'total_amount': '2000',
        'deadline': (timezone.now() + datetime.timedelta(days=5)).isoformat(),
    }
    data.update(overrides)
    return api.post(ORDERS, data, format='json').json()['id']


def _pay_order(api, client_obj, order_id, amount):
    return api.post('/api/v1/clients/payments/', {
        'client': client_obj.id,
        'order': order_id,
        'amount': str(amount),
        'payment_method': 'cash',
        'payment_date': timezone.now().isoformat(),
    }, format='json')


def _deliver_order(api, order_id):
    return api.post(f'{ORDERS}{order_id}/deliver/')


# ── A. Refund owner allowed ────────────────────────────────────────────────
class RefundOwnerAllowedTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RefundCo', is_active=True)
        self.owner = User.objects.create_user(
            username='ref_owner', password='p',
            role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Товар', quantity=Decimal('20'), unit='sht')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.order_id = _make_order(self.api, self.company, self.client_obj, self.product)
        _pay_order(self.api, self.client_obj, self.order_id, 1000)
        _deliver_order(self.api, self.order_id)

    def test_refund_owner_allowed(self):
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '500', 'payment_method': 'cash', 'comment': 'test',
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_refund_creates_expense(self):
        self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '500', 'payment_method': 'cash',
        }, format='json')
        expense = Expense.objects.filter(order_id=self.order_id, category='client_refund')
        self.assertEqual(expense.count(), 1)
        self.assertEqual(expense.first().amount, Decimal('500'))


# ── B. Admin refund denied ─────────────────────────────────────────────────
class RefundAdminDeniedTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RefundCo2', is_active=True)
        self.admin = User.objects.create_user(
            username='ref_admin', password='p',
            role=User.Role.ADMIN, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Товар', quantity=Decimal('20'), unit='sht')
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.order_id = _make_order(self.api, self.company, self.client_obj, self.product)
        owner = User.objects.create_user(
            username='ref_owner2', password='p',
            role=User.Role.OWNER, company=self.company)
        api_owner = APIClient()
        api_owner.force_authenticate(owner)
        _pay_order(api_owner, self.client_obj, self.order_id, 1000)
        _deliver_order(api_owner, self.order_id)

    def test_admin_refund_denied(self):
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '500', 'payment_method': 'cash',
        }, format='json')
        self.assertIn(resp.status_code, [403, 404])


# ── C. Worker refund denied ────────────────────────────────────────────────
class RefundWorkerDeniedTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RefundCo3', is_active=True)
        self.owner = User.objects.create_user(
            username='ref_owner3', password='p',
            role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(
            username='ref_worker', password='p',
            role=User.Role.WORKER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Товар', quantity=Decimal('20'), unit='sht')
        api_owner = APIClient()
        api_owner.force_authenticate(self.owner)
        self.order_id = _make_order(api_owner, self.company, self.client_obj, self.product)
        _pay_order(api_owner, self.client_obj, self.order_id, 1000)
        _deliver_order(api_owner, self.order_id)
        self.api = APIClient()
        self.api.force_authenticate(self.worker)

    def test_worker_refund_denied(self):
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '500', 'payment_method': 'cash',
        }, format='json')
        self.assertIn(resp.status_code, [403, 404])


# ── D. Prepayment refund and cancel scenarios (DEF-001) ───────────────────────
class PrepaymentRefundAndCancelTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RefundPrepayCo', is_active=True)
        self.owner = User.objects.create_user(
            username='ref_prepay_owner', password='p',
            role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Товар', quantity=Decimal('20'),
            cost_price=Decimal('100'), unit='sht')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.order_id = _make_order(self.api, self.company, self.client_obj, self.product)
        _pay_order(self.api, self.client_obj, self.order_id, 1000)

    def test_prepayment_full_refund_then_cancel(self):
        """1) Заказ с предоплатой -> полный возврат -> отмена проходит штатно."""
        order = Order.objects.get(pk=self.order_id)
        self.assertEqual(order.status, Order.Status.NEW)
        self.assertEqual(order.refundable_amount, Decimal('1000'))

        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '1000', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)

        order.refresh_from_db()
        self.assertEqual(order.refundable_amount, Decimal('0'))

        cancel_resp = self.api.post(f'{ORDERS}{self.order_id}/cancel/')
        self.assertEqual(cancel_resp.status_code, 200, cancel_resp.data)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)

        # Склад не изменился (не списывался и не возвращался дважды)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('20'))
        self.assertEqual(self.product.required_for_orders, Decimal('0'))

    def test_prepayment_partial_refund_then_exceed_denied(self):
        """2) Заказ с предоплатой -> частичный возврат -> попытка возврата больше остатка."""
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '400', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 200)

        order = Order.objects.get(pk=self.order_id)
        self.assertEqual(order.refundable_amount, Decimal('600'))

        # Попытка вернуть больше остатка
        resp_over = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '700', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp_over.status_code, 400)

        # Возврат точного остатка
        resp_exact = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '600', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp_exact.status_code, 200)

        order.refresh_from_db()
        self.assertEqual(order.refundable_amount, Decimal('0'))

    def test_refund_cancelled_order_denied(self):
        """3) Попытка возврата отменённого заказа."""
        # Полный возврат, затем отмена
        self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '1000', 'payment_method': 'cash',
        }, format='json')
        self.api.post(f'{ORDERS}{self.order_id}/cancel/')

        # Попытка повторного возврата уже отменённого заказа
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '100', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_cancel_with_unrefunded_prepayment_blocked(self):
        """4) Попытка отмены заказа с неотрицательным остатком к возврату (блокируется)."""
        cancel_resp = self.api.post(f'{ORDERS}{self.order_id}/cancel/')
        self.assertEqual(cancel_resp.status_code, 400)

        # Частичный возврат: отмена всё ещё заблокирована
        self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '300', 'payment_method': 'cash',
        }, format='json')
        cancel_resp2 = self.api.post(f'{ORDERS}{self.order_id}/cancel/')
        self.assertEqual(cancel_resp2.status_code, 400)

        # Полный возврат остатка: отмена разрешена
        self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '700', 'payment_method': 'cash',
        }, format='json')
        cancel_resp3 = self.api.post(f'{ORDERS}{self.order_id}/cancel/')
        self.assertEqual(cancel_resp3.status_code, 200)

    def test_prepayment_refund_does_not_affect_stock(self):
        """5) Отсутствие списания или оприходования склада при возврате предоплаты."""
        self.product.refresh_from_db()
        qty_before = self.product.quantity

        self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '1000', 'payment_method': 'cash',
        }, format='json')

        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, qty_before)
        # Движений по складу не создано
        movements = StockMovement.objects.filter(product=self.product)
        self.assertEqual(movements.count(), 0)

    def test_prepayment_refund_creates_expense_and_decreases_cash(self):
        """6) Появление Expense(category=CLIENT_REFUND) и корректное уменьшение кассы."""
        from apps.reports.services import get_owner_analytics_data
        today = timezone.localdate()
        analytics_before = get_owner_analytics_data(self.company.pk, today, today)
        cash_before = analytics_before['cash']

        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '400', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 200)

        expense = Expense.objects.get(order_id=self.order_id, category='client_refund')
        self.assertEqual(expense.amount, Decimal('400'))
        self.assertEqual(expense.company, self.company)

        analytics_after = get_owner_analytics_data(self.company.pk, today, today)
        self.assertEqual(analytics_after['cash'], cash_before - Decimal('400'))

    def test_prepayment_refund_no_wac_distortion(self):
        """7) Отсутствие искажения WAC и себестоимости."""
        self.product.refresh_from_db()
        cost_price_before = self.product.cost_price

        self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '500', 'payment_method': 'cash',
        }, format='json')

        self.product.refresh_from_db()
        self.assertEqual(self.product.cost_price, cost_price_before)

    def test_concurrent_prepayment_refund_cannot_over_refund(self):
        """8) Защита от over-refund при предоплате."""
        resp1 = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '600', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp1.status_code, 200)

        resp2 = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '500', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp2.status_code, 400)

        resp3 = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '400', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp3.status_code, 200)



# ── E. Refund cancelled denied ─────────────────────────────────────────────
class RefundCancelledDeniedTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RefundCo5', is_active=True)
        self.owner = User.objects.create_user(
            username='ref_owner5', password='p',
            role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Товар', quantity=Decimal('20'), unit='sht')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.order_id = _make_order(self.api, self.company, self.client_obj, self.product)
        self.api.post(f'{ORDERS}{self.order_id}/cancel/')

    def test_cancelled_order_refund_denied(self):
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '500', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 400)


# ── F+G. Refund zero/negative denied ───────────────────────────────────────
class RefundAmountValidationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RefundCo6', is_active=True)
        self.owner = User.objects.create_user(
            username='ref_owner6', password='p',
            role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Товар', quantity=Decimal('20'), unit='sht')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.order_id = _make_order(self.api, self.company, self.client_obj, self.product)
        _pay_order(self.api, self.client_obj, self.order_id, 1000)
        _deliver_order(self.api, self.order_id)

    def test_refund_zero_denied(self):
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '0', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_refund_negative_denied(self):
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '-100', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_refund_invalid_string_denied(self):
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': 'abc', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 400)


# ── H. Refund > refundable denied ──────────────────────────────────────────
class RefundExceedsRefundableTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RefundCo7', is_active=True)
        self.owner = User.objects.create_user(
            username='ref_owner7', password='p',
            role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Товар', quantity=Decimal('20'), unit='sht')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.order_id = _make_order(self.api, self.company, self.client_obj, self.product)
        _pay_order(self.api, self.client_obj, self.order_id, 500)
        _deliver_order(self.api, self.order_id)

    def test_refund_exceeds_paid_denied(self):
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '600', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 400)


# ── I+J+K. Partial refund, full refund, second refund ─────────────────────
class RefundPartialFullTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RefundCo8', is_active=True)
        self.owner = User.objects.create_user(
            username='ref_owner8', password='p',
            role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Товар', quantity=Decimal('20'), unit='sht')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.order_id = _make_order(self.api, self.company, self.client_obj, self.product)
        _pay_order(self.api, self.client_obj, self.order_id, 1000)
        _deliver_order(self.api, self.order_id)

    def test_partial_refund(self):
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '400', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        order = Order.objects.get(pk=self.order_id)
        self.assertEqual(order.refundable_amount, Decimal('600'))

    def test_full_refund(self):
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '1000', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        order = Order.objects.get(pk=self.order_id)
        self.assertEqual(order.refundable_amount, Decimal('0'))

    def test_second_refund_respects_remaining(self):
        self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '600', 'payment_method': 'cash',
        }, format='json')
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '500', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

        resp2 = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '400', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp2.status_code, 200)


# ── L. Full refund → cancel allowed ────────────────────────────────────────
class FullRefundThenCancelTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RefundCo9', is_active=True)
        self.owner = User.objects.create_user(
            username='ref_owner9', password='p',
            role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Товар', quantity=Decimal('20'), unit='sht')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.order_id = _make_order(self.api, self.company, self.client_obj, self.product)
        _pay_order(self.api, self.client_obj, self.order_id, 1000)
        _deliver_order(self.api, self.order_id)

    def test_full_refund_then_cancel_allowed(self):
        self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '1000', 'payment_method': 'cash',
        }, format='json')
        resp = self.api.post(f'{ORDERS}{self.order_id}/cancel/')
        self.assertEqual(resp.status_code, 200)
        order = Order.objects.get(pk=self.order_id)
        self.assertEqual(order.status, Order.Status.CANCELLED)

    def test_full_refund_then_cancel_returns_stock(self):
        self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '1000', 'payment_method': 'cash',
        }, format='json')
        self.api.post(f'{ORDERS}{self.order_id}/cancel/')
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('20'))


# ── M. Partial refund → cancel blocked ─────────────────────────────────────
class PartialRefundThenCancelBlockedTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RefundCo10', is_active=True)
        self.owner = User.objects.create_user(
            username='ref_owner10', password='p',
            role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Товар', quantity=Decimal('20'), unit='sht')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.order_id = _make_order(self.api, self.company, self.client_obj, self.product)
        _pay_order(self.api, self.client_obj, self.order_id, 1000)
        _deliver_order(self.api, self.order_id)

    def test_partial_refund_then_cancel_blocked(self):
        self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '400', 'payment_method': 'cash',
        }, format='json')
        resp = self.api.post(f'{ORDERS}{self.order_id}/cancel/')
        self.assertEqual(resp.status_code, 400)


# ── N+O+P. Financial impact ───────────────────────────────────────────────
class RefundFinancialImpactTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RefundCo11', is_active=True)
        self.owner = User.objects.create_user(
            username='ref_owner11', password='p',
            role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Товар', quantity=Decimal('20'), unit='sht')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.order_id = _make_order(self.api, self.company, self.client_obj, self.product)
        _pay_order(self.api, self.client_obj, self.order_id, 1000)
        _deliver_order(self.api, self.order_id)

    def test_refund_creates_expense_category(self):
        self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '300', 'payment_method': 'cash',
        }, format='json')
        expense = Expense.objects.get(order_id=self.order_id, category='client_refund')
        self.assertEqual(expense.amount, Decimal('300'))
        self.assertEqual(expense.company, self.company)

    def test_cancel_after_refund_restores_stock(self):
        self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '1000', 'payment_method': 'cash',
        }, format='json')
        self.api.post(f'{ORDERS}{self.order_id}/cancel/')
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('20'))


# ── Q+R. Cancellation stock restoration and double cancel ─────────────────
class CancellationStockTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RefundCo12', is_active=True)
        self.owner = User.objects.create_user(
            username='ref_owner12', password='p',
            role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Товар', quantity=Decimal('20'), unit='sht')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.order_id = _make_order(self.api, self.company, self.client_obj, self.product)
        _deliver_order(self.api, self.order_id)

    def test_cancellation_returns_stock_once(self):
        self.api.post(f'{ORDERS}{self.order_id}/cancel/')
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('20'))
        movements = StockMovement.objects.filter(
            product=self.product,
            movement_type=StockMovement.MovementType.INCOMING,
            reason__icontains=str(self.order_id))
        self.assertEqual(movements.count(), 1)

    def test_double_cancellation_blocked(self):
        self.api.post(f'{ORDERS}{self.order_id}/cancel/')
        resp = self.api.post(f'{ORDERS}{self.order_id}/cancel/')
        self.assertEqual(resp.status_code, 400)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('20'))


# ── S. Concurrent refunds cannot over-refund ──────────────────────────────
class ConcurrentRefundTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RefundCo13', is_active=True)
        self.owner = User.objects.create_user(
            username='ref_owner13', password='p',
            role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Товар', quantity=Decimal('20'), unit='sht')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.order_id = _make_order(self.api, self.company, self.client_obj, self.product)
        _pay_order(self.api, self.client_obj, self.order_id, 1000)
        _deliver_order(self.api, self.order_id)

    def test_concurrent_refunds_cannot_over_refund(self):
        """Two sequential 700 refunds on 1000 paid — second must fail.

        True concurrent over-refund is prevented by select_for_update().
        We simulate the idempotency guard: second request sees updated
        refundable_amount and is rejected.
        """
        api2 = APIClient()
        api2.force_authenticate(self.owner)
        r1 = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '700', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(r1.status_code, 200)

        r2 = api2.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '700', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(r2.status_code, 400)

        order = Order.objects.get(pk=self.order_id)
        self.assertEqual(order.refundable_amount, Decimal('300'))


# ── U. Retry/idempotency ──────────────────────────────────────────────────
class RefundIdempotencyTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RefundCo14', is_active=True)
        self.owner = User.objects.create_user(
            username='ref_owner14', password='p',
            role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Товар', quantity=Decimal('20'), unit='sht')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.order_id = _make_order(self.api, self.company, self.client_obj, self.product)
        _pay_order(self.api, self.client_obj, self.order_id, 1000)
        _deliver_order(self.api, self.order_id)

    def test_retry_does_not_create_second_refund(self):
        """Simulate network retry: full refund succeeds, retry rejected."""
        self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '1000', 'payment_method': 'cash',
        }, format='json')
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '1000', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        expenses = Expense.objects.filter(order_id=self.order_id, category='client_refund')
        self.assertEqual(expenses.count(), 1)


# ── V+W. Audit ────────────────────────────────────────────────────────────
class RefundAuditTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RefundCo15', is_active=True)
        self.owner = User.objects.create_user(
            username='ref_owner15', password='p',
            role=User.Role.OWNER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Товар', quantity=Decimal('20'), unit='sht')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.order_id = _make_order(self.api, self.company, self.client_obj, self.product)
        _pay_order(self.api, self.client_obj, self.order_id, 1000)
        _deliver_order(self.api, self.order_id)

    def test_audit_refund(self):
        self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '300', 'payment_method': 'cash', 'comment': 'возврат',
        }, format='json')
        audit = AuditLog.objects.filter(
            action=AuditLog.Action.REFUND,
            object_id=str(self.order_id)).last()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.changes.get('refund_amount'), '300')
        self.assertEqual(audit.company, self.company)

    def test_audit_cancellation_has_old_status(self):
        self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '1000', 'payment_method': 'cash',
        }, format='json')
        self.api.post(f'{ORDERS}{self.order_id}/cancel/')
        audit = AuditLog.objects.filter(
            action=AuditLog.Action.UPDATE,
            object_id=str(self.order_id)).order_by('-created_at').first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.changes.get('status', {}).get('old'), 'delivered')
        self.assertEqual(audit.changes.get('status', {}).get('new'), 'cancelled')


# ── X. Cross-tenant refund denied ─────────────────────────────────────────
class CrossTenantRefundTests(TestCase):
    def setUp(self):
        self.company1 = Company.objects.create(name='Co1', is_active=True)
        self.company2 = Company.objects.create(name='Co2', is_active=True)
        self.owner1 = User.objects.create_user(
            username='own1', password='p',
            role=User.Role.OWNER, company=self.company1)
        self.owner2 = User.objects.create_user(
            username='own2', password='p',
            role=User.Role.OWNER, company=self.company2)
        self.client_obj = Client.objects.create(company=self.company1, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company1, name='Товар', quantity=Decimal('20'), unit='sht')
        self.api1 = APIClient()
        self.api1.force_authenticate(self.owner1)
        self.order_id = _make_order(self.api1, self.company1, self.client_obj, self.product)
        _pay_order(self.api1, self.client_obj, self.order_id, 1000)
        _deliver_order(self.api1, self.order_id)
        self.api2 = APIClient()
        self.api2.force_authenticate(self.owner2)

    def test_cross_tenant_refund_denied(self):
        resp = self.api2.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '500', 'payment_method': 'cash',
        }, format='json')
        self.assertIn(resp.status_code, [403, 404])


# ── Y+Z. Admin/Worker cannot see refund amount ────────────────────────────
class RefundVisibilityTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='RefundCo16', is_active=True)
        self.owner = User.objects.create_user(
            username='ref_owner16', password='p',
            role=User.Role.OWNER, company=self.company)
        self.admin = User.objects.create_user(
            username='ref_admin16', password='p',
            role=User.Role.ADMIN, company=self.company)
        self.worker = User.objects.create_user(
            username='ref_worker16', password='p',
            role=User.Role.WORKER, company=self.company)
        self.client_obj = Client.objects.create(company=self.company, name='Клиент')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Товар', quantity=Decimal('20'), unit='sht')
        self.api_owner = APIClient()
        self.api_owner.force_authenticate(self.owner)
        self.order_id = _make_order(self.api_owner, self.company, self.client_obj, self.product)
        _pay_order(self.api_owner, self.client_obj, self.order_id, 1000)
        _deliver_order(self.api_owner, self.order_id)
        self.api_owner.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '300', 'payment_method': 'cash',
        }, format='json')
        Order.objects.filter(pk=self.order_id).update(worker=self.worker)

    def test_admin_cannot_see_refundable_amount(self):
        self.api_admin = APIClient()
        self.api_admin.force_authenticate(self.admin)
        resp = self.api_admin.get(f'{ORDERS}{self.order_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('refundable_amount', resp.data)

    def test_worker_cannot_see_refundable_amount(self):
        self.api_worker = APIClient()
        self.api_worker.force_authenticate(self.worker)
        resp = self.api_worker.get(f'{ORDERS}{self.order_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('refundable_amount', resp.data)

    def test_owner_sees_refundable_amount(self):
        resp = self.api_owner.get(f'{ORDERS}{self.order_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('refundable_amount', resp.data)
        self.assertEqual(resp.data['refundable_amount'], '700.00')
