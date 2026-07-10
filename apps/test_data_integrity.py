import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.core.models import Currency
from apps.finance.models import Expense
from apps.orders.models import Order, PaymentStatus
from apps.production.models import WorkRecord
from apps.warehouse.models import FinishedProduct, RawMaterial, StockMovement


class NonNegativeValidationTests(TestCase):
    def test_order_and_work_quantities_must_be_positive(self):
        client = Client.objects.create(name='Client')
        order = Order(
            client=client,
            quantity=Decimal('0'),
            unit='sht',
            deadline=datetime.date(2030, 1, 1),
        )
        with self.assertRaises(ValidationError):
            order.full_clean()

        worker = User.objects.create_user('worker', role=User.Role.WORKER)
        work = WorkRecord(
            worker=worker,
            quantity=Decimal('0'),
            unit='sht',
        )
        with self.assertRaises(ValidationError):
            work.full_clean()

    def test_money_and_stock_values_cannot_be_negative(self):
        client = Client(name='Client', debt=Decimal('-1'))
        with self.assertRaises(ValidationError):
            client.full_clean()

        expense = Expense(
            category='rent',
            amount=Decimal('-1'),
            date=datetime.date(2030, 1, 1),
        )
        with self.assertRaises(ValidationError):
            expense.full_clean()

        product = FinishedProduct(name='Product', quantity=Decimal('-1'))
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_stock_movement_quantity_must_be_positive(self):
        material = RawMaterial.objects.create(name='Material')
        movement = StockMovement(
            movement_type=StockMovement.MovementType.OUTGOING,
            material=material,
            quantity=Decimal('0'),
        )
        with self.assertRaises(ValidationError):
            movement.full_clean()

    def test_database_constraint_rejects_negative_order_total(self):
        client = Client.objects.create(name='Client')
        with self.assertRaises(IntegrityError):
            Order.objects.create(
                client=client,
                quantity=Decimal('1'),
                unit='sht',
                deadline=datetime.date(2030, 1, 1),
                total_amount=Decimal('-1'),
            )


class PaymentUpdateAPITests(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.owner = User.objects.create_user(
            'owner', password='secret123', role=User.Role.OWNER
        )
        client = Client.objects.create(name='Client')
        self.order = Order.objects.create(
            client=client,
            quantity=Decimal('1'),
            unit='sht',
            deadline=datetime.date(2030, 1, 1),
            total_amount=Decimal('100.00'),
        )
        self.api.force_authenticate(self.owner)
        self.url = f'/api/v1/orders/{self.order.pk}/update_payment/'

    def test_invalid_and_overpayments_are_rejected(self):
        for payload in ({}, {'amount': '-1'}, {'amount': 'not-a-number'}):
            response = self.api.post(self.url, payload)
            self.assertEqual(response.status_code, 400)

        response = self.api.post(
            self.url, {'amount': '101.00', 'payment_status': 'paid'}
        )
        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal('0.00'))

    def test_payment_status_is_derived_from_amount(self):
        response = self.api.post(
            self.url, {'amount': '40.00', 'payment_status': 'paid'}
        )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_amount, Decimal('40.00'))
        self.assertEqual(self.order.payment_status, PaymentStatus.PARTIAL)

        response = self.api.post(self.url, {'amount': '100.00'})
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, PaymentStatus.PAID)


class OwnerSetupTests(TestCase):
    def test_second_owner_setup_is_rejected(self):
        api = APIClient()
        payload = {
            'username': 'owner',
            'password': 'secret123',
            'password_confirm': 'secret123',
            'full_name': 'First Owner',
        }
        self.assertEqual(
            api.post('/api/v1/accounts/setup/owner/', payload).status_code,
            201,
        )

        payload.update({'username': 'second-owner'})
        response = api.post('/api/v1/accounts/setup/owner/', payload)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(User.objects.filter(role=User.Role.OWNER).count(), 1)


class UserCreationAuthorizationTests(TestCase):
    def test_admin_owner_request_is_forbidden_before_role_uniqueness_validation(self):
        User.objects.create_user('owner', password='secret123', role=User.Role.OWNER)
        admin = User.objects.create_user(
            'admin',
            password='secret123',
            role=User.Role.ADMIN,
            can_create_workers=True,
        )
        api = APIClient()
        api.force_authenticate(admin)

        response = api.post(
            '/api/v1/accounts/users/',
            {
                'username': 'attempted-owner',
                'password': 'secret123',
                'full_name': 'Attempted Owner',
                'role': User.Role.OWNER,
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username='attempted-owner').exists())

    def test_owner_second_owner_request_is_a_clean_validation_error(self):
        owner = User.objects.create_user(
            'owner',
            password='secret123',
            role=User.Role.OWNER,
        )
        api = APIClient()
        api.force_authenticate(owner)

        response = api.post(
            '/api/v1/accounts/users/',
            {
                'username': 'second-owner',
                'password': 'secret123',
                'full_name': 'Second Owner',
                'role': User.Role.OWNER,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username='second-owner').exists())


class StockHistoryProtectionTests(TestCase):
    def test_material_and_product_with_movements_cannot_be_deleted(self):
        material = RawMaterial.objects.create(name='Material')
        product = FinishedProduct.objects.create(name='Product')
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.INCOMING,
            material=material,
            quantity=Decimal('1'),
        )
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.PRODUCTION_IN,
            product=product,
            quantity=Decimal('1'),
        )

        with self.assertRaises(ProtectedError):
            material.delete()
        with self.assertRaises(ProtectedError):
            product.delete()
