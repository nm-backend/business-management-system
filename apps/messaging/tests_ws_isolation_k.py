"""
Изоляция чата: чужие беседы/уведомления недоступны, длина сообщения
ограничена, WebSocket-группы не пересекаются между пользователями.

1. Отправка в беседу другой компании -> 400 «Беседа не найдена.»
2. Сообщение длиннее 10000 символов -> 400.
3. mark_read чужого уведомления -> 404 (в списке видны только свои).
4. WS: сообщение в группу пользователя B не доходит до соединения A
   (группа привязывается к владельцу тикета, не к тому, кто подсунул URL).
"""
import asyncio
import uuid

from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.messaging.models import Conversation, Notification
from apps.messaging.routing import websocket_urlpatterns
from apps.messaging.services import issue_ws_ticket
from apps.messaging.ws_auth import TicketAuthMiddleware

MESSAGES_URL = '/api/v1/messaging/messages/'


def make_user(username, company, role):
    return User.objects.create_user(
        username=username, password='pw', role=role, company=company,
    )


class ChatIsolationTests(TransactionTestCase):
    def setUp(self):
        uid = uuid.uuid4().hex[:8]
        self.company = Company.objects.create(name=f'ISO_{uid}')
        self.other = Company.objects.create(name=f'ISO2_{uid}')
        self.worker = make_user(f'iso_w_{uid}', self.company, User.Role.WORKER)
        self.colleague = make_user(f'iso_c_{uid}', self.company, User.Role.WORKER)
        self.foreign = make_user(f'iso_f_{uid}', self.other, User.Role.WORKER)
        self.api = APIClient()
        self.api.force_authenticate(user=self.worker)
        self.ws_app = TicketAuthMiddleware(URLRouter(websocket_urlpatterns))

    def tearDown(self):
        User.objects.filter(company__in=[self.company, self.other]).delete()
        Company.objects.filter(pk__in=[self.company.pk, self.other.pk]).delete()
        super().tearDown()

    # ── REST: изоляция объектов ────────────────────────────────

    def test_send_to_foreign_conversation_rejected(self):
        conv = Conversation.objects.create(
            company=self.other, kind=Conversation.Kind.DIRECT, created_by=self.foreign,
        )
        resp = self.api.post(MESSAGES_URL, {
            'conversation': conv.id, 'content': 'привет чужому',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Беседа не найдена.', str(resp.data))

    def test_message_length_capped(self):
        resp = self.api.post(MESSAGES_URL, {
            'conversation': 1, 'content': 'x' * 10001,
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('10000', str(resp.data))

    def test_mark_read_foreign_notification_404(self):
        note = Notification.objects.create(
            user=self.colleague, company=self.colleague.company,
            type=Notification.NotificationType.NEW_MESSAGE, title='t', message='m',
        )
        resp = self.api.post(f'/api/v1/messaging/notifications/{note.id}/mark_read/')
        self.assertEqual(resp.status_code, 404)

    def test_mark_read_own_notification_ok_and_russian(self):
        note = Notification.objects.create(
            user=self.worker, company=self.worker.company,
            type=Notification.NotificationType.NEW_MESSAGE, title='t', message='m',
        )
        resp = self.api.post(f'/api/v1/messaging/notifications/{note.id}/mark_read/')
        self.assertEqual(resp.status_code, 200)
        note.refresh_from_db()
        self.assertTrue(note.is_read)
        self.assertNotIn('You can only', resp.content.decode())

    # ── WS: группы изолированы между пользователями ────────────

    @database_sync_to_async
    def _ticket(self, user):
        return issue_ws_ticket(user)

    async def test_ws_groups_are_isolated_between_users(self):
        ticket_a = await self._ticket(self.worker)
        ticket_b = await self._ticket(self.colleague)
        comm_a = WebsocketCommunicator(self.ws_app, f'/ws/chat/?ticket={ticket_a}')
        comm_b = WebsocketCommunicator(self.ws_app, f'/ws/chat/?ticket={ticket_b}')
        ok_a, _ = await comm_a.connect()
        ok_b, _ = await comm_b.connect()
        self.assertTrue(ok_a)
        self.assertTrue(ok_b)
        self.assertEqual((await comm_a.receive_json_from(timeout=2))['type'], 'connected')
        self.assertEqual((await comm_b.receive_json_from(timeout=2))['type'], 'connected')

        layer = get_channel_layer()
        await layer.group_send(f'chat_user_{self.colleague.id}', {
            'type': 'chat.message',
            'message': {'id': 1, 'content': 'секрет только для B'},
        })

        event_b = await comm_b.receive_json_from(timeout=2)
        self.assertEqual(event_b['type'], 'message')
        self.assertEqual(event_b['message']['content'], 'секрет только для B')

        with self.assertRaises(asyncio.TimeoutError):
            await comm_a.receive_json_from(timeout=0.4)

        for comm in (comm_a, comm_b):
            try:
                await comm.disconnect()
            except (asyncio.CancelledError, Exception):
                pass

    async def test_ticket_binds_connection_to_issuer_group(self):
        ticket = await self._ticket(self.worker)
        comm = WebsocketCommunicator(self.ws_app, f'/ws/chat/?ticket={ticket}')
        ok, _ = await comm.connect()
        self.assertTrue(ok)
        self.assertEqual((await comm.receive_json_from(timeout=2))['type'], 'connected')

        layer = get_channel_layer()
        await layer.group_send(f'chat_user_{self.worker.id}', {
            'type': 'chat.message',
            'message': {'id': 2, 'content': 'для владельца тикета'},
        })
        event = await comm.receive_json_from(timeout=2)
        self.assertEqual(event['message']['content'], 'для владельца тикета')
        try:
            await comm.disconnect()
        except (asyncio.CancelledError, Exception):
            pass
