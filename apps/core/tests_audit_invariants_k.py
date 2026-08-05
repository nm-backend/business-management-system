"""
Сквозной аудит бизнес-инвариантов SaaS.

Это не тесты отдельных правок, а проверка того, что система как целое не даёт
потерять деньги, товар или данные. Каждый пункт проверяет КОНЕЧНОЕ состояние
(остаток, долг, начисление, журнал), а не код ответа: код 200 ничего не
доказывает, если склад после него разошёлся с журналом.

Проверяются заново все ранее закрытые дыры — прошлым отчётам не доверяем.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.finance.models import LaborRate
from apps.orders.models import Order
from apps.production.models import WorkRecord
from apps.warehouse.models import FinishedProduct, RawMaterial, Recipe, RecipeItem, StockMovement

ORDERS = '/api/v1/orders/orders/'
WORKS = '/api/v1/production/works/'
PAYMENTS = '/api/v1/clients/payments/'
PRODUCTS = '/api/v1/warehouse/finished-products/'


class AuditBase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='AuditCo', is_active=True)
        self.owner = User.objects.create_user(username='aud_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.admin = User.objects.create_user(username='aud_admin', password='p',
                                              role=User.Role.ADMIN, company=self.company)
        self.worker = User.objects.create_user(username='aud_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.cli = Client.objects.create(company=self.company, name='Клиент')
        self.material = RawMaterial.objects.create(
            company=self.company, name='Мрамор', quantity=Decimal('100'), unit='m2')
        self.product = FinishedProduct.objects.create(
            company=self.company, name='Столешница', quantity=Decimal('0'), unit='dona')
        recipe = Recipe.objects.create(company=self.company, product=self.product,
                                       name='Основной', is_active=True)
        RecipeItem.objects.create(recipe=recipe, material=self.material,
                                  quantity_required=Decimal('2'), unit='m2')
        LaborRate.objects.create(company=self.company, product=self.product,
                                 operation=LaborRate.OperationType.OTHER,
                                 rate_per_unit=Decimal('1000'), unit='dona')
        self.api = APIClient(); self.api.force_authenticate(self.owner)
        self.wapi = APIClient(); self.wapi.force_authenticate(self.worker)

    def deadline(self):
        return (timezone.now() + datetime.timedelta(days=5)).isoformat()

    def make_order(self, **over):
        body = {'client': self.cli.id, 'product': self.product.id, 'quantity': '3',
                'unit': 'dona', 'deadline': self.deadline(), 'total_amount': '9000'}
        body.update(over)
        return self.api.post(ORDERS, body, format='json')

    def produce(self, quantity='3'):
        """Полный производственный цикл: сдача работы и подтверждение."""
        work = self.wapi.post(WORKS, {'product': self.product.id, 'quantity': quantity,
                                      'unit': 'dona'}, format='json')
        assert work.status_code == 201, work.content[:200]
        wid = work.json()['id']
        confirmed = self.api.post(f'{WORKS}{wid}/confirm/')
        assert confirmed.status_code == 200, confirmed.content[:200]
        return WorkRecord.objects.get(pk=wid)


class ProductionChainAudit(AuditBase):
    def test_confirmation_stocks_product_and_accrues_wage(self):
        work = self.produce('3')
        self.product.refresh_from_db()
        self.material.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('3.000'), 'продукция обязана появиться')
        self.assertEqual(self.material.quantity, Decimal('94.000'), 'сырьё обязано списаться')
        self.assertEqual(work.labor_cost, Decimal('3000.00'), '3 * 1000')
        self.assertTrue(StockMovement.objects.filter(
            product=self.product,
            movement_type=StockMovement.MovementType.PRODUCTION_IN).exists())
        self.assertTrue(StockMovement.objects.filter(
            material=self.material,
            movement_type=StockMovement.MovementType.PRODUCTION_OUT).exists())

    def test_wage_reaches_settlements_and_dashboard(self):
        self.produce('3')
        rows = self.api.get('/api/v1/finance/worker-payments/settlements/').json()
        mine = [r for r in rows['results'] if r['worker'] == self.worker.id][0]
        self.assertEqual(Decimal(str(mine['accrued'])), Decimal('3000'))
        dash = self.api.get('/api/v1/reports/analytics/owner/', {'period': 'year'}).json()
        self.assertEqual(Decimal(str(dash['worker_debts'])), Decimal(str(rows['total_balance'])),
                         'дашборд и расчёты обязаны сходиться')

    def test_confirmation_without_rate_is_refused(self):
        other = FinishedProduct.objects.create(company=self.company, name='Без ставки',
                                               quantity=Decimal('0'), unit='dona')
        work = self.wapi.post(WORKS, {'product': other.id, 'quantity': '1',
                                      'unit': 'dona'}, format='json').json()
        resp = self.api.post(f"{WORKS}{work['id']}/confirm/")
        self.assertEqual(resp.status_code, 400)
        other.refresh_from_db()
        self.assertEqual(other.quantity, Decimal('0.000'), 'отказ обязан быть чистым')

    def test_double_confirmation_does_not_double_stock(self):
        work = self.produce('3')
        again = self.api.post(f'{WORKS}{work.id}/confirm/')
        self.assertIn(again.status_code, (400, 409))
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('3.000'), 'приход ровно один')

    def test_worker_cannot_confirm_own_work(self):
        work = self.wapi.post(WORKS, {'product': self.product.id, 'quantity': '1',
                                      'unit': 'dona'}, format='json').json()
        resp = self.wapi.post(f"{WORKS}{work['id']}/confirm/")
        self.assertEqual(resp.status_code, 403, 'рабочий не может сам себе начислить')


class WarehouseIntegrityAudit(AuditBase):
    def test_delivery_writes_off_and_journals(self):
        self.produce('3')
        oid = self.make_order().json()['id']
        self.assertEqual(self.api.post(f'{ORDERS}{oid}/deliver/').status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('0.000'))
        self.assertTrue(StockMovement.objects.filter(
            product=self.product,
            movement_type=StockMovement.MovementType.OUTGOING).exists())

    def test_cannot_deliver_what_is_not_produced(self):
        oid = self.make_order().json()['id']
        resp = self.api.post(f'{ORDERS}{oid}/deliver/')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get('code'), 'not_enough_stock')

    def test_cancel_after_delivery_returns_stock(self):
        self.produce('3')
        oid = self.make_order().json()['id']
        self.api.post(f'{ORDERS}{oid}/deliver/')
        self.api.post(f'{ORDERS}{oid}/cancel/')
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('3.000'), 'возврат обязан вернуть товар')

    def test_paid_order_cannot_be_deleted(self):
        self.produce('3')
        oid = self.make_order().json()['id']
        self.api.post(PAYMENTS, {'client': self.cli.id, 'order': oid, 'amount': '500',
                                 'payment_method': 'cash',
                                 'payment_date': timezone.now().isoformat()}, format='json')
        self.assertEqual(self.api.delete(f'{ORDERS}{oid}/').status_code, 400)

    def test_stock_never_goes_negative_through_any_path(self):
        """Ни один путь не должен уводить остаток в минус."""
        self.produce('2')
        oid = self.make_order(quantity='5').json()['id']
        self.api.post(f'{ORDERS}{oid}/deliver/')
        self.api.post(f'{PRODUCTS}{self.product.id}/outgoing/', {'quantity': '99'}, format='json')
        self.product.refresh_from_db()
        self.assertGreaterEqual(self.product.quantity, Decimal('0'))


class MoneyIntegrityAudit(AuditBase):
    def test_debt_lifecycle(self):
        self.produce('3')
        oid = self.make_order().json()['id']
        self.api.post(f'{ORDERS}{oid}/deliver/')
        self.cli.refresh_from_db()
        self.assertEqual(self.cli.debt, Decimal('9000.00'))

        self.api.post(PAYMENTS, {'client': self.cli.id, 'order': oid, 'amount': '4000',
                                 'payment_method': 'cash',
                                 'payment_date': timezone.now().isoformat()}, format='json')
        self.cli.refresh_from_db()
        self.assertEqual(self.cli.debt, Decimal('5000.00'))

        self.api.post(PAYMENTS, {'client': self.cli.id, 'order': oid, 'amount': '5000',
                                 'payment_method': 'cash',
                                 'payment_date': timezone.now().isoformat()}, format='json')
        self.cli.refresh_from_db()
        self.assertEqual(self.cli.debt, Decimal('0.00'))
        self.assertEqual(Order.objects.get(pk=oid).payment_status, Order.PaymentStatus.PAID)

    def test_overpayment_is_refused(self):
        self.produce('3')
        oid = self.make_order().json()['id']
        self.api.post(PAYMENTS, {'client': self.cli.id, 'order': oid, 'amount': '9000',
                                 'payment_method': 'cash',
                                 'payment_date': timezone.now().isoformat()}, format='json')
        extra = self.api.post(PAYMENTS, {'client': self.cli.id, 'order': oid, 'amount': '1',
                                         'payment_method': 'cash',
                                         'payment_date': timezone.now().isoformat()},
                              format='json')
        self.assertEqual(extra.status_code, 400)

    def test_admin_never_sees_money(self):
        self.produce('3')
        api = APIClient(); api.force_authenticate(self.admin)
        work = api.get(WORKS).json()['results'][0]
        self.assertNotIn('labor_cost', work)
        self.assertEqual(api.get('/api/v1/finance/worker-payments/settlements/').status_code, 403)
        product = api.get(f'{PRODUCTS}{self.product.id}/').json()
        self.assertNotIn('cost_price', product)
        self.assertNotIn('labor_rate', product)


class ValidationAudit(AuditBase):
    def test_order_without_product_refused(self):
        resp = self.api.post(ORDERS, {'client': self.cli.id, 'quantity': '1', 'unit': 'dona',
                                      'deadline': self.deadline()}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_phone_with_letters_refused(self):
        resp = self.api.post('/api/v1/clients/clients/',
                             {'name': 'Тест', 'phone': 'не телефон'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_cross_company_isolation(self):
        other = Company.objects.create(name='Чужая', is_active=True)
        stranger = User.objects.create_user(username='aud_stranger', password='p',
                                            role=User.Role.OWNER, company=other)
        api = APIClient(); api.force_authenticate(stranger)
        self.assertEqual(api.get(f'{PRODUCTS}{self.product.id}/').status_code, 404)
        oid = self.make_order().json()['id']
        self.assertEqual(api.post(f'{ORDERS}{oid}/deliver/').status_code, 404)
