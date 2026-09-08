"""
Тесты локализации уведомлений (требование ТЗ: уведомления переводятся).

Раньше текст уведомления формировался строкой прямо в коде: бизнес-события
всегда по-узбекски, подписки — по-русски, язык получателя не учитывался.
Теперь уведомление хранит ключ локали + параметры, а API отдаёт текст на
языке ТЕКУЩЕГО пользователя (сменил язык — переведётся и старая лента).
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.companies.models import Company
from apps.messaging.models import Notification
from apps.messaging.services import notify, notify_staff
from apps.orders.models import Order
from apps.production.models import RefusalReason, Task, TaskStatus
from core.utils import translate


class ServerSideTranslateTests(TestCase):
    def test_returns_language_specific_value(self):
        self.assertEqual(translate('common.save', 'ru'), 'Сохранить')
        self.assertEqual(translate('common.save', 'uz_cyrl'), 'Сақлаш')

    def test_falls_back_to_uzbek_for_missing_language(self):
        # Несуществующий язык -> базовый словарь uz_cyrl (как на фронтенде).
        self.assertEqual(translate('common.save', 'de'), translate('common.save', 'uz_cyrl'))

    def test_unknown_key_returns_key(self):
        self.assertEqual(translate('nope.nothing', 'ru'), 'nope.nothing')

    def test_placeholders_substituted(self):
        text = translate('notifications.msg_new_order', 'ru', {
            'id': 7, 'client': 'Акбаров', 'product': 'Столешница', 'qty': '2',
        })
        self.assertEqual(text, '#7 Акбаров: Столешница x 2')

    def test_key_params_are_translated_too(self):
        """reason_key='refusal_reasons.no_time' подставляется в {reason}."""
        text = translate('notifications.msg_task_refused', 'ru', {
            'id': 3, 'worker': 'Али', 'reason_key': 'refusal_reasons.no_time',
        })
        self.assertIn('Али', text)
        self.assertIn(translate('refusal_reasons.no_time', 'ru'), text)


class NotificationLocalizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='Granit')
        cls.owner_ru = User.objects.create_user(
            username='owner_ru', password='pw', role=User.Role.OWNER,
            company=cls.company, language='ru',
        )
        cls.admin_uz = User.objects.create_user(
            username='admin_uz', password='pw', role=User.Role.ADMIN,
            company=cls.company, language='uz_cyrl',
        )

    def test_each_recipient_gets_snapshot_in_own_language(self):
        """title/message — снимок на языке получателя (его читает Web Push)."""
        notify_staff(
            self.company,
            Notification.NotificationType.TASK_CANCELLED,
            title_key='notifications.task_cancelled',
            message_key='notifications.msg_task_cancelled',
            params={'id': 42},
        )
        ru = Notification.objects.get(user=self.owner_ru)
        uz = Notification.objects.get(user=self.admin_uz)
        self.assertEqual(ru.message, 'Задача #42 отменена')
        self.assertEqual(uz.message, 'Вазифа #42 бекор қилинди')
        self.assertNotEqual(ru.title, uz.title)

    def test_api_renders_in_current_language_after_switch(self):
        notify(
            self.owner_ru,
            Notification.NotificationType.TASK_CANCELLED,
            title_key='notifications.task_cancelled',
            message_key='notifications.msg_task_cancelled',
            params={'id': 7},
        )
        client = APIClient()
        client.force_authenticate(self.owner_ru)

        response = client.get('/api/v1/messaging/notifications/')
        results = response.data['results'] if 'results' in response.data else response.data
        self.assertEqual(results[0]['message'], 'Задача #7 отменена')

        # Пользователь переключил язык — старое уведомление тоже переводится.
        self.owner_ru.language = 'uz_cyrl'
        self.owner_ru.save(update_fields=['language'])
        client.force_authenticate(self.owner_ru)
        response = client.get('/api/v1/messaging/notifications/')
        results = response.data['results'] if 'results' in response.data else response.data
        self.assertEqual(results[0]['message'], 'Вазифа #7 бекор қилинди')

    def test_plain_text_notification_still_works(self):
        """Непереводимый текст (имя отправителя, комментарий) отдаётся как есть."""
        notify(
            self.owner_ru,
            Notification.NotificationType.NEW_MESSAGE,
            'Абдулазиз М.',
            'Материал етарли эмас',
        )
        client = APIClient()
        client.force_authenticate(self.owner_ru)
        response = client.get('/api/v1/messaging/notifications/')
        results = response.data['results'] if 'results' in response.data else response.data
        self.assertEqual(results[0]['title'], 'Абдулазиз М.')
        self.assertEqual(results[0]['message'], 'Материал етарли эмас')


class BusinessEventNotificationLanguageTests(TestCase):
    """События реальных сценариев приходят на языке получателя."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='Granit')
        cls.owner = User.objects.create_user(
            username='owner', password='pw', role=User.Role.OWNER,
            company=cls.company, language='ru',
        )
        cls.worker = User.objects.create_user(
            username='worker', password='pw', role=User.Role.WORKER,
            company=cls.company, language='uz_cyrl', full_name='Али',
        )
        cls.client_obj = Client.objects.create(company=cls.company, name='Акбаров')

    def test_new_order_notification_is_russian_for_russian_owner(self):
        api = APIClient()
        api.force_authenticate(self.owner)
        response = api.post('/api/v1/orders/orders/', {
            'client': self.client_obj.id,
            'custom_product_name': 'Столешница',
            'quantity': '2',
            'unit': 'sht',
            'total_amount': '1000.00',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)

        notification = Notification.objects.get(
            user=self.owner, type=Notification.NotificationType.NEW_ORDER,
        )
        self.assertEqual(notification.title, translate('notifications.new_order', 'ru'))
        self.assertIn('Акбаров', notification.message)

    def test_task_refusal_reason_is_localized(self):
        order = Order.objects.create(
            company=self.company, client=self.client_obj,
            custom_product_name='Столешница', quantity=Decimal('1'), unit='sht',
            total_amount=Decimal('100'), deadline=timezone.now(),
        )
        task = Task.objects.create(
            company=self.company, order=order, worker=self.worker,
            assigned_by=self.owner, status=TaskStatus.PENDING,
        )
        api = APIClient()
        api.force_authenticate(self.worker)
        response = api.post(f'/api/v1/production/tasks/{task.id}/refuse/', {
            'reason': RefusalReason.NO_TIME,
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)

        notification = Notification.objects.get(
            user=self.owner, type=Notification.NotificationType.WORKER_REFUSED,
        )
        # Владелец с русским языком видит причину по-русски.
        self.assertIn(translate('refusal_reasons.no_time', 'ru'), notification.message)
        self.assertIn('Али', notification.message)
