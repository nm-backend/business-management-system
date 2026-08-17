"""
Тесты уведомлений о приближающемся окончании подписки.

Покрывают задачу notify_subscription_expiry (окна 7/1 день, идемпотентность,
push), колокольчик уведомлений для супер-админа и сотрудников, изоляцию
арендаторов и пометку устаревших алертов прочитанными при продлении.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.companies.models import Company
from apps.companies.tasks import notify_subscription_expiry
from apps.messaging.models import Notification

from .tests_subscriptions import make_admin, make_company, make_owner


class NotifySubscriptionExpiryTestCase(TestCase):
    """Общий setUp: суперадмин + компания (владелец и админ)."""

    def setUp(self):
        self.superadmin = User.objects.create_superuser(username='root', password='pw')
        self.company = make_company(name='Acme')
        self.owner = make_owner(self.company, username='acme_owner')
        self.admin = make_admin(self.company, username='acme_admin')
        self.other_company = make_company(name='OtherCo')
        self.other_owner = make_owner(self.other_company, username='other_owner')

    def _set_end(self, company, days):
        company.subscription_end = timezone.now() + timedelta(days=days)
        company.save(update_fields=['subscription_end'])

    def _alerts(self, user, ntype=None):
        qs = Notification.objects.filter(user=user)
        if ntype:
            qs = qs.filter(type=ntype)
        return list(qs)


class TaskTests(NotifySubscriptionExpiryTestCase):
    def test_seven_day_alert_created_for_staff_and_superadmin(self):
        self._set_end(self.company, 5)  # в 7-дневном окне, вне 1-дневного
        notified = notify_subscription_expiry.run()
        self.assertEqual(notified, 3)  # owner + admin + superadmin

        for user in (self.owner, self.admin, self.superadmin):
            alerts = self._alerts(user, Notification.NotificationType.SUBSCRIPTION_EXPIRING_SOON)
            self.assertEqual(len(alerts), 1, msg=user.username)
            self.assertEqual(alerts[0].company_id, self.company.id)
            self.assertFalse(alerts[0].is_read)
            self.assertIn(self.company.name, alerts[0].message)

        # Компания за пределами окна не трогается.
        self.assertEqual(self._alerts(self.other_owner), [])

    def test_one_day_alert_uses_expiring_type(self):
        self._set_end(self.company, 1)
        notify_subscription_expiry.run()
        alerts = self._alerts(self.owner, Notification.NotificationType.SUBSCRIPTION_EXPIRING)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(
            self._alerts(self.owner, Notification.NotificationType.SUBSCRIPTION_EXPIRING_SOON),
            [],
        )

    def test_company_within_one_day_gets_only_one_day_alert(self):
        # end = now + 6 часов: попадает и в 7-дневное, и в 1-дневное окно,
        # но тип должен быть только один — ближайший (1 день).
        self.company.subscription_end = timezone.now() + timedelta(hours=6)
        self.company.save(update_fields=['subscription_end'])
        notify_subscription_expiry.run()
        self.assertEqual(
            len(self._alerts(self.owner, Notification.NotificationType.SUBSCRIPTION_EXPIRING)),
            1,
        )
        self.assertEqual(
            self._alerts(self.owner, Notification.NotificationType.SUBSCRIPTION_EXPIRING_SOON),
            [],
        )

    def test_rerun_is_idempotent(self):
        self._set_end(self.company, 5)
        notify_subscription_expiry.run()
        notify_subscription_expiry.run()  # повторный запуск
        for user in (self.owner, self.admin, self.superadmin):
            self.assertEqual(
                len(self._alerts(user, Notification.NotificationType.SUBSCRIPTION_EXPIRING_SOON)),
                1,
                msg=user.username,
            )

    def test_read_notification_not_recreated(self):
        self._set_end(self.company, 5)
        notify_subscription_expiry.run()
        # Пользователь прочитал уведомление — следующий запуск в том же окне
        # НЕ создаёт новое (дедупликация по дате создания, а не по is_read).
        Notification.objects.update(is_read=True, read_at=timezone.now())
        notify_subscription_expiry.run()
        self.assertEqual(
            len(self._alerts(self.owner, Notification.NotificationType.SUBSCRIPTION_EXPIRING_SOON)),
            1,
        )

    def test_company_outside_window_not_notified(self):
        self._set_end(self.company, 10)  # дальше 7 дней
        notify_subscription_expiry.run()
        self.assertEqual(self._alerts(self.owner), [])
        self.assertEqual(self._alerts(self.superadmin), [])

    def test_non_active_company_not_notified(self):
        # Замороженная вручную компания с подходящим сроком — без уведомлений.
        self._set_end(self.company, 3)
        self.company.subscription_status = Company.SubscriptionStatus.FROZEN
        self.company.save(update_fields=['subscription_status'])
        notify_subscription_expiry.run()
        self.assertEqual(self._alerts(self.owner), [])
        self.assertEqual(self._alerts(self.superadmin), [])

    @patch('apps.accounts.push_service.send_push_to_user')
    def test_push_sent_to_all_recipients(self, mock_push):
        self._set_end(self.company, 5)
        notify_subscription_expiry.run()
        self.assertEqual(mock_push.call_count, 3)
        urls = {call.kwargs['data']['url'] for call in mock_push.call_args_list}
        self.assertIn('/#/companies', urls)
        self.assertIn('/#/', urls)
        for call in mock_push.call_args_list:
            self.assertIn(self.company.name, call.args[1])

    def test_no_push_without_vapid_keys_is_silent(self):
        # send_push_to_user без VAPID ключей возвращает False и не падает.
        self._set_end(self.company, 5)
        notified = notify_subscription_expiry.run()
        self.assertEqual(notified, 3)


class ExtensionMarksAlertsReadTests(NotifySubscriptionExpiryTestCase):
    def test_extension_marks_stale_alerts_read(self):
        self._set_end(self.company, 3)
        notify_subscription_expiry.run()
        self.assertTrue(
            Notification.objects.filter(
                company=self.company,
                type=Notification.NotificationType.SUBSCRIPTION_EXPIRING_SOON,
                is_read=False,
            ).exists(),
        )
        # Суперадмин продлевает — старые предупреждения становятся прочитанными.
        api = APIClient()
        api.force_authenticate(user=self.superadmin)
        resp = api.post(
            f'/api/v1/companies/{self.company.id}/subscription_extend/',
            {'days': 30}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            Notification.objects.filter(
                company=self.company,
                type=Notification.NotificationType.SUBSCRIPTION_EXPIRING_SOON,
                is_read=False,
            ).exists(),
        )

    def test_activation_marks_stale_alerts_read(self):
        self._set_end(self.company, 3)
        notify_subscription_expiry.run()
        api = APIClient()
        api.force_authenticate(user=self.superadmin)
        resp = api.post(f'/api/v1/companies/{self.company.id}/subscription_activate/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            Notification.objects.filter(
                company=self.company,
                type=Notification.NotificationType.SUBSCRIPTION_EXPIRING_SOON,
                is_read=False,
            ).exists(),
        )


class BellApiTests(NotifySubscriptionExpiryTestCase):
    def _run_alerts(self):
        self._set_end(self.company, 4)
        notify_subscription_expiry.run()

    def test_superadmin_sees_platform_notifications_via_bell(self):
        self._run_alerts()
        api = APIClient()
        api.force_authenticate(user=self.superadmin)
        resp = api.get('/api/v1/messaging/notifications/')
        self.assertEqual(resp.status_code, 200)
        results = resp.data.get('results', resp.data)
        self.assertTrue(any(
            n['type'] == Notification.NotificationType.SUBSCRIPTION_EXPIRING_SOON
            and n['company'] == self.company.id
            for n in results
        ))

    def test_superadmin_unread_filter_and_mark_read(self):
        self._run_alerts()
        api = APIClient()
        api.force_authenticate(user=self.superadmin)
        unread = api.get('/api/v1/messaging/notifications/?is_read=false')
        self.assertEqual(unread.status_code, 200)
        results = unread.data.get('results', unread.data)
        self.assertGreater(len(results), 0)

        nid = results[0]['id']
        mark = api.post(f'/api/v1/messaging/notifications/{nid}/mark_read/')
        self.assertEqual(mark.status_code, 200)
        self.assertTrue(mark.data['is_read'])

    def test_owner_sees_only_own_company_notifications(self):
        self._run_alerts()
        api = APIClient()
        api.force_authenticate(user=self.owner)
        resp = api.get('/api/v1/messaging/notifications/')
        self.assertEqual(resp.status_code, 200)
        results = resp.data.get('results', resp.data)
        self.assertTrue(all(n['company'] == self.company.id for n in results))
        self.assertTrue(any(
            n['type'] == Notification.NotificationType.SUBSCRIPTION_EXPIRING_SOON
            for n in results
        ))

    def test_cross_tenant_isolation(self):
        """Сотрудник другой компании не видит чужие уведомления о подписке."""
        self._run_alerts()
        api = APIClient()
        api.force_authenticate(user=self.other_owner)
        resp = api.get('/api/v1/messaging/notifications/')
        self.assertEqual(resp.status_code, 200)
        results = resp.data.get('results', resp.data)
        self.assertEqual(results, [])

    def test_owner_cannot_mark_others_notification(self):
        self._run_alerts()
        other_notif = Notification.objects.get(
            user=self.superadmin, type=Notification.NotificationType.SUBSCRIPTION_EXPIRING_SOON,
        )
        api = APIClient()
        api.force_authenticate(user=self.owner)
        resp = api.post(f'/api/v1/messaging/notifications/{other_notif.id}/mark_read/')
        self.assertEqual(resp.status_code, 404)  # вне queryset владельца


class BellAccessTests(NotifySubscriptionExpiryTestCase):
    def test_unauthenticated_cannot_read_notifications(self):
        resp = APIClient().get('/api/v1/messaging/notifications/')
        self.assertEqual(resp.status_code, 401)

    def test_frozen_company_staff_bell_blocked(self):
        """Сотрудник замороженной компании не получает колокольчик (SaaS gate)."""
        self.company.subscription_status = Company.SubscriptionStatus.FROZEN
        self.company.save(update_fields=['subscription_status'])
        api = APIClient()
        api.force_authenticate(user=self.owner)
        self.assertEqual(api.get('/api/v1/messaging/notifications/').status_code, 403)
