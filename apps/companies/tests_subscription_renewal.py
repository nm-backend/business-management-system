"""
Тесты страницы «Подписка» владельца.

Покрывают GET /companies/my-subscription/ (информация + история), POST
/companies/my-subscription/request-renewal/ (уведомление суперадминам,
push, audit, дедупликация), RBAC (owner/admin — да, worker/superadmin — нет),
доступ владельца замороженной компании (гейт SaaS не блокирует платформенный
контур, но бизнес-API заблокирован) и cross-tenant изоляцию.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.companies.models import Company, SubscriptionChange
from apps.messaging.models import Notification

from .tests_subscriptions import make_admin, make_company, make_owner


class SubscriptionPageTestCase(TestCase):
    """Общий setUp: суперадмин + компания (владелец, админ, работник)."""

    def setUp(self):
        self.superadmin = User.objects.create_superuser(username='root', password='pw')
        self.company = make_company(name='Acme')
        self.owner = make_owner(self.company, username='acme_owner')
        self.admin = make_admin(self.company, username='acme_admin')
        self.worker = User.objects.create_user(
            username='acme_worker', password='secretpw',
            role=User.Role.WORKER, company=self.company,
        )
        self.api_owner = APIClient()
        self.api_owner.force_authenticate(user=self.owner)
        self.api_admin = APIClient()
        self.api_admin.force_authenticate(user=self.admin)
        self.api_worker = APIClient()
        self.api_worker.force_authenticate(user=self.worker)
        self.api_sa = APIClient()
        self.api_sa.force_authenticate(user=self.superadmin)

    def _freeze(self):
        self.company.subscription_status = Company.SubscriptionStatus.FROZEN
        self.company.save(update_fields=['subscription_status'])


class MySubscriptionInfoTests(SubscriptionPageTestCase):
    def test_owner_sees_subscription_info_and_history(self):
        SubscriptionChange.objects.create(
            company=self.company, action=SubscriptionChange.Action.ACTIVATED,
            old_status='', new_status=Company.SubscriptionStatus.ACTIVE,
            old_end=None, new_end=self.company.subscription_end,
            days_added=30, actor=self.superadmin, note='trial',
        )
        resp = self.api_owner.get('/api/v1/companies/my-subscription/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['company_name'], 'Acme')
        self.assertEqual(resp.data['subscription_status'], Company.SubscriptionStatus.ACTIVE)
        self.assertIsNotNone(resp.data['subscription_end'])
        self.assertIsNotNone(resp.data['subscription_start'])
        self.assertGreaterEqual(resp.data['days_left'], 0)
        # История содержит запись о старте подписки.
        actions = [h['action'] for h in resp.data['history']]
        self.assertIn(SubscriptionChange.Action.ACTIVATED, actions)
        # Чужих бизнес-данных нет.
        for key in ('clients', 'orders', 'finance', 'revenue'):
            self.assertNotIn(key, resp.data)

    def test_admin_sees_own_subscription(self):
        resp = self.api_admin.get('/api/v1/companies/my-subscription/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['company_name'], 'Acme')

    def test_worker_cannot_access_subscription_page(self):
        resp = self.api_worker.get('/api/v1/companies/my-subscription/')
        self.assertEqual(resp.status_code, 403)

    def test_superadmin_cannot_access_my_subscription(self):
        resp = self.api_sa.get('/api/v1/companies/my-subscription/')
        self.assertEqual(resp.status_code, 403)

    def test_cross_tenant_owner_cannot_see_other_company(self):
        other = make_company(name='OtherCo')
        other_owner = make_owner(other, username='other_owner')
        other_owner.company.subscription_end = timezone.now() + timedelta(days=99)
        other_owner.company.save(update_fields=['subscription_end'])
        api = APIClient()
        api.force_authenticate(user=other_owner)
        resp = api.get('/api/v1/companies/my-subscription/')
        self.assertEqual(resp.status_code, 200)
        # URL без pk — компания всегда берётся из токена, чужая не подставится.
        self.assertEqual(resp.data['company_name'], 'OtherCo')


class RenewalRequestTests(SubscriptionPageTestCase):
    def test_owner_requests_renewal_creates_superadmin_notification_and_audit(self):
        with patch('apps.accounts.push_service.send_push_to_user') as push:
            resp = self.api_owner.post(
                '/api/v1/companies/my-subscription/request-renewal/', {}, format='json',
            )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.data['created'])

        alerts = Notification.objects.filter(
            user=self.superadmin,
            type=Notification.NotificationType.SUBSCRIPTION_RENEWAL_REQUEST,
        )
        self.assertEqual(alerts.count(), 1)
        self.assertEqual(alerts[0].company_id, self.company.id)
        self.assertIn('Acme', alerts[0].message)
        self.assertFalse(alerts[0].is_read)

        # Push отправлен суперадмину с маршрутом на «Управление бизнесами».
        self.assertEqual(push.call_count, 1)
        self.assertEqual(push.call_args[0][0], self.superadmin)
        self.assertEqual(push.call_args[1]['data']['url'], '/#/companies')

        # Audit записан с действием и актором.
        log = AuditLog.objects.filter(
            action=AuditLog.Action.SUBSCRIPTION_RENEWAL_REQUESTED,
            actor=self.owner,
        )
        self.assertTrue(log.exists())
        self.assertEqual(log.first().company_id, self.company.id)

    def test_request_is_deduplicated(self):
        self.api_owner.post(
            '/api/v1/companies/my-subscription/request-renewal/', {}, format='json',
        )
        with patch('apps.accounts.push_service.send_push_to_user') as push:
            resp = self.api_owner.post(
                '/api/v1/companies/my-subscription/request-renewal/', {}, format='json',
            )
        self.assertEqual(resp.status_code, 200)  # успешный ответ...
        self.assertFalse(resp.data['created'])    # ...но новая запись не создана
        self.assertEqual(
            Notification.objects.filter(
                user=self.superadmin,
                type=Notification.NotificationType.SUBSCRIPTION_RENEWAL_REQUEST,
            ).count(), 1,
        )
        self.assertEqual(push.call_count, 0)
        # Пока запрос непрочитан — повторная подача не спамит.
        self.assertIn('уже отправлен', resp.data['detail'])

    def test_request_after_superadmin_reads_creates_new(self):
        self.api_owner.post(
            '/api/v1/companies/my-subscription/request-renewal/', {}, format='json',
        )
        Notification.objects.filter(
            user=self.superadmin,
            type=Notification.NotificationType.SUBSCRIPTION_RENEWAL_REQUEST,
        ).update(is_read=True)
        with patch('apps.accounts.push_service.send_push_to_user'):
            resp = self.api_owner.post(
                '/api/v1/companies/my-subscription/request-renewal/', {}, format='json',
            )
        self.assertTrue(resp.data['created'])
        self.assertEqual(
            Notification.objects.filter(
                user=self.superadmin,
                type=Notification.NotificationType.SUBSCRIPTION_RENEWAL_REQUEST,
            ).count(), 2,
        )

    def test_worker_cannot_request_renewal(self):
        resp = self.api_worker.post(
            '/api/v1/companies/my-subscription/request-renewal/', {}, format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_superadmin_cannot_request_renewal(self):
        resp = self.api_sa.post(
            '/api/v1/companies/my-subscription/request-renewal/', {}, format='json',
        )
        self.assertEqual(resp.status_code, 403)


class FrozenCompanyAccessTests(SubscriptionPageTestCase):
    def test_frozen_owner_can_view_subscription_and_request_renewal(self):
        self._freeze()
        # Платформенный контур доступен...
        self.assertEqual(
            self.api_owner.get('/api/v1/companies/my-subscription/').status_code, 200,
        )
        with patch('apps.accounts.push_service.send_push_to_user'):
            resp = self.api_owner.post(
                '/api/v1/companies/my-subscription/request-renewal/', {}, format='json',
            )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.data['created'])
        # ...а бизнес-функциональность заблокирована.
        self.assertEqual(
            self.api_owner.get('/api/v1/warehouse/raw-materials/').status_code, 403,
        )

    def test_frozen_admin_can_view_subscription(self):
        self._freeze()
        self.assertEqual(
            self.api_admin.get('/api/v1/companies/my-subscription/').status_code, 200,
        )

    def test_frozen_worker_still_blocked_everywhere(self):
        self._freeze()
        self.assertEqual(
            self.api_worker.get('/api/v1/companies/my-subscription/').status_code, 403,
        )
        self.assertEqual(
            self.api_worker.get('/api/v1/warehouse/raw-materials/').status_code, 403,
        )

    def test_renewal_request_works_when_expired(self):
        self.company.subscription_status = Company.SubscriptionStatus.EXPIRED
        self.company.subscription_end = timezone.now() - timedelta(days=5)
        self.company.save(update_fields=['subscription_status', 'subscription_end'])
        with patch('apps.accounts.push_service.send_push_to_user'):
            resp = self.api_owner.post(
                '/api/v1/companies/my-subscription/request-renewal/', {}, format='json',
            )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.data['created'])


class RenewalProcessingTests(SubscriptionPageTestCase):
    """
    Замкнутый цикл продления: суперадмин обрабатывает запрос -> запрос
    закрывается (дедупликация сбрасывается), владелец/админ получают
    уведомление «Подписка продлена» (колокольчик + push) с переходом на
    страницу «Подписка». Триал при создании и заморозка НЕ уведомляют.
    """

    def _request_renewal(self):
        with patch('apps.accounts.push_service.send_push_to_user'):
            resp = self.api_owner.post(
                '/api/v1/companies/my-subscription/request-renewal/', {}, format='json',
            )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.data['created'])
        self.assertTrue(Notification.objects.filter(
            user=self.superadmin,
            type=Notification.NotificationType.SUBSCRIPTION_RENEWAL_REQUEST,
            is_read=False,
        ).exists())

    def _owner_alerts(self):
        return Notification.objects.filter(
            user=self.owner,
            type=Notification.NotificationType.SUBSCRIPTION_EXTENDED,
        )

    def test_extend_closes_request_and_notifies_owner(self):
        self._request_renewal()
        self.assertTrue(self.api_owner.get(
            '/api/v1/companies/my-subscription/'
        ).data['renewal_request_pending'])

        with patch('apps.accounts.push_service.send_push_to_user') as push:
            resp = self.api_sa.post(
                f'/api/v1/companies/{self.company.id}/subscription_extend/',
                {'days': 30}, format='json',
            )
        self.assertEqual(resp.status_code, 200)

        # Запрос обработан: суперадмину не висит непрочитанный запрос,
        # у владельца renewal_request_pending = False.
        self.assertFalse(Notification.objects.filter(
            user=self.superadmin,
            type=Notification.NotificationType.SUBSCRIPTION_RENEWAL_REQUEST,
            is_read=False,
        ).exists())
        self.assertFalse(self.api_owner.get(
            '/api/v1/companies/my-subscription/'
        ).data['renewal_request_pending'])

        # Владелец и админ получили уведомление о продлении, привязанное
        # к компании, с НОВОЙ датой окончания.
        self.company.refresh_from_db()
        alerts = self._owner_alerts()
        self.assertEqual(alerts.count(), 1)
        self.assertEqual(alerts[0].company_id, self.company.id)
        self.assertIn('Acme', alerts[0].message)
        self.assertIn(self.company.subscription_end.strftime('%d.%m.%Y'), alerts[0].message)
        admin_alerts = Notification.objects.filter(
            user=self.admin,
            type=Notification.NotificationType.SUBSCRIPTION_EXTENDED,
        )
        self.assertEqual(admin_alerts.count(), 1)

        # Push отправлен владельцу и админу с переходом на страницу «Подписка».
        pushed_users = [call.args[0] for call in push.call_args_list]
        self.assertIn(self.owner, pushed_users)
        self.assertIn(self.admin, pushed_users)
        for call in push.call_args_list:
            self.assertEqual(call.kwargs['data']['url'], '/#/subscription')

    def test_request_can_be_requested_again_after_processing(self):
        # После обработки дедупликация сброшена: владелец может запросить
        # продление снова (новое уведомление суперадмину создаётся).
        self._request_renewal()
        with patch('apps.accounts.push_service.send_push_to_user'):
            self.api_sa.post(
                f'/api/v1/companies/{self.company.id}/subscription_extend/',
                {'days': 30}, format='json',
            )
        with patch('apps.accounts.push_service.send_push_to_user'):
            resp = self.api_owner.post(
                '/api/v1/companies/my-subscription/request-renewal/', {}, format='json',
            )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.data['created'])
        self.assertEqual(
            Notification.objects.filter(
                user=self.superadmin,
                type=Notification.NotificationType.SUBSCRIPTION_RENEWAL_REQUEST,
            ).count(), 2,
        )

    def test_activate_notifies_owner(self):
        self.company.subscription_status = Company.SubscriptionStatus.FROZEN
        self.company.save(update_fields=['subscription_status'])
        with patch('apps.accounts.push_service.send_push_to_user'):
            resp = self.api_sa.post(
                f'/api/v1/companies/{self.company.id}/subscription_activate/', {}, format='json',
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._owner_alerts().count(), 1)

    def test_set_end_notifies_owner(self):
        future = timezone.now() + timedelta(days=60)
        with patch('apps.accounts.push_service.send_push_to_user'):
            resp = self.api_sa.post(
                f'/api/v1/companies/{self.company.id}/subscription_set_end/',
                {'end': future.isoformat()}, format='json',
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._owner_alerts().count(), 1)

    def test_unfreeze_notifies_owner(self):
        self.company.subscription_status = Company.SubscriptionStatus.FROZEN
        self.company.save(update_fields=['subscription_status'])
        with patch('apps.accounts.push_service.send_push_to_user'):
            resp = self.api_sa.post(
                f'/api/v1/companies/{self.company.id}/subscription_unfreeze/', {}, format='json',
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._owner_alerts().count(), 1)

    def test_freeze_does_not_notify_extended(self):
        with patch('apps.accounts.push_service.send_push_to_user'):
            resp = self.api_sa.post(
                f'/api/v1/companies/{self.company.id}/subscription_freeze/', {}, format='json',
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._owner_alerts().count(), 0)

    def test_trial_creation_does_not_notify_owner(self):
        # При создании компании (триал) уведомление «подписка продлена» —
        # это был бы спам; владелец только что получил аккаунт.
        with patch('apps.accounts.push_service.send_push_to_user') as push:
            resp = self.api_sa.post('/api/v1/companies/', {
                'name': 'FreshCo',
                'owner_username': 'fresh_owner',
                'owner_password': 'Str0ng!Pass',
                'owner_full_name': 'Fresh Owner',
            }, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(
            Notification.objects.filter(
                type=Notification.NotificationType.SUBSCRIPTION_EXTENDED,
            ).count(), 0,
        )
        self.assertEqual(push.call_count, 0)

    def test_company_list_has_renewal_request_flag(self):
        def flag():
            resp = self.api_sa.get('/api/v1/companies/')
            row = next(c for c in resp.data['results'] if c['id'] == self.company.id)
            return row['has_renewal_request']

        self.assertFalse(flag())
        self._request_renewal()
        self.assertTrue(flag())
        with patch('apps.accounts.push_service.send_push_to_user'):
            self.api_sa.post(
                f'/api/v1/companies/{self.company.id}/subscription_extend/',
                {'days': 30}, format='json',
            )
        self.assertFalse(flag())

    def test_expired_owner_request_processed_by_extension(self):
        # Истёкшая компания: владелец запросил продление, суперадмин продлил —
        # компания снова активна, владелец уведомлён, доступ восстановлен.
        self.company.subscription_status = Company.SubscriptionStatus.EXPIRED
        self.company.subscription_end = timezone.now() - timedelta(days=5)
        self.company.save(update_fields=['subscription_status', 'subscription_end'])
        self._request_renewal()
        with patch('apps.accounts.push_service.send_push_to_user'):
            resp = self.api_sa.post(
                f'/api/v1/companies/{self.company.id}/subscription_extend/',
                {'days': 30}, format='json',
            )
        self.assertEqual(resp.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.ACTIVE)
        self.assertEqual(self._owner_alerts().count(), 1)
        # Бизнес-доступ восстановлен.
        self.assertEqual(
            self.api_owner.get('/api/v1/warehouse/raw-materials/').status_code, 200,
        )


class BillingSubscriptionSyncTests(SubscriptionPageTestCase):
    """
    Единый источник истины: Company.subscription_* зеркалится в billing.Subscription.

    Раньше синхронизация была односторонней (billing -> company), поэтому
    продление/заморозка через компании-API (superadmin UI) не сдвигали
    billing-часы: billing-задача check_expired_subscriptions замораживала уже
    продлённую компанию по устаревшему expires_at, а гейт (fallback по
    Subscription.is_blocked) блокировал её бизнес-доступ.
    """

    def test_extend_via_companies_api_syncs_billing_subscription(self):
        from apps.billing.models import Subscription

        end_before = self.company.subscription_end
        with patch('apps.accounts.push_service.send_push_to_user'):
            resp = self.api_sa.post(
                f'/api/v1/companies/{self.company.id}/subscription_extend/',
                {'days': 30}, format='json',
            )
        self.assertEqual(resp.status_code, 200)
        self.company.refresh_from_db()
        sub = Subscription.objects.get(company=self.company)
        self.assertGreater(sub.expires_at, end_before)
        self.assertEqual(sub.expires_at, self.company.subscription_end)
        self.assertEqual(sub.status, 'active')

    def test_freeze_via_companies_api_syncs_billing_subscription(self):
        from apps.billing.models import Subscription

        resp = self.api_sa.post(
            f'/api/v1/companies/{self.company.id}/subscription_freeze/',
            {}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        sub = Subscription.objects.get(company=self.company)
        self.assertEqual(sub.status, 'frozen')
        self.assertIsNotNone(sub.frozen_at)

    def test_activate_via_companies_api_syncs_billing_subscription(self):
        from apps.billing.models import Subscription

        # Замороженная компания с истёкшим сроком: активация выдаёт свежие 30 дней.
        self.company.subscription_status = Company.SubscriptionStatus.FROZEN
        self.company.subscription_end = timezone.now() - timedelta(days=5)
        self.company.save(update_fields=['subscription_status', 'subscription_end'])
        with patch('apps.accounts.push_service.send_push_to_user'):
            resp = self.api_sa.post(
                f'/api/v1/companies/{self.company.id}/subscription_activate/',
                {}, format='json',
            )
        self.assertEqual(resp.status_code, 200)
        self.company.refresh_from_db()
        sub = Subscription.objects.get(company=self.company)
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.expires_at, self.company.subscription_end)
        self.assertGreater(sub.expires_at, timezone.now())
        self.assertIsNone(sub.frozen_at)
