"""
Unit-тесты для приложения messaging: свойства и строковые представления
моделей Message и Notification.
"""
from django.test import TestCase

from apps.accounts.models import User
from apps.messaging.models import Message, Notification


class MessageTests(TestCase):
    def test_is_unread(self):
        self.assertTrue(Message(is_read=False).is_unread)
        self.assertFalse(Message(is_read=True).is_unread)

    def test_str_with_subject(self):
        sender = User(username='alice')
        self.assertEqual(str(Message(sender=sender, subject='Hi')), 'alice - Hi')

    def test_str_without_subject(self):
        sender = User(username='alice')
        self.assertEqual(str(Message(sender=sender, subject='')), 'alice - No subject')


class NotificationTests(TestCase):
    def test_is_unread(self):
        self.assertTrue(Notification(is_read=False).is_unread)
        self.assertFalse(Notification(is_read=True).is_unread)

    def test_str_shows_type_and_title(self):
        note = Notification(type=Notification.NotificationType.NEW_ORDER, title='Order #1')
        self.assertEqual(str(note), 'Янги буюртма - Order #1')
