"""
API tests for messaging app.

Coverage:
- Message CRUD
- User sees only own messages (sent/received)
- mark_read action
- Notification read-only list
- mark_read / mark_all_read actions
- RBAC: all authenticated users can message within their permissions
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.messaging.models import Message, Notification


def _create_users():
    owner = User.objects.create_user(
        username='owner', password='owner123', role=User.Role.OWNER
    )
    admin = User.objects.create_user(
        username='admin', password='admin123', role=User.Role.ADMIN
    )
    worker = User.objects.create_user(
        username='worker', password='worker123', role=User.Role.WORKER
    )
    return owner, admin, worker


class MessageCRUDTests(TestCase):
    """Tests for Message CRUD."""

    def setUp(self):
        self.api = APIClient()
        self.owner, self.admin, self.worker = _create_users()

    def test_owner_can_send_message(self):
        self.api.force_authenticate(user=self.owner)
        response = self.api.post('/api/v1/messaging/messages/', {
            'recipient': self.admin.id,
            'subject': 'Urgent',
            'content': 'Please check the warehouse',
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(response.data['sender_name'], 'owner')

    def test_admin_can_send_message(self):
        self.api.force_authenticate(user=self.admin)
        response = self.api.post('/api/v1/messaging/messages/', {
            'recipient': self.worker.id,
            'subject': 'Task',
            'content': 'Start production order #5',
        })
        self.assertEqual(response.status_code, 201)

    def test_worker_can_send_message(self):
        self.api.force_authenticate(user=self.worker)
        response = self.api.post('/api/v1/messaging/messages/', {
            'recipient': self.admin.id,
            'subject': 'Question',
            'content': 'Need more material',
        })
        self.assertEqual(response.status_code, 201)

    def test_unauthenticated_cannot_send(self):
        response = self.api.post('/api/v1/messaging/messages/', {
            'recipient': 1,
            'content': 'Hello',
        })
        self.assertEqual(response.status_code, 401)

    def test_user_sees_only_own_messages(self):
        self.api.force_authenticate(user=self.owner)
        self.api.post('/api/v1/messaging/messages/', {
            'recipient': self.admin.id,
            'content': 'Hello admin',
        })
        response = self.api.get('/api/v1/messaging/messages/')
        self.assertEqual(response.status_code, 200)
        data = response.json() if hasattr(response, 'content') else response.data
        results = data.get('results', data) if isinstance(data, dict) else data
        self.assertEqual(len(results), 1)

        self.api.force_authenticate(user=self.admin)
        response = self.api.get('/api/v1/messaging/messages/')
        data = response.json() if hasattr(response, 'content') else response.data
        results = data.get('results', data) if isinstance(data, dict) else data
        self.assertEqual(len(results), 1)

        self.api.force_authenticate(user=self.worker)
        response = self.api.get('/api/v1/messaging/messages/')
        data = response.json() if hasattr(response, 'content') else response.data
        results = data.get('results', data) if isinstance(data, dict) else data
        self.assertEqual(len(results), 0)

    def test_mark_read_changes_status(self):
        self.api.force_authenticate(user=self.admin)
        msg = Message.objects.create(
            sender=self.owner, recipient=self.admin, content='Test message'
        )
        self.assertFalse(msg.is_read)
        response = self.api.post(f'/api/v1/messaging/messages/{msg.id}/mark_read/')
        self.assertEqual(response.status_code, 200)
        msg.refresh_from_db()
        self.assertTrue(msg.is_read)
        self.assertIsNotNone(msg.read_at)

    def test_cannot_mark_others_message_as_read(self):
        self.api.force_authenticate(user=self.worker)
        msg = Message.objects.create(
            sender=self.owner, recipient=self.admin, content='Private'
        )
        response = self.api.post(f'/api/v1/messaging/messages/{msg.id}/mark_read/')
        # 404 because worker's queryset doesn't include admin's messages
        self.assertEqual(response.status_code, 404)

    def test_filter_by_is_read(self):
        self.api.force_authenticate(user=self.admin)
        Message.objects.create(sender=self.owner, recipient=self.admin, content='A', is_read=True)
        Message.objects.create(sender=self.owner, recipient=self.admin, content='B', is_read=False)
        response = self.api.get('/api/v1/messaging/messages/?is_read=true')
        self.assertEqual(response.status_code, 200)
        data = response.json() if hasattr(response, 'content') else response.data
        results = data.get('results', data) if isinstance(data, dict) else data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['content'], 'A')

    def test_is_unread_property(self):
        msg = Message(sender=self.owner, recipient=self.admin, content='X')
        self.assertTrue(msg.is_unread)
        msg.is_read = True
        self.assertFalse(msg.is_unread)


class NotificationTests(TestCase):
    """Tests for Notification read-only + actions."""

    def setUp(self):
        self.api = APIClient()
        self.owner, self.admin, self.worker = _create_users()

    def test_user_sees_only_own_notifications(self):
        self.api.force_authenticate(user=self.owner)
        Notification.objects.create(
            user=self.owner, type='new_order', title='Order #1',
            message='New order created',
        )
        Notification.objects.create(
            user=self.admin, type='new_order', title='Order #2',
            message='Another order',
        )
        response = self.api.get('/api/v1/messaging/notifications/')
        self.assertEqual(response.status_code, 200)
        data = response.json() if hasattr(response, 'content') else response.data
        results = data.get('results', data) if isinstance(data, dict) else data
        self.assertEqual(len(results), 1)

    def test_mark_read(self):
        self.api.force_authenticate(user=self.admin)
        notif = Notification.objects.create(
            user=self.admin, type='task_assigned', title='Task',
            message='You have a new task'
        )
        response = self.api.post(f'/api/v1/messaging/notifications/{notif.id}/mark_read/')
        self.assertEqual(response.status_code, 200)
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_cannot_mark_others_notification(self):
        self.api.force_authenticate(user=self.worker)
        notif = Notification.objects.create(
            user=self.admin, type='test', title='Test', message='Test'
        )
        response = self.api.post(f'/api/v1/messaging/notifications/{notif.id}/mark_read/')
        # 404 because worker's queryset doesn't include admin's notifications
        self.assertEqual(response.status_code, 404)

    def test_mark_all_read(self):
        self.api.force_authenticate(user=self.admin)
        Notification.objects.create(
            user=self.admin, type='a', title='A', message='A', is_read=False,
        )
        Notification.objects.create(
            user=self.admin, type='b', title='B', message='B', is_read=False,
        )
        response = self.api.post('/api/v1/messaging/notifications/mark_all_read/')
        self.assertEqual(response.status_code, 200)
        unread = Notification.objects.filter(user=self.admin, is_read=False).count()
        self.assertEqual(unread, 0)

    def test_notification_is_unread_property(self):
        n = Notification(user=self.admin, type='test', title='T', message='M')
        self.assertTrue(n.is_unread)
        n.is_read = True
        self.assertFalse(n.is_unread)

    def test_filter_by_is_read(self):
        self.api.force_authenticate(user=self.admin)
        Notification.objects.create(
            user=self.admin, type='a', title='A', message='A', is_read=True,
        )
        Notification.objects.create(
            user=self.admin, type='b', title='B', message='B', is_read=False,
        )
        response = self.api.get('/api/v1/messaging/notifications/?is_read=false')
        self.assertEqual(response.status_code, 200)
        data = response.json() if hasattr(response, 'content') else response.data
        results = data.get('results', data) if isinstance(data, dict) else data
        self.assertEqual(len(results), 1)
