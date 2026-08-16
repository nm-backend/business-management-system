"""
Права и изоляция (IDOR) billing-эндпоинтов.

  - владелец видит ТОЛЬКО подписку своей компании;
  - работник/админ не могут управлять подпиской;
  - список всех подписок и все изменяющие операции — только супер-админ;
  - владелец не может продлить/заморозить/подтвердить счёт чужой компании.
"""
from datetime import timedelta

from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.messaging.routing import websocket_urlpatterns
from apps.messaging.services import issue_ws_ticket
from apps.messaging.ws_auth import TicketAuthMiddleware

from .models import Invoice, Subscription
from .services import create_invoice, freeze_subscription


class BillingPermissionTests(TestCase):
    def setUp(self):
        self.company_a, self.owner_a = self._company('AlphaB')
        self.company_b, self.owner_b = self._company('BetaB')
        self.worker_a = User.objects.create_user(
            username='alpha_worker', password='pw',
            role=User.Role.WORKER, company=self.company_a,
        )
        self.admin_a = User.objects.create_user(
            username='alpha_admin', password='pw',
            role=User.Role.ADMIN, company=self.company_a,
        )
        self.superadmin = User.objects.create_superuser(username='root', password='pw')
        self.sub_a = Subscription.objects.get(company=self.company_a)
        self.sub_b = Subscription.objects.get(company=self.company_b)
        self.api = APIClient()

    @staticmethod
    def _company(name):
        company = Company.objects.create(name=name)
        owner = User.objects.create_user(
            username=f'{name}_owner', password='pw', role=User.Role.OWNER, company=company,
        )
        return company, owner

    def test_owner_sees_only_own_subscription(self):
        self.api.force_authenticate(user=self.owner_a)
        resp = self.api.get('/api/v1/billing/subscription/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['company'], self.company_a.id)
        self.assertEqual(resp.data['id'], self.sub_a.id)

    def test_worker_and_admin_cannot_manage_subscription(self):
        for user in (self.worker_a, self.admin_a):
            self.api.force_authenticate(user=user)
            self.assertEqual(
                self.api.get('/api/v1/billing/subscription/').status_code, 403,
            )
            self.assertEqual(
                self.api.post('/api/v1/billing/subscription/renew/', {}, format='json').status_code,
                403,
            )

    def test_owner_cannot_list_all_subscriptions(self):
        self.api.force_authenticate(user=self.owner_a)
        self.assertEqual(self.api.get('/api/v1/billing/subscriptions/').status_code, 403)

    def test_superadmin_lists_all_subscriptions(self):
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.get('/api/v1/billing/subscriptions/')
        self.assertEqual(resp.status_code, 200)
        ids = [row['id'] for row in resp.data['results']]
        self.assertIn(self.sub_a.id, ids)
        self.assertIn(self.sub_b.id, ids)

    def test_superadmin_can_search_by_company(self):
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.get('/api/v1/billing/subscriptions/?search=Beta')
        self.assertEqual(resp.status_code, 200)
        ids = [row['id'] for row in resp.data['results']]
        self.assertNotIn(self.sub_a.id, ids)
        self.assertIn(self.sub_b.id, ids)

    def test_owner_cannot_modify_own_subscription_via_admin_api(self):
        # Изменяющие операции подписок — только супер-админ.
        self.api.force_authenticate(user=self.owner_a)
        for action, body in [
            ('extend', {'days': 30}),
            ('activate', {}),
            ('freeze', {}),
            ('unfreeze', {}),
            ('confirm_payment', {'invoice_id': 1}),
        ]:
            resp = self.api.post(
                f'/api/v1/billing/subscriptions/{self.sub_a.id}/{action}/',
                body, format='json',
            )
            self.assertEqual(resp.status_code, 403, action)

    def test_owner_cannot_extend_other_company(self):
        self.api.force_authenticate(user=self.owner_a)
        resp = self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub_b.id}/extend/',
            {'days': 30}, format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_owner_cannot_confirm_invoice_of_other_company(self):
        # Счёт компании B создан её владельцем; владелец A пытается его оплатить.
        invoice, _ = create_invoice(self.sub_b, actor=self.owner_b)
        self.api.force_authenticate(user=self.owner_a)
        resp = self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub_b.id}/confirm_payment/',
            {'invoice_id': invoice.id}, format='json',
        )
        self.assertEqual(resp.status_code, 403)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PENDING)

    def test_admin_api_rejects_unknown_invoice_for_subscription(self):
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub_a.id}/confirm_payment/',
            {'invoice_id': 999999}, format='json',
        )
        self.assertEqual(resp.status_code, 404)

    def test_extend_requires_valid_days(self):
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub_a.id}/extend/',
            {'days': 0}, format='json',
        )
        self.assertEqual(resp.status_code, 400)
        resp = self.api.post(
            f'/api/v1/billing/subscriptions/{self.sub_a.id}/extend/',
            {'days': 366}, format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_superadmin_is_not_affected_by_subscription_gate(self):
        # Супер-админ не привязан к компании — gate его не трогает (а
        # бизнес-данные ему закрыты IsCompanyMember, это другой механизм).
        self.api.force_authenticate(user=self.superadmin)
        resp = self.api.get('/api/v1/warehouse/raw-materials/')
        self.assertEqual(resp.status_code, 403)
        self.assertNotEqual(resp.data.get('code'), 'subscription_expired')

    def test_frozen_company_cannot_issue_ws_ticket(self):
        """
        Выдача WS-тикета (чат) — бизнес-функция: замороженная компания
        получает subscription_expired, а не тикет.

        Gate — middleware и видит только настоящий JWT в Authorization
        (force_authenticate его обходит), поэтому логинимся по-настоящему.
        """
        resp = self.api.post('/api/v1/accounts/login/', {
            'username': self.owner_a.username, 'password': 'pw',
            'fingerprint': 'x' * 32,
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        token = resp.data['tokens']['access']
        self.api.force_authenticate(user=None)
        self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        # До заморозки тикет выдаётся.
        self.assertEqual(self.api.get('/api/v1/messaging/ws-ticket/').status_code, 200)

        # Заморозка → тикет больше не выдаётся (бизнес-функция).
        Subscription.objects.filter(pk=self.sub_a.pk).update(
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.sub_a.refresh_from_db()
        self.assertTrue(freeze_subscription(self.sub_a))
        resp = self.api.get('/api/v1/messaging/ws-ticket/')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()['code'], 'subscription_expired')

        # А вот статус подписки и продление — whitelist, работают.
        self.assertEqual(self.api.get('/api/v1/billing/subscription/').status_code, 200)


class BillingWsGateTests(TransactionTestCase):
    """
    WebSocket-чат для замороженной компании не открывается даже по тикету,
    выданному до заморозки (тикет живёт до 60 секунд).
    """

    def setUp(self):
        self.company = Company.objects.create(name='WsFrozenCo')
        self.owner = User.objects.create_user(
            username='ws_frozen_owner', password='pw',
            role=User.Role.OWNER, company=self.company,
        )
        self.sub = Subscription.objects.get(company=self.company)
        self.ws_app = TicketAuthMiddleware(URLRouter(websocket_urlpatterns))

    async def test_ws_rejected_for_frozen_company(self):
        ticket = await database_sync_to_async(issue_ws_ticket)(self.owner)
        # Заморозка после выдачи тикета.
        await database_sync_to_async(self._expire_and_freeze)()
        communicator = WebsocketCommunicator(self.ws_app, f'/ws/chat/?ticket={ticket}')
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

    async def test_ws_ok_for_active_company(self):
        ticket = await database_sync_to_async(issue_ws_ticket)(self.owner)
        communicator = WebsocketCommunicator(self.ws_app, f'/ws/chat/?ticket={ticket}')
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.disconnect()

    def _expire_and_freeze(self):
        from datetime import timedelta
        from django.utils import timezone
        Subscription.objects.filter(pk=self.sub.pk).update(
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.sub.refresh_from_db()
        freeze_subscription(self.sub)
