import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.core.models import Currency, ExchangeRate
from apps.messaging.models import Message, Notification
from apps.orders.models import Order
from apps.production.models import Task, WorkRecord
from apps.warehouse.models import FinishedProduct


class APIAuthorizationMatrixTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.owner = User.objects.create_user('owner', role=User.Role.OWNER)
        self.admin = User.objects.create_user(
            'admin', role=User.Role.ADMIN, can_create_workers=True
        )
        self.worker = User.objects.create_user('worker', role=User.Role.WORKER)
        self.other_worker = User.objects.create_user(
            'other-worker', role=User.Role.WORKER
        )

        self.client_record = Client.objects.create(
            name='Client', debt=Decimal('125.00')
        )
        self.other_client = Client.objects.create(name='Other Client')
        self.product = FinishedProduct.objects.create(name='Product')
        self.currency = Currency.objects.create(
            code='USD', name='Dollar', symbol='$'
        )
        self.other_currency = Currency.objects.create(
            code='KGS', name='Som', symbol='с'
        )
        self.rate = ExchangeRate.objects.create(
            from_currency=self.currency,
            to_currency=self.other_currency,
            rate=Decimal('89.00'),
            effective_date=datetime.date(2024, 1, 1),
        )
        self.order = self._order(self.worker, self.client_record)
        self.other_order = self._order(self.other_worker, self.other_client)
        self.task = Task.objects.create(
            order=self.order,
            worker=self.worker,
            assigned_by=self.admin,
        )
        self.other_task = Task.objects.create(
            order=self.other_order,
            worker=self.other_worker,
            assigned_by=self.admin,
        )
        self.work = WorkRecord.objects.create(
            task=self.task,
            worker=self.worker,
            product=self.product,
            quantity=Decimal('2'),
            unit='sht',
        )
        self.other_work = WorkRecord.objects.create(
            task=self.other_task,
            worker=self.other_worker,
            product=self.product,
            quantity=Decimal('3'),
            unit='sht',
        )
        self.message = Message.objects.create(
            sender=self.worker,
            recipient=self.owner,
            subject='Private',
            content='Message',
        )
        self.other_message = Message.objects.create(
            sender=self.other_worker,
            recipient=self.owner,
            subject='Other',
            content='Other message',
        )
        self.notification = Notification.objects.create(
            user=self.worker,
            type=Notification.NotificationType.NEW_MESSAGE,
            title='Private',
            message='Notification',
        )
        self.other_notification = Notification.objects.create(
            user=self.other_worker,
            type=Notification.NotificationType.NEW_MESSAGE,
            title='Other',
            message='Other notification',
        )

    def _order(self, worker, client):
        return Order.objects.create(
            client=client,
            product=self.product,
            worker=worker,
            quantity=Decimal('1'),
            unit='sht',
            deadline=datetime.date(2030, 1, 1),
            total_amount=Decimal('100.00'),
            paid_amount=Decimal('25.00'),
        )

    def authenticate(self, user):
        self.api.force_authenticate(user=user)

    @staticmethod
    def results(response):
        data = response.data
        return data.get('results', data) if isinstance(data, dict) else data

    def test_clients_are_owner_admin_only_and_hide_debt_indicators(self):
        self.authenticate(self.worker)
        self.assertEqual(self.api.get('/api/v1/clients/').status_code, 403)
        self.assertEqual(
            self.api.get(f'/api/v1/clients/{self.client_record.pk}/').status_code,
            403,
        )
        self.assertEqual(
            self.api.post('/api/v1/clients/', {'name': 'Worker client'}).status_code,
            403,
        )

        self.authenticate(self.admin)
        response = self.api.get('/api/v1/clients/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('has_debt', self.results(response)[0])
        self.assertEqual(
            self.api.post('/api/v1/clients/', {'name': 'Admin client'}).status_code,
            201,
        )
        self.assertEqual(
            self.api.delete(f'/api/v1/clients/{self.client_record.pk}/').status_code,
            405,
        )

        self.authenticate(self.owner)
        response = self.api.get(f'/api/v1/clients/{self.client_record.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('debt', response.data)
        self.assertIn('has_debt', response.data)
        self.assertEqual(
            self.api.post(
                f'/api/v1/clients/{self.client_record.pk}/archive/'
            ).status_code,
            200,
        )

    def test_currencies_and_rates_are_owner_write_admin_read_only(self):
        self.authenticate(self.admin)
        self.assertEqual(
            self.api.get('/api/v1/core/currencies/').status_code, 200
        )
        self.assertEqual(
            self.api.post(
                '/api/v1/core/currencies/',
                {'code': 'EUR', 'name': 'Euro', 'symbol': '€'},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.api.post(
                '/api/v1/core/exchange-rates/',
                {
                    'from_currency': self.currency.pk,
                    'to_currency': self.other_currency.pk,
                    'rate': '90',
                    'effective_date': '2024-02-01',
                },
            ).status_code,
            403,
        )
        self.assertEqual(
            self.api.delete(
                f'/api/v1/core/currencies/{self.currency.pk}/'
            ).status_code,
            403,
        )

        self.authenticate(self.owner)
        self.assertEqual(
            self.api.post(
                '/api/v1/core/currencies/',
                {'code': 'EUR', 'name': 'Euro', 'symbol': '€'},
            ).status_code,
            201,
        )
        self.assertEqual(
            self.api.delete(
                f'/api/v1/core/currencies/{self.currency.pk}/'
            ).status_code,
            405,
        )
        self.assertEqual(
            self.api.delete(
                f'/api/v1/core/exchange-rates/{self.rate.pk}/'
            ).status_code,
            405,
        )

    def test_orders_are_scoped_and_nonowners_receive_no_payment_state(self):
        self.authenticate(self.worker)
        response = self.api.get('/api/v1/orders/')
        self.assertEqual(response.status_code, 200)
        rows = self.results(response)
        self.assertEqual({row['id'] for row in rows}, {self.order.pk})
        self.assertEqual(
            self.api.get(f'/api/v1/orders/{self.other_order.pk}/').status_code,
            404,
        )
        self.assertEqual(
            self.api.post(
                '/api/v1/orders/',
                {
                    'client': self.client_record.pk,
                    'quantity': '1',
                    'unit': 'sht',
                    'deadline': '2030-01-01',
                },
            ).status_code,
            403,
        )
        self.assertEqual(
            self.api.patch(
                f'/api/v1/orders/{self.order.pk}/',
                {'status': 'cancelled'},
            ).status_code,
            403,
        )

        self.authenticate(self.admin)
        response = self.api.get('/api/v1/orders/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('payment_status', self.results(response)[0])
        self.assertNotIn('is_paid', self.results(response)[0])
        self.assertNotIn('has_debt', self.results(response)[0])
        self.assertEqual(
            self.api.post(
                f'/api/v1/orders/{self.order.pk}/assign_worker/',
                {'worker_id': self.other_worker.pk},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.api.post(
                f'/api/v1/orders/{self.order.pk}/update_payment/',
                {'payment_status': 'paid', 'amount': '100'},
            ).status_code,
            403,
        )

        self.authenticate(self.owner)
        response = self.api.get(f'/api/v1/orders/{self.order.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('payment_status', response.data)
        self.assertIn('is_paid', response.data)
        self.assertIn('has_debt', response.data)
        self.assertEqual(
            self.api.delete(f'/api/v1/orders/{self.order.pk}/').status_code,
            405,
        )

    def test_production_is_scoped_and_server_controls_actor_fields(self):
        self.authenticate(self.worker)
        response = self.api.get('/api/v1/production/tasks/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {row['id'] for row in self.results(response)}, {self.task.pk}
        )
        self.assertEqual(
            self.api.get(f'/api/v1/production/tasks/{self.other_task.pk}/').status_code,
            404,
        )
        self.assertEqual(
            self.api.post(
                '/api/v1/production/tasks/',
                {'order': self.order.pk, 'worker': self.worker.pk},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.api.post(
                f'/api/v1/production/tasks/{self.task.pk}/accept/'
            ).status_code,
            200,
        )
        self.assertEqual(
            self.api.post(
                f'/api/v1/production/tasks/{self.other_task.pk}/accept/'
            ).status_code,
            404,
        )

        worker_work_response = self.api.post(
            '/api/v1/production/works/',
            {
                'task': self.task.pk,
                'worker': self.other_worker.pk,
                'product': self.product.pk,
                'quantity': '1',
                'unit': 'sht',
            },
        )
        self.assertEqual(worker_work_response.status_code, 201)
        worker_created_work = WorkRecord.objects.latest('id')
        self.assertEqual(worker_created_work.worker, self.worker)
        self.assertEqual(
            self.api.patch(
                f'/api/v1/production/works/{worker_created_work.pk}/',
                {'quantity': '2'},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.api.delete(
                f'/api/v1/production/works/{worker_created_work.pk}/'
            ).status_code,
            403,
        )

        self.authenticate(self.admin)
        response = self.api.post(
            '/api/v1/production/tasks/',
            {'order': self.order.pk, 'worker': self.worker.pk},
        )
        self.assertEqual(response.status_code, 201)
        created_task = Task.objects.latest('id')
        self.assertEqual(created_task.assigned_by, self.admin)
        self.assertEqual(
            self.api.patch(
                f'/api/v1/production/tasks/{created_task.pk}/',
                {'assigned_by': self.owner.pk},
            ).status_code,
            200,
        )
        created_task.refresh_from_db()
        self.assertEqual(created_task.assigned_by, self.admin)
        self.assertEqual(
            self.api.delete(
                f'/api/v1/production/tasks/{created_task.pk}/'
            ).status_code,
            405,
        )

        response = self.api.get('/api/v1/production/works/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('labor_cost', self.results(response)[0])
        response = self.api.post(
            '/api/v1/production/works/',
            {
                'task': self.task.pk,
                'worker': self.other_worker.pk,
                'product': self.product.pk,
                'quantity': '1',
                'unit': 'sht',
            },
        )
        self.assertEqual(response.status_code, 201)
        work = WorkRecord.objects.latest('id')
        self.assertEqual(work.worker, self.admin)
        self.assertEqual(
            self.api.post(
                f'/api/v1/production/works/{self.work.pk}/confirm/',
                {'labor_cost': '50'},
            ).status_code,
            200,
        )

        self.authenticate(self.owner)
        response = self.api.get(f'/api/v1/production/works/{self.work.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('labor_cost', response.data)
        self.assertEqual(
            self.api.delete(f'/api/v1/production/works/{self.work.pk}/').status_code,
            405,
        )

    def test_messages_are_participant_scoped_sender_owned_and_non_deletable(self):
        self.authenticate(self.worker)
        response = self.api.get('/api/v1/messaging/messages/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {row['id'] for row in self.results(response)},
            {self.message.pk},
        )
        self.assertEqual(
            self.api.get(
                f'/api/v1/messaging/messages/{self.other_message.pk}/'
            ).status_code,
            404,
        )
        response = self.api.patch(
            f'/api/v1/messaging/messages/{self.message.pk}/',
            {'recipient': self.other_worker.pk, 'content': 'Updated'},
        )
        self.assertEqual(response.status_code, 200)
        self.message.refresh_from_db()
        self.assertEqual(self.message.recipient, self.owner)
        self.assertEqual(self.message.content, 'Updated')
        self.assertEqual(
            self.api.delete(
                f'/api/v1/messaging/messages/{self.message.pk}/'
            ).status_code,
            405,
        )

        self.authenticate(self.owner)
        response = self.api.patch(
            f'/api/v1/messaging/messages/{self.message.pk}/',
            {'content': 'Recipient cannot edit'},
        )
        self.assertEqual(response.status_code, 403)

        response = self.api.get('/api/v1/messaging/notifications/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {row['id'] for row in self.results(response)},
            set(),
        )

        self.authenticate(self.worker)
        response = self.api.get('/api/v1/messaging/notifications/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {row['id'] for row in self.results(response)},
            {self.notification.pk},
        )
        self.assertEqual(
            self.api.post(
                '/api/v1/messaging/notifications/',
                {
                    'user': self.worker.pk,
                    'type': Notification.NotificationType.NEW_MESSAGE,
                    'title': 'Forged',
                    'message': 'Forged',
                },
            ).status_code,
            405,
        )
        self.assertEqual(
            self.api.delete(
                f'/api/v1/messaging/notifications/{self.notification.pk}/'
            ).status_code,
            405,
        )
        self.assertEqual(
            self.api.post(
                f'/api/v1/messaging/notifications/{self.notification.pk}/mark_read/'
            ).status_code,
            200,
        )

    def test_admin_cannot_create_owner_or_grant_capabilities(self):
        self.authenticate(self.admin)
        response = self.api.post(
            '/api/v1/accounts/users/',
            {
                'username': 'forbidden-owner',
                'password': 'secret123',
                'role': User.Role.OWNER,
                'can_write_to_owner': True,
                'can_create_workers': True,
                'can_see_other_workers': True,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username='forbidden-owner').exists())

        response = self.api.post(
            '/api/v1/accounts/users/',
            {
                'username': 'created-worker',
                'password': 'secret123',
                'role': User.Role.WORKER,
                'can_write_to_owner': True,
                'can_create_workers': True,
                'can_see_other_workers': True,
            },
        )
        self.assertEqual(response.status_code, 201)
        created = User.objects.get(username='created-worker')
        self.assertEqual(created.role, User.Role.WORKER)
        self.assertFalse(created.can_write_to_owner)
        self.assertFalse(created.can_create_workers)
        self.assertFalse(created.can_see_other_workers)
