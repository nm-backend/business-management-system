"""
Тесты тарифов (планов), льготного периода (grace), флага триала и уведомлений
жизненного цикла подписки.

Покрывают: назначение плана по умолчанию, смену тарифа (история + аудит +
уведомление, RBAC), снятие триала при ручных действиях, переход active -> grace
(бизнес работает, уведомление с датой блокировки), grace -> expired
(блокировка + уведомление), дедупликацию уведомлений при повторных запусках.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.companies.models import Company, SubscriptionChange, SubscriptionPlan
from apps.companies.tasks import auto_freeze_expired_subscriptions
from apps.messaging.models import Notification

from .tests_subscriptions import make_admin, make_company, make_owner


class SubscriptionPlansTestCase(TestCase):
    """Общий setUp: суперадмин + компания с владельцем/админом."""

    def setUp(self):
        self.superadmin = User.objects.create_superuser(username='root', password='pw')
        self.api = APIClient()
        self.api.force_authenticate(user=self.superadmin)
        self.company = make_company(name='Acme')
        self.owner = make_owner(self.company, username='acme_owner')
        self.admin = make_admin(self.company, username='acme_admin')
        self.api_owner = APIClient()
        self.api_owner.force_authenticate(user=self.owner)
        self.api_admin = APIClient()
        self.api_admin.force_authenticate(user=self.admin)
        self.free_trial = SubscriptionPlan.objects.get(code='free_trial')
        self.basic = SubscriptionPlan.objects.get(code='basic')
        self.business = SubscriptionPlan.objects.get(code='business')

    def _alerts(self, user, ntype=None):
        qs = Notification.objects.filter(user=user)
        if ntype:
            qs = qs.filter(type=ntype)
        return list(qs)


class PlanModelTests(SubscriptionPlansTestCase):
    def test_plans_seeded(self):
        codes = set(SubscriptionPlan.objects.values_list('code', flat=True))
        self.assertIn('free_trial', codes)
        self.assertIn('basic', codes)
        self.assertIn('business', codes)
        self.assertIn('enterprise', codes)
        self.assertTrue(SubscriptionPlan.objects.get(code='free_trial').is_default)

    def test_new_company_gets_default_plan_and_trial(self):
        resp = self.api.post('/api/v1/companies/', {
            'name': 'NewCo',
            'owner_username': 'newco_owner',
            'owner_password': 'Str0ng!Pass',
            'owner_full_name': 'New Owner',
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        company = Company.objects.get(name='NewCo')
        self.assertEqual(company.plan_id, self.free_trial.id)
        self.assertTrue(company.is_trial)
        self.assertEqual(company.subscription_status, Company.SubscriptionStatus.ACTIVE)

    def test_make_company_helper_assigns_plan(self):
        self.assertEqual(self.company.plan_id, self.free_trial.id)
        self.assertTrue(self.company.is_trial)


class ChangePlanTests(SubscriptionPlansTestCase):
    def test_superadmin_changes_plan_with_history_audit_notification(self):
        with patch('apps.accounts.push_service.send_push_to_user') as push:
            resp = self.api.post(
                f'/api/v1/companies/{self.company.id}/subscription_change_plan/',
                {'plan_id': self.business.id}, format='json',
            )
        self.assertEqual(resp.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.plan_id, self.business.id)
        # Триал снят: выбор тарифа супер-админом = конец бесплатного периода.
        self.assertFalse(self.company.is_trial)

        # История: старая и новая планы записаны, статус не менялся.
        change = self.company.subscription_changes.filter(
            action=SubscriptionChange.Action.PLAN_CHANGED,
        ).first()
        self.assertIsNotNone(change)
        self.assertEqual(change.old_plan, 'Free Trial')
        self.assertEqual(change.new_plan, 'Business')
        self.assertEqual(change.old_status, change.new_status)

        # Audit с привязкой к компании и актором.
        self.assertTrue(AuditLog.objects.filter(
            company=self.company, action=AuditLog.Action.SUBSCRIPTION_PLAN_CHANGED,
            actor=self.superadmin,
        ).exists())

        # Уведомление владельцу и админу (колокольчик + push).
        self.assertEqual(len(self._alerts(self.owner, Notification.NotificationType.SUBSCRIPTION_PLAN_CHANGED)), 1)
        self.assertEqual(len(self._alerts(self.admin, Notification.NotificationType.SUBSCRIPTION_PLAN_CHANGED)), 1)
        self.assertIn('Business', self._alerts(self.owner)[0].message)
        pushed = {call.args[0] for call in push.call_args_list}
        self.assertIn(self.owner, pushed)
        self.assertIn(self.admin, pushed)

    def test_change_plan_keeps_subscription_dates(self):
        end_before = self.company.subscription_end
        self.api.post(
            f'/api/v1/companies/{self.company.id}/subscription_change_plan/',
            {'plan_id': self.basic.id}, format='json',
        )
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_end, end_before)
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.ACTIVE)

    def test_change_plan_same_plan_rejected(self):
        resp = self.api.post(
            f'/api/v1/companies/{self.company.id}/subscription_change_plan/',
            {'plan_id': self.free_trial.id}, format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(self.company.subscription_changes.filter(
            action=SubscriptionChange.Action.PLAN_CHANGED,
        ).exists())

    def test_change_plan_missing_and_invalid_plan(self):
        resp = self.api.post(
            f'/api/v1/companies/{self.company.id}/subscription_change_plan/',
            {}, format='json',
        )
        self.assertEqual(resp.status_code, 400)
        resp = self.api.post(
            f'/api/v1/companies/{self.company.id}/subscription_change_plan/',
            {'plan_id': 999999}, format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_change_plan_inactive_plan_rejected(self):
        self.business.is_active = False
        self.business.save(update_fields=['is_active'])
        resp = self.api.post(
            f'/api/v1/companies/{self.company.id}/subscription_change_plan/',
            {'plan_id': self.business.id}, format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.company.refresh_from_db()
        self.assertEqual(self.company.plan_id, self.free_trial.id)

    def test_plans_list_only_active(self):
        self.business.is_active = False
        self.business.save(update_fields=['is_active'])
        resp = self.api.get('/api/v1/companies/plans/')
        self.assertEqual(resp.status_code, 200)
        codes = [p['code'] for p in resp.data]
        self.assertIn('free_trial', codes)
        self.assertIn('basic', codes)
        self.assertNotIn('business', codes)

    def test_owner_cannot_change_plan(self):
        resp = self.api_owner.post(
            f'/api/v1/companies/{self.company.id}/subscription_change_plan/',
            {'plan_id': self.basic.id}, format='json',
        )
        self.assertEqual(resp.status_code, 403)
        self.company.refresh_from_db()
        self.assertEqual(self.company.plan_id, self.free_trial.id)

    def test_admin_cannot_change_plan(self):
        resp = self.api_admin.post(
            f'/api/v1/companies/{self.company.id}/subscription_change_plan/',
            {'plan_id': self.basic.id}, format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_worker_cannot_change_plan(self):
        worker = User.objects.create_user(
            username='acme_worker', password='secretpw',
            role=User.Role.WORKER, company=self.company,
        )
        api = APIClient()
        api.force_authenticate(user=worker)
        resp = api.post(
            f'/api/v1/companies/{self.company.id}/subscription_change_plan/',
            {'plan_id': self.basic.id}, format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_owner_cannot_list_plans(self):
        resp = self.api_owner.get('/api/v1/companies/plans/')
        self.assertEqual(resp.status_code, 403)

    def test_plan_cannot_be_changed_via_patch(self):
        resp = self.api.patch(
            f'/api/v1/companies/{self.company.id}/',
            {'plan_id': self.basic.id}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.plan_id, self.free_trial.id)


class TrialFlagTests(SubscriptionPlansTestCase):
    def test_extend_clears_trial(self):
        self.assertTrue(self.company.is_trial)
        self.api.post(
            f'/api/v1/companies/{self.company.id}/subscription_extend/',
            {'days': 30}, format='json',
        )
        self.company.refresh_from_db()
        self.assertFalse(self.company.is_trial)

    def test_activate_clears_trial(self):
        self.api.post(
            f'/api/v1/companies/{self.company.id}/subscription_activate/', {}, format='json',
        )
        self.company.refresh_from_db()
        self.assertFalse(self.company.is_trial)

    def test_freeze_keeps_trial(self):
        self.api.post(
            f'/api/v1/companies/{self.company.id}/subscription_freeze/', {}, format='json',
        )
        self.company.refresh_from_db()
        self.assertTrue(self.company.is_trial)

    def test_trial_visible_in_me_and_my_subscription(self):
        me = self.api_owner.get('/api/v1/accounts/me/')
        self.assertEqual(me.status_code, 200)
        sub = self.api_owner.get('/api/v1/companies/my-subscription/')
        self.assertEqual(sub.status_code, 200)
        self.assertTrue(sub.data['is_trial'])
        self.assertEqual(sub.data['plan_name'], 'Free Trial')


class GraceLifecycleTests(SubscriptionPlansTestCase):
    def _expire_end(self, company, days_ago):
        company.subscription_end = timezone.now() - timedelta(days=days_ago)
        company.save(update_fields=['subscription_end'])

    def test_task_moves_to_grace_and_notifies_with_deadline(self):
        self._expire_end(self.company, 1)  # в пределах grace (7 дней)
        with patch('apps.accounts.push_service.send_push_to_user') as push:
            processed = auto_freeze_expired_subscriptions.run()
        self.assertEqual(processed, 1)
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.GRACE)

        # История и аудит.
        self.assertTrue(self.company.subscription_changes.filter(
            action=SubscriptionChange.Action.GRACE_STARTED,
        ).exists())
        self.assertTrue(AuditLog.objects.filter(
            company=self.company, action=AuditLog.Action.SUBSCRIPTION_GRACE_STARTED,
        ).exists())

        # Уведомление владельцу и суперадмину, с датой блокировки.
        for user in (self.owner, self.superadmin):
            alerts = self._alerts(user, Notification.NotificationType.SUBSCRIPTION_GRACE_STARTED)
            self.assertEqual(len(alerts), 1, msg=user.username)
            deadline = self.company.grace_end.strftime('%d.%m.%Y')
            self.assertIn(deadline, alerts[0].message)
        self.assertEqual(push.call_count, 3)  # владелец + админ + суперадмин

        # Бизнес-доступ в льготный период сохранён.
        self.assertEqual(
            self.api_owner.get('/api/v1/warehouse/raw-materials/').status_code, 200,
        )

    def test_grace_notification_deduplicated_on_rerun(self):
        self._expire_end(self.company, 1)
        auto_freeze_expired_subscriptions.run()
        auto_freeze_expired_subscriptions.run()  # повторный запуск
        self.assertEqual(
            len(self._alerts(self.owner, Notification.NotificationType.SUBSCRIPTION_GRACE_STARTED)),
            1,
        )
        self.assertEqual(
            self.company.subscription_changes.filter(
                action=SubscriptionChange.Action.GRACE_STARTED,
            ).count(), 1,
        )

    def test_grace_to_expired_notifies_owner(self):
        self._expire_end(self.company, 1)
        auto_freeze_expired_subscriptions.run()
        # Льготный период вышел.
        self._expire_end(self.company, 8)
        with patch('apps.accounts.push_service.send_push_to_user') as push:
            processed = auto_freeze_expired_subscriptions.run()
        self.assertEqual(processed, 1)
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.EXPIRED)
        self.assertEqual(
            len(self._alerts(self.owner, Notification.NotificationType.SUBSCRIPTION_EXPIRED)), 1,
        )
        self.assertEqual(push.call_count, 2)  # владелец + админ
        # Доступ заблокирован.
        self.assertEqual(
            self.api_owner.get('/api/v1/warehouse/raw-materials/').status_code, 403,
        )

    def test_expired_notification_deduplicated_on_rerun(self):
        self._expire_end(self.company, 8)
        auto_freeze_expired_subscriptions.run()
        auto_freeze_expired_subscriptions.run()
        self.assertEqual(
            len(self._alerts(self.owner, Notification.NotificationType.SUBSCRIPTION_EXPIRED)), 1,
        )
        self.assertEqual(
            self.company.subscription_changes.filter(
                action=SubscriptionChange.Action.EXPIRED,
            ).count(), 1,
        )

    def test_grace_company_renewal_restores_access_and_clears_trial(self):
        self._expire_end(self.company, 1)
        auto_freeze_expired_subscriptions.run()
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.GRACE)
        with patch('apps.accounts.push_service.send_push_to_user'):
            resp = self.api.post(
                f'/api/v1/companies/{self.company.id}/subscription_extend/',
                {'days': 30}, format='json',
            )
        self.assertEqual(resp.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.ACTIVE)
        self.assertFalse(self.company.is_trial)
        self.assertGreater(self.company.subscription_end, timezone.now())
        # Старое предупреждение grace стало прочитанным.
        self.assertFalse(Notification.objects.filter(
            company=self.company,
            type=Notification.NotificationType.SUBSCRIPTION_GRACE_STARTED,
            is_read=False,
        ).exists())

    def test_manual_freeze_from_grace(self):
        self._expire_end(self.company, 1)
        auto_freeze_expired_subscriptions.run()
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.GRACE)
        resp = self.api.post(
            f'/api/v1/companies/{self.company.id}/subscription_freeze/', {}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.FROZEN)
        # Автозадача не трогает ручную заморозку.
        auto_freeze_expired_subscriptions.run()
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.FROZEN)

    def test_grace_visible_in_my_subscription(self):
        self._expire_end(self.company, 1)
        auto_freeze_expired_subscriptions.run()
        resp = self.api_owner.get('/api/v1/companies/my-subscription/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['subscription_status'], Company.SubscriptionStatus.GRACE)
        self.assertIsNotNone(resp.data['grace_end'])
        self.assertGreaterEqual(resp.data['grace_days_left'], 0)


class GraceEdgeCaseTests(SubscriptionPlansTestCase):
    def test_zero_grace_period_goes_straight_to_expired(self):
        self.company.grace_period_days = 0
        self.company.subscription_end = timezone.now() - timedelta(minutes=1)
        self.company.save(update_fields=['grace_period_days', 'subscription_end'])
        processed = auto_freeze_expired_subscriptions.run()
        self.assertEqual(processed, 1)
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.EXPIRED)
        self.assertFalse(self.company.subscription_changes.filter(
            action=SubscriptionChange.Action.GRACE_STARTED,
        ).exists())

    def test_future_end_not_touched(self):
        processed = auto_freeze_expired_subscriptions.run()
        self.assertEqual(processed, 0)
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_status, Company.SubscriptionStatus.ACTIVE)
