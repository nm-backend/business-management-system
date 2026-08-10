"""
Одноразовые WS-тикеты вместо access-токена в query-строке WebSocket-URL.

Access-токен в query-строке попадал в логи прокси/балансировщиков.
Теперь клиент получает короткоживущий одноразовый тикет по REST
(GET /api/v1/messaging/ws-ticket/), а WebSocket открывает только с ним.
"""
import uuid
from datetime import timedelta

from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.messaging.models import WsTicket
from apps.messaging.routing import websocket_urlpatterns
from apps.messaging.services import issue_ws_ticket
from apps.messaging.ws_auth import TicketAuthMiddleware

TICKET_URL = '/api/v1/messaging/ws-ticket/'


class WsTicketApiTests(TransactionTestCase):
    def setUp(self):
        uid = uuid.uuid4().hex[:8]
        self.company = Company.objects.create(name=f'WsT_{uid}')
        self.owner = User.objects.create_user(
            username=f'wst_owner_{uid}', password='pw', role=User.Role.OWNER, company=self.company,
        )
        self.superadmin = User.objects.create_user(
            username=f'wst_super_{uid}', password='pw', role=User.Role.SUPERADMIN,
        )
        self.api = APIClient()
        self.ws_app = TicketAuthMiddleware(URLRouter(websocket_urlpatterns))

    def tearDown(self):
        User.objects.filter(company=self.company).delete()
        Company.objects.filter(pk=self.company.pk).delete()
        super().tearDown()

    def test_endpoint_issues_ticket(self):
        self.api.force_authenticate(self.owner)
        resp = self.api.get(TICKET_URL)
        self.assertEqual(resp.status_code, 200)
        ticket = resp.data['ticket']
        self.assertTrue(len(ticket) >= 32)
        saved = WsTicket.objects.get(ticket=ticket)
        self.assertEqual(saved.user, self.owner)
        self.assertFalse(saved.used)

    def test_superadmin_without_company_is_rejected(self):
        self.api.force_authenticate(self.superadmin)
        resp = self.api.get(TICKET_URL)
        self.assertEqual(resp.status_code, 403)

    def test_ticket_requires_auth(self):
        resp = self.api.get(TICKET_URL)
        self.assertEqual(resp.status_code, 401)

    async def test_ticket_cannot_be_reused(self):
        ticket = await self._ticket(self.owner)

        communicator1 = WebsocketCommunicator(self.ws_app, f'/ws/chat/?ticket={ticket}')
        connected1, _ = await communicator1.connect()
        self.assertTrue(connected1)

        communicator2 = WebsocketCommunicator(self.ws_app, f'/ws/chat/?ticket={ticket}')
        connected2, _ = await communicator2.connect()
        self.assertFalse(connected2)

        await communicator1.disconnect()
        await communicator2.disconnect()

    async def test_blocked_user_cannot_connect(self):
        worker = await self._make_blocked_user()
        ticket = await self._ticket(worker)
        communicator = WebsocketCommunicator(self.ws_app, f'/ws/chat/?ticket={ticket}')
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

    async def test_expired_ticket_cannot_connect(self):
        ticket = await self._expired_ticket()
        communicator = WebsocketCommunicator(self.ws_app, f'/ws/chat/?ticket={ticket}')
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

    async def test_ticket_of_disabled_user_cannot_connect(self):
        """is_active=False — тикет не пускает (сокет блокированного аккаунта)."""
        inactive = await self._make_inactive_user()
        ticket = await self._ticket(inactive)
        communicator = WebsocketCommunicator(self.ws_app, f'/ws/chat/?ticket={ticket}')
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

    async def _ticket(self, user):
        from channels.db import database_sync_to_async
        return await database_sync_to_async(issue_ws_ticket)(user)

    @database_sync_to_async
    def _make_blocked_user(self):
        return User.objects.create_user(
            username=f'blocked_{uuid.uuid4().hex[:6]}', password='pw',
            role=User.Role.WORKER, company=self.company, blocked_by_owner=True,
        )

    @database_sync_to_async
    def _make_inactive_user(self):
        return User.objects.create_user(
            username=f'inactive_{uuid.uuid4().hex[:6]}', password='pw',
            role=User.Role.WORKER, company=self.company, is_active=False,
        )

    @database_sync_to_async
    def _expired_ticket(self):
        import secrets
        return WsTicket.objects.create(
            company=self.company, user=self.owner,
            ticket=secrets.token_urlsafe(32),
            expires_at=timezone.now() - timedelta(seconds=1),
        ).ticket
