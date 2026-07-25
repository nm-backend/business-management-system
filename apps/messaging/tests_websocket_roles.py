"""
Live-тесты WebSocket чата между ролями SkladPro.Nod.

Проверяет:
1. Owner → Admin (общий чат компании)
2. Admin → Worker (личный диалог)
3. Worker → Owner (личный диалог с can_write_to_owner)
4. REST API + WebSocket интеграция
5. Система уведомлений
6. Безопасность (worker без прав)
"""
from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User
from apps.companies.models import Company
from apps.messaging.models import ChatMessage, Conversation, Notification
from apps.messaging.routing import websocket_urlpatterns
from apps.messaging.services import (
    ensure_general_conversation,
    get_or_create_direct,
    broadcast_message,
    notify,
    notify_staff,
    unread_count,
)
import uuid
from apps.messaging.ws_auth import JWTAuthMiddleware


class WebSocketRoleTests(TransactionTestCase):
    """Тестирование WebSocket чата между всеми ролями."""

    def setUp(self):
        uid = uuid.uuid4().hex[:8]
        self.company = Company.objects.create(name=f'TestCompany_{uid}')
        self.owner = User.objects.create_user(
            username=f'owner_{uid}', password='owner1234',
            role=User.Role.OWNER, company=self.company,
            full_name='Хозяин Тестов',
        )
        self.admin = User.objects.create_user(
            username=f'admin_{uid}', password='admin1234',
            role=User.Role.ADMIN, company=self.company,
            full_name='Администратор Тестов',
        )
        self.worker = User.objects.create_user(
            username=f'worker_{uid}', password='worker1234',
            role=User.Role.WORKER, company=self.company,
            full_name='Работник Тестов',
            can_write_to_owner=True,
        )
        self.restricted_worker = User.objects.create_user(
            username=f'restricted_{uid}', password='pw12345678',
            role=User.Role.WORKER, company=self.company,
            can_write_to_owner=False,
        )
        self.rest = APIClient()
        self.ws_app = JWTAuthMiddleware(URLRouter(websocket_urlpatterns))

    def tearDown(self):
        ChatMessage.objects.filter(company=self.company).delete()
        Notification.objects.filter(company=self.company).delete()
        Conversation.objects.filter(company=self.company).delete()
        User.objects.filter(company=self.company).delete()
        Company.objects.filter(pk=self.company.pk).delete()
        super().tearDown()

    def _token(self, user):
        return str(AccessToken.for_user(user))

    @database_sync_to_async
    def _async_token(self, user):
        return self._token(user)

    @database_sync_to_async
    def _ensure_general(self):
        return ensure_general_conversation(self.company)

    @database_sync_to_async
    def _create_dm(self, user_a, user_b):
        conv, _ = get_or_create_direct(self.company, user_a, user_b)
        return conv

    @database_sync_to_async
    def _create_and_broadcast(self, conversation, sender, content):
        message = ChatMessage.objects.create(
            company=self.company,
            conversation=conversation,
            sender=sender,
            content=content,
        )
        broadcast_message(message)
        return message

    @database_sync_to_async
    def _create_notifications(self):
        return notify_staff(
            self.company, Notification.NotificationType.NEW_ORDER,
            'Янги буюртма', 'Буюртма #5',
        )

    @database_sync_to_async
    def _create_worker_notification(self):
        return notify(
            self.worker, Notification.NotificationType.TASK_ASSIGNED,
            'Янги вазифа', 'Вазифа #10',
        )

    @database_sync_to_async
    def _get_unread_count(self, conv, user):
        return unread_count(conv, user)

    @database_sync_to_async
    def _rest_get(self, user, url, data=None):
        self.rest.force_authenticate(user=user)
        if data:
            return self.rest.post(url, data, format='json')
        return self.rest.get(url)

    @database_sync_to_async
    def _rest_post(self, user, url, data):
        self.rest.force_authenticate(user=user)
        return self.rest.post(url, data, format='json')

    async def _connect_ws(self, user):
        """Подключает WebSocket и возвращает communicator."""
        token = await self._async_token(user)
        communicator = WebsocketCommunicator(self.ws_app, f'/ws/chat/?token={token}')
        connected, _ = await communicator.connect()
        greeting = await communicator.receive_json_from()
        return connected, greeting, communicator

    # ─────────────── Тест 1: Все роли подключаются ───────────────

    async def test_01_all_roles_can_connect(self):
        """✅ Все три роли подключаются к WebSocket."""
        connected_o, _, ws_o = await self._connect_ws(self.owner)
        self.assertTrue(connected_o)

        connected_a, _, ws_a = await self._connect_ws(self.admin)
        self.assertTrue(connected_a)

        connected_w, _, ws_w = await self._connect_ws(self.worker)
        self.assertTrue(connected_w)

        await ws_o.disconnect()
        await ws_a.disconnect()
        await ws_w.disconnect()

    # ─────────────── Тест 2: Owner → General → Admin ───────────────

    async def test_02_owner_to_general_admin_receives(self):
        """✅ Owner → General чат → Admin получает real-time."""
        _, _, ws_o = await self._connect_ws(self.owner)
        _, _, ws_a = await self._connect_ws(self.admin)

        general = await self._ensure_general()
        await self._create_and_broadcast(general, self.owner, 'Всем привет! Это хозяин.')

        received = await ws_a.receive_json_from()
        self.assertEqual(received['type'], 'message')
        self.assertEqual(received['message']['content'], 'Всем привет! Это хозяин.')
        self.assertEqual(received['message']['sender'], self.owner.id)
        self.assertEqual(received['message']['sender_name'], 'Хозяин Тестов')
        self.assertEqual(received['message']['conversation_kind'], 'general')

        await ws_o.disconnect()
        await ws_a.disconnect()

    # ─────────────── Тест 3: Admin → DM → Worker ───────────────

    async def test_03_admin_dms_worker_realtime(self):
        """✅ Admin → DM → Worker получает real-time."""
        _, _, ws_a = await self._connect_ws(self.admin)
        _, _, ws_w = await self._connect_ws(self.worker)

        dm = await self._create_dm(self.admin, self.worker)
        await self._create_and_broadcast(dm, self.admin, 'Привет! Сделай задачу №5.')

        received = await ws_w.receive_json_from()
        self.assertEqual(received['type'], 'message')
        self.assertEqual(received['message']['content'], 'Привет! Сделай задачу №5.')
        self.assertEqual(received['message']['sender'], self.admin.id)

        await ws_a.disconnect()
        await ws_w.disconnect()

    # ─────────────── Тест 4: Worker → DM → Owner ───────────────

    async def test_04_worker_dms_owner_realtime(self):
        """✅ Worker → DM → Owner получает real-time."""
        _, _, ws_w = await self._connect_ws(self.worker)
        _, _, ws_o = await self._connect_ws(self.owner)

        dm = await self._create_dm(self.worker, self.owner)
        await self._create_and_broadcast(dm, self.worker, 'Хозяин, нужна помощь!')

        received = await ws_o.receive_json_from()
        self.assertEqual(received['type'], 'message')
        self.assertEqual(received['message']['content'], 'Хозяин, нужна помощь!')
        self.assertEqual(received['message']['sender'], self.worker.id)

        await ws_w.disconnect()
        await ws_o.disconnect()

    # ─────────────── Тест 5: REST API ───────────────

    async def test_05_rest_api_flow(self):
        """✅ REST API: диалог → сообщение → чтение → счётчик."""
        # Owner → Admin диалог
        resp = await self._rest_post(
            self.owner, '/api/v1/messaging/conversations/start_direct/',
            {'user_id': self.admin.id},
        )
        self.assertEqual(resp.status_code, 200)
        conv_id = resp.data['id']

        # Owner отправляет сообщение
        msg_resp = await self._rest_post(
            self.owner, '/api/v1/messaging/messages/',
            {'conversation': conv_id, 'content': 'Админ, проверь склад!'},
        )
        self.assertEqual(msg_resp.status_code, 201)
        self.assertTrue(msg_resp.data['is_mine'])

        # Admin видит беседу с непрочитанным
        convs = await self._rest_get(self.admin, '/api/v1/messaging/conversations/')
        rows = convs.data['results'] if isinstance(convs.data, dict) else convs.data
        target = next((c for c in rows if c['id'] == conv_id), None)
        self.assertIsNotNone(target)
        self.assertGreater(target['unread_count'], 0)

        # Admin читает сообщения
        msgs = await self._rest_get(
            self.admin, f'/api/v1/messaging/conversations/{conv_id}/messages/'
        )
        self.assertEqual(len(msgs.data), 1)
        self.assertEqual(msgs.data[0]['content'], 'Админ, проверь склад!')
        self.assertFalse(msgs.data[0]['is_mine'])

        # Admin отмечает прочитанным
        read = await self._rest_post(
            self.admin, f'/api/v1/messaging/conversations/{conv_id}/read/', {}
        )
        self.assertEqual(read.status_code, 200)

        # Проверяем счётчик
        dm = await self._create_dm(self.admin, self.owner)
        count = await self._get_unread_count(dm, self.admin)
        self.assertEqual(count, 0)

    # ─────────────── Тест 6: Уведомления ───────────────

    async def test_06_notifications(self):
        """✅ Уведомления: создание, фильтрация, чтение."""
        # notify_staff → owner + admin
        notes = await self._create_notifications()
        self.assertEqual(len(notes), 2)
        recipients = set(n.user_id for n in notes)
        self.assertIn(self.owner.id, recipients)
        self.assertIn(self.admin.id, recipients)

        # notify → worker
        w_notes = await self._create_worker_notification()
        self.assertEqual(len(w_notes), 1)
        self.assertEqual(w_notes[0].user_id, self.worker.id)

        # REST: owner видит непрочитанные
        resp = await self._rest_get(self.owner, '/api/v1/messaging/notifications/?is_read=false')
        results = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(results), 1)

        # Mark all read
        await self._rest_post(self.owner, '/api/v1/messaging/notifications/mark_all_read/', {})
        resp2 = await self._rest_get(self.owner, '/api/v1/messaging/notifications/?is_read=false')
        results2 = resp2.data['results'] if isinstance(resp2.data, dict) else resp2.data
        self.assertEqual(len(results2), 0)

    # ─────────────── Тест 7: Безопасность ───────────────

    async def test_07_security(self):
        """✅ Безопасность: worker без прав ≠ owner."""
        # Restricted → owner = 400
        resp = await self._rest_post(
            self.restricted_worker, '/api/v1/messaging/conversations/start_direct/',
            {'user_id': self.owner.id},
        )
        self.assertEqual(resp.status_code, 400)

        # Worker с правами → owner = 200
        resp2 = await self._rest_post(
            self.worker, '/api/v1/messaging/conversations/start_direct/',
            {'user_id': self.owner.id},
        )
        self.assertEqual(resp2.status_code, 200)

        # Admin → owner = 200
        resp3 = await self._rest_post(
            self.admin, '/api/v1/messaging/conversations/start_direct/',
            {'user_id': self.owner.id},
        )
        self.assertEqual(resp3.status_code, 200)

    # ─────────────── Тест 8: WebSocket + REST ───────────────

    async def test_08_websocket_and_rest_integration(self):
        """✅ WebSocket получает эхо REST-отправки."""
        _, _, ws_o = await self._connect_ws(self.owner)
        _, _, ws_w = await self._connect_ws(self.worker)

        # Worker пишет в общий чат через REST
        general = await self._ensure_general()
        msg_resp = await self._rest_post(
            self.worker, '/api/v1/messaging/messages/',
            {'conversation': general.id, 'content': 'Всем привет от работника!'},
        )
        self.assertEqual(msg_resp.status_code, 201)

        # Owner получает через WebSocket
        received = await ws_o.receive_json_from()
        self.assertEqual(received['type'], 'message')
        self.assertEqual(received['message']['content'], 'Всем привет от работника!')
        self.assertEqual(received['message']['sender'], self.worker.id)

        await ws_o.disconnect()
        await ws_w.disconnect()
