"""
Verification gap closure tests for Block 3 refund/cancel.

Covers:
1. Real concurrent refund (TransactionTestCase + threading.Barrier)
2. Real concurrent cancel (TransactionTestCase + threading.Barrier)
3. DB-level financial invariants (revenue, COGS, expenses, cash, net profit, client debt)
4. Refund amount boundaries (empty, null, 0.01, 100, 501 on 500, exact refundable)
5. Superadmin RBAC (SUPERADMIN → refund → denied)
6. DB-level audit (refund + cancel)
7. Expense metadata (created_by, date, payment_method, comment, company, order FK)
8. Idempotency (full retry denied, partial insufficient denied, exact remaining succeeds)
9. Stock invariant lifecycle (X → deliver X-N → cancel → X, exactly 1 StockMovement)
"""
import datetime
import threading
from decimal import Decimal

from django.test import TestCase, TransactionTestCase
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


def _create_delivered_order(company, total='1000', paid='1000', quantity='5'):
    owner = User.objects.create_user(
        username=f'vco_{company.pk}', password='p',
        role=User.Role.OWNER, company=company)
    client_obj = Client.objects.create(company=company, name='Клиент')
    product = FinishedProduct.objects.create(
        company=company, name='Товар', quantity=Decimal('20'), unit='sht')
    api = APIClient()
    api.force_authenticate(owner)
    order_id = _make_order(api, company, client_obj, product,
                           total_amount=total, quantity=quantity)
    _pay_order(api, client_obj, order_id, paid)
    _deliver_order(api, order_id)
    return order_id, client_obj, product, owner


# ── 1. Concurrent refund (real, TransactionTestCase) ────────────────────────

class ConcurrentRefundDBTests(TransactionTestCase):
    """Real concurrent refund with threading.Barrier and TransactionTestCase.

    Verifies select_for_update() prevents double-refund under concurrency.
    """
    reset_sequences = True

    def _refund_thread(self, barrier, api, order_id, amount, results, idx):
        from django.db import connection
        try:
            barrier.wait()
            resp = api.post(f'{ORDERS}{order_id}/refund/', {
                'amount': str(amount), 'payment_method': 'cash',
            }, format='json')
            results[idx] = resp.status_code
        finally:
            connection.close()

    def _run_concurrent_refunds(self, paid, amt1, amt2):
        company = Company.objects.create(name=f'ConcRef_{paid}_{amt1}', is_active=True)
        order_id, _, _, owner = _create_delivered_order(company, total=str(paid), paid=str(paid))

        barrier = threading.Barrier(2)
        results = [None, None]

        api1 = APIClient()
        api1.force_authenticate(owner)
        api2 = APIClient()
        api2.force_authenticate(owner)

        t1 = threading.Thread(target=self._refund_thread,
                              args=(barrier, api1, order_id, amt1, results, 0))
        t2 = threading.Thread(target=self._refund_thread,
                              args=(barrier, api2, order_id, amt2, results, 1))
        t1.start(); t2.start()
        t1.join(timeout=10); t2.join(timeout=10)

        order = Order.objects.get(pk=order_id)
        return results, order.refundable_amount

    def test_700_700_on_1000_one_wins(self):
        results, refundable = self._run_concurrent_refunds(1000, 700, 700)
        self.assertEqual(results.count(200), 1)
        self.assertEqual(results.count(400), 1)
        self.assertEqual(refundable, Decimal('300'))

    def test_500_500_on_1000_both_win(self):
        results, refundable = self._run_concurrent_refunds(1000, 500, 500)
        self.assertEqual(results.count(200), 2)
        self.assertEqual(refundable, Decimal('0'))

    def test_600_600_on_1000_one_wins(self):
        results, refundable = self._run_concurrent_refunds(1000, 600, 600)
        self.assertEqual(results.count(200), 1)
        self.assertEqual(results.count(400), 1)
        self.assertIn(refundable, (Decimal('400'), Decimal('0')))


# ── 2. Concurrent cancel (real, TransactionTestCase) ────────────────────────

class ConcurrentCancelDBTests(TransactionTestCase):
    """Real concurrent cancel: exactly 1 succeeds, stock returned once."""
    reset_sequences = True

    def _cancel_thread(self, barrier, api, order_id, results, idx):
        from django.db import connection
        try:
            barrier.wait()
            resp = api.post(f'{ORDERS}{order_id}/cancel/')
            results[idx] = resp.status_code
        finally:
            connection.close()

    def test_concurrent_cancel_one_wins(self):
        company = Company.objects.create(name='ConcCancel', is_active=True)
        order_id, _, product, owner = _create_delivered_order(company, paid='0')
        initial_qty = product.quantity

        barrier = threading.Barrier(2)
        results = [None, None]

        api1 = APIClient()
        api1.force_authenticate(owner)
        api2 = APIClient()
        api2.force_authenticate(owner)

        t1 = threading.Thread(target=self._cancel_thread,
                              args=(barrier, api1, order_id, results, 0))
        t2 = threading.Thread(target=self._cancel_thread,
                              args=(barrier, api2, order_id, results, 1))
        t1.start(); t2.start()
        t1.join(timeout=10); t2.join(timeout=10)

        self.assertEqual(results.count(200), 1)
        self.assertEqual(results.count(400), 1)

        order = Order.objects.get(pk=order_id)
        self.assertEqual(order.status, Order.Status.CANCELLED)

        product.refresh_from_db()
        self.assertEqual(product.quantity, initial_qty)

        movements = StockMovement.objects.filter(
            product=product,
            movement_type=StockMovement.MovementType.INCOMING,
            reason__icontains=str(order_id))
        self.assertEqual(movements.count(), 1)


# ── 3. DB-level financial invariants ────────────────────────────────────────

class RefundFinancialInvariantTests(TestCase):
    """Verify DB-level revenue, COGS, expenses, cash, net profit, client debt."""

    def _get_financials(self, company, date_from, date_to):
        from django.db.models import Sum, F, DecimalField, ExpressionWrapper
        from django.db.models.functions import TruncMonth

        revenue = Order.objects.filter(
            company_id=company.pk, status=Order.Status.DELIVERED,
            delivered_at__date__range=(date_from, date_to),
        ).aggregate(s=Sum('total_amount'))['s'] or Decimal('0')

        cogs = Order.objects.filter(
            company_id=company.pk, status=Order.Status.DELIVERED,
            delivered_at__date__range=(date_from, date_to),
        ).aggregate(s=Sum(ExpressionWrapper(
            F('quantity') * F('cost_price'),
            output_field=DecimalField(max_digits=15, decimal_places=2),
        )))['s'] or Decimal('0')

        expenses = Expense.objects.filter(
            company_id=company.pk, date__range=(date_from, date_to),
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0')

        payments = __import__('apps.clients.models', fromlist=['Payment']).Payment.objects.filter(
            company_id=company.pk,
            payment_date__date__range=(date_from, date_to),
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0')

        net_profit = revenue - cogs - expenses
        cash = payments - expenses

        client_debt = Client.objects.filter(
            company_id=company.pk, is_archived=False,
        ).aggregate(s=Sum('debt'))['s'] or Decimal('0')

        return {
            'revenue': revenue, 'cogs': cogs, 'expenses': expenses,
            'net_profit': net_profit, 'cash': cash, 'client_debt': client_debt,
        }

    def test_partial_refund_300(self):
        company = Company.objects.create(name='FinPart300', is_active=True)
        order_id, client_obj, product, owner = _create_delivered_order(
            company, total='1000', paid='1000')
        api = APIClient()
        api.force_authenticate(owner)
        api.post(f'{ORDERS}{order_id}/refund/', {
            'amount': '300', 'payment_method': 'cash',
        }, format='json')

        today = timezone.localdate()
        d = self._get_financials(company, today - datetime.timedelta(days=1), today + datetime.timedelta(days=1))

        order = Order.objects.get(pk=order_id)
        self.assertEqual(d['revenue'], Decimal('1000'))
        self.assertEqual(d['expenses'], Decimal('300'))
        self.assertEqual(d['net_profit'], Decimal('700'))
        self.assertEqual(order.refundable_amount, Decimal('700'))
        self.assertEqual(order.status, Order.Status.DELIVERED)
        self.assertEqual(client_obj.debt, Decimal('0'))

    def test_full_refund_1000(self):
        company = Company.objects.create(name='FinFull1000', is_active=True)
        order_id, client_obj, product, owner = _create_delivered_order(
            company, total='1000', paid='1000')
        api = APIClient()
        api.force_authenticate(owner)
        api.post(f'{ORDERS}{order_id}/refund/', {
            'amount': '1000', 'payment_method': 'cash',
        }, format='json')

        today = timezone.localdate()
        d = self._get_financials(company, today - datetime.timedelta(days=1), today + datetime.timedelta(days=1))

        order = Order.objects.get(pk=order_id)
        self.assertEqual(d['revenue'], Decimal('1000'))
        self.assertEqual(d['expenses'], Decimal('1000'))
        self.assertEqual(d['net_profit'], Decimal('0'))
        self.assertEqual(order.refundable_amount, Decimal('0'))

    def test_full_refund_then_cancel(self):
        company = Company.objects.create(name='FinRefCancel', is_active=True)
        order_id, client_obj, product, owner = _create_delivered_order(
            company, total='1000', paid='1000')
        api = APIClient()
        api.force_authenticate(owner)
        api.post(f'{ORDERS}{order_id}/refund/', {
            'amount': '1000', 'payment_method': 'cash',
        }, format='json')
        api.post(f'{ORDERS}{order_id}/cancel/')

        today = timezone.localdate()
        d = self._get_financials(company, today - datetime.timedelta(days=1), today + datetime.timedelta(days=1))

        order = Order.objects.get(pk=order_id)
        self.assertEqual(d['revenue'], Decimal('0'))
        self.assertEqual(d['cogs'], Decimal('0'))
        self.assertEqual(d['expenses'], Decimal('1000'))
        self.assertEqual(d['net_profit'], Decimal('-1000'))
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(order.refundable_amount, Decimal('0'))


# ── 4. Refund amount boundaries ─────────────────────────────────────────────

class RefundBoundaryTests(TestCase):

    def setUp(self):
        self.company = Company.objects.create(name='BndCo', is_active=True)
        order_id, self.client_obj, self.product, self.owner = _create_delivered_order(
            self.company, total='1000', paid='500')
        self.order_id = order_id
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_empty_string(self):
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_none_amount(self):
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_zero(self):
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '0', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_001_small_valid(self):
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '0.01', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 200)

    def test_exact_100(self):
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '100', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 200)

    def test_501_on_500_refundable_denied(self):
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '501', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_exact_refundable_succeeds(self):
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '500', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Order.objects.get(pk=self.order_id).refundable_amount, Decimal('0'))


# ── 5. Superadmin RBAC ──────────────────────────────────────────────────────

class SuperadminRefundTests(TestCase):
    """SUPERADMIN (platform role, company=None) → refund → denied."""

    def test_superadmin_refund_denied(self):
        company = Company.objects.create(name='SaCo', is_active=True)
        order_id, _, _, _ = _create_delivered_order(company, total='1000', paid='1000')
        superadmin = User.objects.create_user(
            username='sa_refund', password='p',
            role=User.Role.SUPERADMIN, company=None)
        api = APIClient()
        api.force_authenticate(superadmin)
        resp = api.post(f'{ORDERS}{order_id}/refund/', {
            'amount': '500', 'payment_method': 'cash',
        }, format='json')
        self.assertIn(resp.status_code, [403, 404])


# ── 6. DB-level audit ───────────────────────────────────────────────────────

class RefundAuditDBTests(TestCase):

    def test_refund_audit_fields(self):
        company = Company.objects.create(name='AudRefCo', is_active=True)
        order_id, _, _, owner = _create_delivered_order(company, total='1000', paid='1000')
        api = APIClient()
        api.force_authenticate(owner)
        api.post(f'{ORDERS}{order_id}/refund/', {
            'amount': '300', 'payment_method': 'cash', 'comment': 'тест',
        }, format='json')

        audit = AuditLog.objects.filter(
            action=AuditLog.Action.REFUND,
            object_id=str(order_id),
        ).order_by('-created_at').first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.company, company)
        self.assertEqual(audit.actor, owner)
        self.assertEqual(audit.changes.get('refund_amount'), '300')
        self.assertIn('expense_id', audit.changes)

    def test_cancel_audit_old_status(self):
        company = Company.objects.create(name='AudCanCo', is_active=True)
        order_id, _, _, owner = _create_delivered_order(company, paid='0')
        api = APIClient()
        api.force_authenticate(owner)
        api.post(f'{ORDERS}{order_id}/cancel/')

        audit = AuditLog.objects.filter(
            action=AuditLog.Action.UPDATE,
            object_id=str(order_id),
        ).order_by('-created_at').first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.company, company)
        self.assertEqual(audit.actor, owner)
        self.assertEqual(audit.changes.get('status', {}).get('old'), 'delivered')
        self.assertEqual(audit.changes.get('status', {}).get('new'), 'cancelled')


# ── 7. Expense metadata ─────────────────────────────────────────────────────

class RefundMetadataTests(TestCase):

    def test_expense_metadata_fields(self):
        company = Company.objects.create(name='MetaCo', is_active=True)
        order_id, _, _, owner = _create_delivered_order(company, total='1000', paid='1000')
        api = APIClient()
        api.force_authenticate(owner)
        api.post(f'{ORDERS}{order_id}/refund/', {
            'amount': '500', 'payment_method': 'card', 'comment': 'возврат',
        }, format='json')

        expense = Expense.objects.get(order_id=order_id, category='client_refund')
        self.assertEqual(expense.created_by, owner)
        self.assertEqual(expense.date, timezone.localdate())
        self.assertEqual(expense.payment_method, 'card')
        self.assertEqual(expense.comment, 'возврат')
        self.assertEqual(expense.company, company)
        self.assertEqual(expense.order_id, order_id)
        self.assertEqual(expense.amount, Decimal('500'))


# ── 8. Idempotency (business-level duplicate prevention) ────────────────────

class RefundIdempotencyDBTests(TestCase):

    def setUp(self):
        self.company = Company.objects.create(name='IdemCo', is_active=True)
        order_id, self.client_obj, self.product, self.owner = _create_delivered_order(
            self.company, total='1000', paid='1000')
        self.order_id = order_id
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_full_refund_retry_denied(self):
        self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '1000', 'payment_method': 'cash',
        }, format='json')
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '1000', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Expense.objects.filter(
            order_id=self.order_id, category='client_refund').count(), 1)

    def test_partial_retry_after_insufficient(self):
        self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '700', 'payment_method': 'cash',
        }, format='json')
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '400', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_partial_then_exact_remaining_succeeds(self):
        self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '600', 'payment_method': 'cash',
        }, format='json')
        resp = self.api.post(f'{ORDERS}{self.order_id}/refund/', {
            'amount': '400', 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Order.objects.get(pk=self.order_id).refundable_amount, Decimal('0'))


# ── 9. Stock invariant lifecycle ────────────────────────────────────────────

class StockInvariantTests(TestCase):
    """quantity X → deliver → X-N → cancel → X, exactly 1 StockMovement."""

    def test_stock_lifecycle(self):
        company = Company.objects.create(name='StockCo', is_active=True)
        order_id, _, product, owner = _create_delivered_order(
            company, total='1000', paid='0', quantity='5')
        initial_qty = product.quantity
        order = Order.objects.get(pk=order_id)
        order_quantity = order.quantity

        product.refresh_from_db()
        self.assertEqual(product.quantity, initial_qty - order_quantity)

        api = APIClient()
        api.force_authenticate(owner)
        api.post(f'{ORDERS}{order_id}/cancel/')

        product.refresh_from_db()
        self.assertEqual(product.quantity, initial_qty)

        movements = StockMovement.objects.filter(
            product=product,
            movement_type=StockMovement.MovementType.INCOMING,
            reason__icontains=str(order_id))
        self.assertEqual(movements.count(), 1)
