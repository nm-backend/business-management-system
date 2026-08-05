"""
Уведомление NEW_MESSAGE создаётся только за первое непрочитанное сообщение
личного диалога (баг тестировщика: пока страница открыта, каждый следующий
ответ плодил ещё одно уведомление — спам; счётчики вкладки чата уже
показывают непрочитанные).
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.messaging.models import ChatMessage, Conversation, Notification


class NewMessageNotificationDedupTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='DedupCo', is_active=True)
        self.owner = User.objects.create_user(username='dd_owner', password='p',
                                              role=User.Role.OWNER, company=self.company)
        self.worker = User.objects.create_user(username='dd_worker', password='p',
                                               role=User.Role.WORKER, company=self.company)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _start_direct(self):
        resp = self.api.post('/api/v1/messaging/conversations/start_direct/',
                             {'user_id': self.worker.id}, format='json')
        self.assertEqual(resp.status_code, 200)
        return resp.data['id']

    def _send(self, conversation_id, user, content):
        self.api.force_authenticate(user)
        resp = self.api.post('/api/v1/messaging/messages/',
                             {'conversation': conversation_id, 'content': content}, format='json')
        self.assertEqual(resp.status_code, 201)
        return resp

    def test_only_first_unread_message_notifies(self):
        conv = self._start_direct()
        self._send(conv, self.owner, 'Первое сообщение')
        notes = Notification.objects.filter(user=self.worker, type=Notification.NotificationType.NEW_MESSAGE)
        self.assertEqual(notes.count(), 1)

        self._send(conv, self.owner, 'Второе сообщение (работник не читал)')
        self.assertEqual(Notification.objects.filter(user=self.worker, type=Notification.NotificationType.NEW_MESSAGE).count(), 1)

    def test_after_read_next_message_notifies_again(self):
        conv = self._start_direct()
        self._send(conv, self.owner, 'Первое')
        # Работник открывает диалог и читает
        self.api.force_authenticate(self.worker)
        self.api.post(f'/api/v1/messaging/conversations/{conv}/read/', {}, format='json')
        # Новое сообщение после чтения — снова одно уведомление
        self._send(conv, self.owner, 'Второе')
        self.assertEqual(Notification.objects.filter(user=self.worker, type=Notification.NotificationType.NEW_MESSAGE).count(), 2)

    def test_sender_never_notified(self):
        conv = self._start_direct()
        self._send(conv, self.worker, 'Привет')
        self.assertEqual(Notification.objects.filter(user=self.owner, type=Notification.NotificationType.NEW_MESSAGE).count(), 1)
        self._send(conv, self.worker, 'Второе')
        self.assertEqual(Notification.objects.filter(user=self.owner, type=Notification.NotificationType.NEW_MESSAGE).count(), 1)
