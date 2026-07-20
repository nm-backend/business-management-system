"""
Тесты корпоративного чата и уведомлений.

Покрывают:
- модели и сервисные функции (общий чат, диалоги, счётчик непрочитанных);
- REST API (создание диалога, отправка/чтение сообщений, счётчики);
- ИЗОЛЯЦИЮ арендаторов и участие в беседе (нельзя достать чужое даже прямым
  запросом; не-участник не видит чужой диалог внутри своей же компании);
- права (супер-админ без компании не допускается);
- WebSocket-консьюмер (аутентификация по токену + доставка сообщения).
"""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User
from apps.companies.models import Company
from apps.messaging.models import (
    ChatMessage,
    Conversation,
    ConversationParticipant,
    Notification,
)
from apps.messaging.routing import websocket_urlpatterns
from apps.messaging.services import (
    ensure_general_conversation,
    get_or_create_direct,
    recipient_user_ids,
    unread_count,
)
from apps.messaging.ws_auth import JWTAuthMiddleware


def make_company(name):
    company = Company.objects.create(name=name)
    owner = User.objects.create_user(username=f'{name}_owner', password='pw', role=User.Role.OWNER, company=company)
    worker = User.objects.create_user(username=f'{name}_worker', password='pw', role=User.Role.WORKER, company=company)
    admin = User.objects.create_user(username=f'{name}_admin', password='pw', role=User.Role.ADMIN, company=company)
    return company, owner, worker, admin


# ─────────────────────────── Модели / сервисы ───────────────────────────

class ChatServiceTests(TestCase):
    def setUp(self):
        self.company, self.owner, self.worker, self.admin = make_company('Alpha')

    def test_general_is_unique_per_company(self):
        a = ensure_general_conversation(self.company)
        b = ensure_general_conversation(self.company)
        self.assertEqual(a.id, b.id)
        self.assertEqual(a.kind, Conversation.Kind.GENERAL)
        self.assertEqual(Conversation.objects.filter(company=self.company, kind='general').count(), 1)

    def test_get_or_create_direct_is_idempotent(self):
        conv1, created1 = get_or_create_direct(self.company, self.owner, self.worker)
        conv2, created2 = get_or_create_direct(self.company, self.worker, self.owner)
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(conv1.id, conv2.id)
        self.assertEqual(conv1.participants.count(), 2)

    def test_unread_count_excludes_own_and_respects_read_pointer(self):
        conv, _ = get_or_create_direct(self.company, self.owner, self.worker)
        ChatMessage.objects.create(company=self.company, conversation=conv, sender=self.owner, content='hi')
        # Отправитель своё сообщение «прочитал».
        self.assertEqual(unread_count(conv, self.owner), 0)
        # Получатель ещё не читал -> 1 непрочитанное.
        self.assertEqual(unread_count(conv, self.worker), 1)

    def test_recipient_ids_general_is_all_company(self):
        general = ensure_general_conversation(self.company)
        ids = set(recipient_user_ids(general))
        self.assertEqual(ids, {self.owner.id, self.worker.id, self.admin.id})

    def test_recipient_ids_direct_is_participants(self):
        conv, _ = get_or_create_direct(self.company, self.owner, self.worker)
        self.assertEqual(set(recipient_user_ids(conv)), {self.owner.id, self.worker.id})

    def test_str_reprs(self):
        conv = ensure_general_conversation(self.company)
        msg = ChatMessage.objects.create(company=self.company, conversation=conv, sender=self.owner, content='hello world')
        self.assertIn('hello world'[:10], str(msg))
        self.assertTrue(str(conv))


# ─────────────────────────── REST API ───────────────────────────

class ChatAPITests(TestCase):
    def setUp(self):
        self.company, self.owner, self.worker, self.admin = make_company('Alpha')
        self.api = APIClient()

    def auth(self, user):
        self.api.force_authenticate(user=user)

    def test_conversations_list_creates_general(self):
        self.auth(self.worker)
        resp = self.api.get('/api/v1/messaging/conversations/')
        self.assertEqual(resp.status_code, 200)
        rows = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        kinds = [c['kind'] for c in rows]
        self.assertIn('general', kinds)

    def test_general_endpoint_returns_general(self):
        self.auth(self.owner)
        resp = self.api.get('/api/v1/messaging/conversations/general/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['kind'], 'general')

    def test_start_direct_and_send_message(self):
        self.auth(self.owner)
        start = self.api.post('/api/v1/messaging/conversations/start_direct/',
                              {'user_id': self.worker.id}, format='json')
        self.assertEqual(start.status_code, 200)
        conv_id = start.data['id']

        send = self.api.post('/api/v1/messaging/messages/',
                             {'conversation': conv_id, 'content': 'Salom!'}, format='json')
        self.assertEqual(send.status_code, 201)
        self.assertEqual(send.data['content'], 'Salom!')
        self.assertTrue(send.data['is_mine'])
        msg = ChatMessage.objects.get(pk=send.data['id'])
        self.assertEqual(msg.company_id, self.company.id)
        self.assertEqual(msg.sender_id, self.owner.id)

    def test_message_list_and_unread_flow(self):
        conv, _ = get_or_create_direct(self.company, self.owner, self.worker)
        # Владелец пишет два сообщения.
        self.auth(self.owner)
        for text in ('one', 'two'):
            self.api.post('/api/v1/messaging/messages/', {'conversation': conv.id, 'content': text}, format='json')

        # Работник видит беседу с 2 непрочитанными.
        self.auth(self.worker)
        conv_list = self.api.get('/api/v1/messaging/conversations/').data
        rows = conv_list['results'] if isinstance(conv_list, dict) else conv_list
        target = next(c for c in rows if c['id'] == conv.id)
        self.assertEqual(target['unread_count'], 2)

        # Сообщения приходят в хронологическом порядке.
        msgs = self.api.get(f'/api/v1/messaging/conversations/{conv.id}/messages/').data
        self.assertEqual([m['content'] for m in msgs], ['one', 'two'])

        # После чтения — 0 непрочитанных.
        read = self.api.post(f'/api/v1/messaging/conversations/{conv.id}/read/')
        self.assertEqual(read.status_code, 200)
        self.assertEqual(unread_count(conv, self.worker), 0)

    def test_empty_message_rejected(self):
        conv = ensure_general_conversation(self.company)
        self.auth(self.owner)
        resp = self.api.post('/api/v1/messaging/messages/',
                             {'conversation': conv.id, 'content': '   '}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_start_direct_with_self_rejected(self):
        self.auth(self.owner)
        resp = self.api.post('/api/v1/messaging/conversations/start_direct/',
                             {'user_id': self.owner.id}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_employees_search(self):
        self.auth(self.owner)
        resp = self.api.get('/api/v1/messaging/employees/?search=worker')
        rows = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        usernames = [u['username'] for u in rows]
        self.assertIn(self.worker.username, usernames)
        self.assertNotIn(self.admin.username, usernames)
        self.assertNotIn(self.owner.username, usernames)  # себя не показываем


# ─────────────────────────── Изоляция / участие ───────────────────────────

class ChatIsolationTests(TestCase):
    def setUp(self):
        self.company, self.owner, self.worker, self.admin = make_company('Alpha')
        self.other_company, self.b_owner, self.b_worker, _ = make_company('Beta')
        self.api = APIClient()

    def auth(self, user):
        self.api.force_authenticate(user=user)

    def test_non_participant_cannot_read_direct_in_same_company(self):
        # Диалог owner<->worker; admin (та же компания) не участник.
        conv, _ = get_or_create_direct(self.company, self.owner, self.worker)
        ChatMessage.objects.create(company=self.company, conversation=conv, sender=self.owner, content='private')
        self.auth(self.admin)
        self.assertEqual(self.api.get(f'/api/v1/messaging/conversations/{conv.id}/').status_code, 404)
        self.assertEqual(self.api.get(f'/api/v1/messaging/conversations/{conv.id}/messages/').status_code, 404)
        # И отправить в чужой диалог нельзя.
        post = self.api.post('/api/v1/messaging/messages/',
                             {'conversation': conv.id, 'content': 'x'}, format='json')
        self.assertEqual(post.status_code, 400)

    def test_cannot_access_other_company_conversation(self):
        conv_b, _ = get_or_create_direct(self.other_company, self.b_owner, self.b_worker)
        self.auth(self.owner)
        self.assertEqual(self.api.get(f'/api/v1/messaging/conversations/{conv_b.id}/').status_code, 404)
        self.assertEqual(self.api.get(f'/api/v1/messaging/conversations/{conv_b.id}/messages/').status_code, 404)

    def test_cannot_start_direct_across_companies(self):
        self.auth(self.owner)
        resp = self.api.post('/api/v1/messaging/conversations/start_direct/',
                             {'user_id': self.b_worker.id}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_employees_never_leak_other_company(self):
        self.auth(self.owner)
        resp = self.api.get('/api/v1/messaging/employees/')
        rows = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        usernames = [u['username'] for u in rows]
        self.assertTrue(all('Beta' not in u for u in usernames))


# ─────────────────────────── Права ───────────────────────────

class ChatPermissionTests(TestCase):
    def setUp(self):
        self.company, self.owner, self.worker, self.admin = make_company('Alpha')
        self.superadmin = User.objects.create_superuser(username='root', password='pw12345X')
        self.api = APIClient()

    def test_superadmin_blocked_from_chat(self):
        self.api.force_authenticate(user=self.superadmin)
        self.assertEqual(self.api.get('/api/v1/messaging/conversations/').status_code, 403)
        self.assertEqual(self.api.get('/api/v1/messaging/employees/').status_code, 403)

    def test_anonymous_blocked(self):
        self.assertEqual(self.api.get('/api/v1/messaging/conversations/').status_code, 401)

    def test_worker_cannot_start_direct_with_owner_without_permission(self):
        """Работник без can_write_to_owner не может начать диалог с хозяином."""
        self.worker.can_write_to_owner = False
        self.worker.save()
        self.api.force_authenticate(user=self.worker)
        resp = self.api.post('/api/v1/messaging/conversations/start_direct/',
                             {'user_id': self.owner.id}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_worker_can_start_direct_with_owner_with_permission(self):
        """Работник с can_write_to_owner может начать диалог с хозяином."""
        self.worker.can_write_to_owner = True
        self.worker.save()
        self.api.force_authenticate(user=self.worker)
        resp = self.api.post('/api/v1/messaging/conversations/start_direct/',
                             {'user_id': self.owner.id}, format='json')
        self.assertEqual(resp.status_code, 200)

    def test_admin_can_always_message_owner(self):
        """Админ всегда может писать хозяину."""
        self.api.force_authenticate(user=self.admin)
        resp = self.api.post('/api/v1/messaging/conversations/start_direct/',
                             {'user_id': self.owner.id}, format='json')
        self.assertEqual(resp.status_code, 200)


# ─────────────────────────── WebSocket ───────────────────────────

class ChatConsumerTests(TransactionTestCase):
    """
    Проверяет аутентификацию WebSocket по access-токену и доставку события
    в персональную группу пользователя. Канальный слой — in-memory (тестовые
    настройки), поэтому Redis не требуется.
    """
    def setUp(self):
        self.company = Company.objects.create(name='WsCo')
        self.user = User.objects.create_user(
            username='ws_user', password='pw', role=User.Role.OWNER, company=self.company,
        )
        # JWTAuthMiddleware поверх маршрутов чата (без origin-валидатора для теста).
        self.application = JWTAuthMiddleware(URLRouter(websocket_urlpatterns))

    def _token(self, user):
        return str(AccessToken.for_user(user))

    async def test_authenticated_connection_receives_broadcast(self):
        token = await self._async_token()
        communicator = WebsocketCommunicator(self.application, f'/ws/chat/?token={token}')
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        greeting = await communicator.receive_json_from()
        self.assertEqual(greeting['type'], 'connected')

        # Отправляем событие в персональную группу пользователя.
        channel_layer = get_channel_layer()
        await channel_layer.group_send(
            f'chat_user_{self.user.id}',
            {'type': 'chat.message', 'message': {'id': 1, 'content': 'ping'}},
        )
        received = await communicator.receive_json_from()
        self.assertEqual(received['type'], 'message')
        self.assertEqual(received['message']['content'], 'ping')

        await communicator.disconnect()

    async def test_bad_token_is_rejected(self):
        communicator = WebsocketCommunicator(self.application, '/ws/chat/?token=not-a-real-token')
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

    async def _async_token(self):
        from channels.db import database_sync_to_async
        return await database_sync_to_async(self._token)(self.user)


# ─────────────────────────── Уведомления ───────────────────────────

class NotificationTests(TestCase):
    def test_is_unread(self):
        self.assertTrue(Notification(is_read=False).is_unread)
        self.assertFalse(Notification(is_read=True).is_unread)

    def test_str_shows_type_and_title(self):
        note = Notification(type=Notification.NotificationType.NEW_ORDER, title='Order #1')
        self.assertEqual(str(note), 'Янги буюртма - Order #1')
