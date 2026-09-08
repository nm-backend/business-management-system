"""
Архив и группировка уведомлений (макет «Билдиришномалар»).

Вкладки макета: «Барчаси / Ўқилмаган / Архив», а сами уведомления сгруппированы
по смыслу («Янги буюртмалар», «Материал камчилиги», «Тасдиқлар», «Ўқилмаган
хабарлар», «Система хабарлари»).

Главное требование ТЗ: уведомления не теряются. Прочитанное остаётся в
истории, архивное уходит из основной ленты, но доступно по вкладке «Архив».
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.messaging.models import Notification
from apps.messaging.services import notify

NOTIFICATIONS = '/api/v1/messaging/notifications/'


class NotificationArchiveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='NotifCo')
        cls.owner = User.objects.create_user(
            username='na_owner', password='pw', role=User.Role.OWNER, company=cls.company,
        )
        cls.admin = User.objects.create_user(
            username='na_admin', password='pw', role=User.Role.ADMIN, company=cls.company,
        )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.notification = notify(
            self.owner, Notification.NotificationType.NEW_ORDER,
            title_key='notifications.new_order',
            message_key='notifications.msg_new_order',
            params={'id': 1, 'client': 'Акбаров', 'product': 'Столешница', 'qty': '1'},
        )[0]

    def _rows(self, response):
        data = response.data
        return data['results'] if 'results' in data else data

    def test_default_feed_hides_archived(self):
        self.notification.archive()
        self.assertEqual(len(self._rows(self.api.get(NOTIFICATIONS))), 0)

    def test_archive_tab_shows_archived(self):
        self.notification.archive()
        rows = self._rows(self.api.get(NOTIFICATIONS, {'is_archived': 'true'}))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['is_archived'])
        self.assertIsNotNone(rows[0]['archived_at'])

    def test_read_notification_is_not_lost(self):
        """Прочитанное остаётся в ленте — история уведомлений сохраняется."""
        self.api.post(f'{NOTIFICATIONS}{self.notification.id}/mark_read/')
        rows = self._rows(self.api.get(NOTIFICATIONS))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['is_read'])

    def test_archive_action_does_not_delete(self):
        response = self.api.post(f'{NOTIFICATIONS}{self.notification.id}/archive/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(Notification.objects.filter(pk=self.notification.pk).exists())

    def test_archive_is_idempotent(self):
        """Повторное архивирование не меняет дату — история не переписывается."""
        self.api.post(f'{NOTIFICATIONS}{self.notification.id}/archive/')
        self.notification.refresh_from_db()
        first_time = self.notification.archived_at

        self.api.post(f'{NOTIFICATIONS}{self.notification.id}/archive/')
        self.notification.refresh_from_db()
        self.assertEqual(self.notification.archived_at, first_time)

    def test_cannot_archive_foreign_notification(self):
        other = notify(
            self.admin, Notification.NotificationType.NEW_ORDER, 'Чужое', 'Сообщение',
        )[0]
        response = self.api.post(f'{NOTIFICATIONS}{other.id}/archive/')
        self.assertIn(response.status_code, (403, 404))
        other.refresh_from_db()
        self.assertFalse(other.is_archived)

    def test_category_derived_from_type(self):
        rows = self._rows(self.api.get(NOTIFICATIONS))
        self.assertEqual(rows[0]['category'], 'orders')

    def test_filter_by_category(self):
        notify(
            self.owner, Notification.NotificationType.NEW_MESSAGE, 'Абдулазиз', 'Привет',
        )
        orders = self._rows(self.api.get(NOTIFICATIONS, {'category': 'orders'}))
        messages = self._rows(self.api.get(NOTIFICATIONS, {'category': 'messages'}))
        self.assertEqual(len(orders), 1)
        self.assertEqual(len(messages), 1)
        self.assertEqual(orders[0]['category'], 'orders')
        self.assertEqual(messages[0]['category'], 'messages')

    def test_unknown_category_returns_empty(self):
        rows = self._rows(self.api.get(NOTIFICATIONS, {'category': 'нечто'}))
        self.assertEqual(len(rows), 0)

    def test_subscription_types_fall_into_system(self):
        notify(
            self.owner, Notification.NotificationType.SUBSCRIPTION_EXPIRING,
            'Обуна', 'Скоро истекает',
        )
        rows = self._rows(self.api.get(NOTIFICATIONS, {'category': 'system'}))
        self.assertEqual(len(rows), 1)

    def test_archived_not_counted_as_unread(self):
        unread_before = self._rows(self.api.get(NOTIFICATIONS, {'is_read': 'false'}))
        self.assertEqual(len(unread_before), 1)

        self.notification.archive()
        unread_after = self._rows(self.api.get(NOTIFICATIONS, {'is_read': 'false'}))
        self.assertEqual(len(unread_after), 0, 'архивное не должно висеть в непрочитанных')
